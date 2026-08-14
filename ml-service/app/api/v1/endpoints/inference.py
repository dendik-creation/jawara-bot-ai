"""Inference endpoints: embed, rag-query, generate, train, evaluate, classify.

Every response carries `model_version` — the audit trail has to be able to name
which model decided something, and "the model we happened to be running that
week" is not an answer.
"""

import asyncio
import logging
import uuid
from collections import Counter
from pathlib import Path

from fastapi import APIRouter, Depends

from app.api.deps import Timer, envelope, get_repository
from app.core.config import get_settings
from app.core.errors import MlError
from app.core.security import verify_internal_key
from app.llm.prompt import GenerationRequest
from app.llm.template_provider import TemplateProvider
from app.llm.validator import status_for_risk, validate_response
from app.models import classifier as classifier_module
from app.models.registry import registry
from app.rag import claim as claim_module
from app.rag.qdrant_repo import QdrantRepository
from app.rag.ranking import rerank
from app.schemas.contract import MlRequest, MlResponse

logger = logging.getLogger("app.api.inference")

router = APIRouter(dependencies=[Depends(verify_internal_key)])


def _parse_samples(dataset_payload: dict) -> list[tuple[str, str]]:
    raw_samples = dataset_payload.get("samples") or []
    if not isinstance(raw_samples, list) or not raw_samples:
        raise MlError("invalid_payload", "payload.dataset.samples must be a non-empty list", retryable=False)
    try:
        return [(str(item["text"]), str(item["label"])) for item in raw_samples]
    except (KeyError, TypeError) as exc:
        raise MlError("invalid_payload", "each sample needs 'text' and 'label'", retryable=False) from exc


def _artifact_path(model_version: str) -> Path:
    return Path(get_settings().model_artifact_dir) / f"{model_version}.joblib"


def _load_classifier(model_version: str, expected_sha256: str) -> classifier_module.TrainedClassifier:
    try:
        return registry.classifier(model_version, expected_sha256)
    except FileNotFoundError as exc:
        raise MlError(
            "model_not_available",
            f"no classifier artifact for version {model_version}",
            status_code=503,
            retryable=False,
        ) from exc
    except classifier_module.ArtifactIntegrityError as exc:
        raise MlError("artifact_integrity_failed", str(exc), status_code=409, retryable=False) from exc


@router.post("/embed", response_model=MlResponse)
async def embed(request: MlRequest) -> MlResponse:
    texts = request.payload.get("texts") or []
    if not isinstance(texts, list) or not all(isinstance(text, str) for text in texts):
        raise MlError("invalid_payload", "payload.texts must be a list of strings", retryable=False)

    embedder = registry.embedder()
    with Timer() as timer:
        vectors = await embedder.embed(texts)

    return envelope(
        request.request_id,
        {"vectors": vectors, "dim": embedder.dim, "count": len(vectors)},
        embedder.model_version,
        timer.elapsed_ms,
    )


@router.post("/rag-query", response_model=MlResponse)
async def rag_query(
    request: MlRequest,
    repository: QdrantRepository = Depends(get_repository),
) -> MlResponse:
    """Embed the claim, run the documented filtered search, then re-rank.

    Below-threshold results are reported as `unverified: true` with an empty
    match list. Returning the nearest weak match instead would let the generator
    write a confident answer on top of an unrelated fact — the single most
    damaging failure mode this pipeline has.

    Re-ranking (app/rag/ranking.py) reorders what came back by source
    reliability and freshness and cuts to `top_k`. It never changes which
    matches passed the similarity threshold, and `score` stays the raw cosine
    similarity the audit row records — see that module for why.
    """
    settings = get_settings()
    query = (request.payload.get("query") or "").strip()
    if not query:
        raise MlError("invalid_payload", "payload.query must be a non-empty string", retryable=False)

    category = request.payload.get("category")
    top_k = int(request.payload.get("top_k") or settings.rag_top_k)
    threshold = float(
        request.payload.get("score_threshold")
        if request.payload.get("score_threshold") is not None
        else settings.rag_score_threshold
    )
    # Per-request override so an operator tool can inspect raw retrieval
    # without redeploying the service with re-ranking off.
    reranking = settings.rag_rerank_enabled and request.payload.get("rerank") is not False
    # Overfetch, then trim: re-ordering exactly `top_k` candidates can never
    # promote a trustworthy fourth match over a shaky third.
    fetch_k = top_k * max(1, settings.rag_rerank_overfetch) if reranking else top_k

    embedder = registry.embedder()
    with Timer() as timer:
        vectors = await embedder.embed([query])
        try:
            matches = await repository.search(
                vector=vectors[0], category=category, top_k=fetch_k, score_threshold=threshold
            )
        except Exception as exc:  # noqa: BLE001
            # Qdrant down: the pipeline continues without knowledge context and
            # the answer is marked low-confidence (02_Data_Pipeline §6).
            logger.warning("qdrant retrieval failed", extra={"error": type(exc).__name__})
            raise MlError(
                "retrieval_unavailable", type(exc).__name__, status_code=503, retryable=True
            ) from exc

        candidate_count = len(matches)
        if reranking:
            matches = rerank(
                matches,
                top_k=top_k,
                reliability_weight=settings.rag_reliability_weight,
                recency_weight=settings.rag_recency_weight,
                half_life_days=settings.rag_recency_half_life_days,
            )
        else:
            matches = matches[:top_k]

    # The raw similarity of the top-*ranked* match — the one the generator will
    # actually cite. Not the discounted score (the audit row must stay able to
    # answer "how well did retrieval match"), and not the maximum across the
    # list, which before re-ranking were the same number and now are not.
    top_score = float(matches[0].get("score") or 0.0) if matches else 0.0
    return envelope(
        request.request_id,
        {
            "matches": matches,
            "unverified": not matches,
            "score_threshold": threshold,
            "category_filter": category,
            "top_k": top_k,
            "reranked": reranking,
            "candidates_considered": candidate_count,
        },
        embedder.model_version,
        timer.elapsed_ms,
        confidence=top_score,
    )


@router.post("/extract-claim", response_model=MlResponse)
async def extract_claim(request: MlRequest) -> MlResponse:
    """Canonicalise a forwarded WhatsApp message into one claim sentence.

    Called by the gateway immediately before `/rag-query`, so retrieval matches
    on the claim rather than on the greeting, emoji and "TOLONG SEBARKAN!!!"
    wrapped around it (app/rag/claim.py explains why that gap matters).

    Never fails on a provider problem: the deterministic heuristic is always
    available, and `fallback_used`/`fallback_reason` say when it was used.
    """
    text = str(request.payload.get("text") or "")
    if not text.strip():
        raise MlError("invalid_payload", "payload.text must be a non-empty string", retryable=False)

    settings = get_settings()
    with Timer() as timer:
        extraction = await claim_module.extract_claim(
            text, provider=registry.llm(), settings=settings
        )

    logger.info(
        "claim extracted",
        extra={
            "request_id": request.request_id,
            "method": extraction.method,
            "fallback_used": extraction.fallback_used,
        },
    )
    return envelope(
        request.request_id,
        extraction.as_result(text),
        extraction.model_version,
        timer.elapsed_ms,
    )


@router.post("/generate", response_model=MlResponse)
async def generate(request: MlRequest) -> MlResponse:
    """Generate the four-section WhatsApp reply and enforce the contract.

    Order matters: generate, then validate, then repair. A response that fails
    validation is never returned to the gateway — it is replaced by the
    deterministic composer, and `fallback_used` says so in the audit trail.
    """
    payload = request.payload
    generation = GenerationRequest(
        user_text=str(payload.get("user_text") or "").strip(),
        category=payload.get("category"),
        risk_level=str(payload.get("risk_level") or "UNKNOWN"),
        context=list(payload.get("context") or []),
        url_verdicts=list(payload.get("url_verdicts") or []),
    )
    if not generation.user_text:
        raise MlError("invalid_payload", "payload.user_text must not be empty", retryable=False)

    provider = registry.llm()
    fallback = TemplateProvider()
    fallback_reason = ""

    # The deterministic mapping is the source of truth (task Part 1): the LLM
    # explains `risk_level`, it never chooses the status. `validate_response`
    # rejects any reply whose status marker doesn't match this exactly, so a
    # provider that answers "HIGH" for a computed UNKNOWN — or "LOW" for a
    # computed HIGH — never reaches `dispatch`; it is discarded in favour of
    # the deterministic composer below, same as any other contract violation.
    expected_status = status_for_risk(generation.risk_level, category=generation.category)
    llm_status = ""
    status_mismatch = False

    with Timer() as timer:
        try:
            text = await provider.generate(generation)
        except MlError as exc:
            logger.warning(
                "llm generation failed, composing deterministic reply",
                extra={"request_id": request.request_id, "error": exc.error_code},
            )
            text = fallback.compose(generation)
            fallback_reason = exc.error_code

        validated = validate_response(text, expected_status=expected_status)
        llm_status = validated.status
        status_mismatch = "status_mismatch" in validated.violations
        if not validated.is_valid:
            logger.warning(
                "generated reply failed the four-section contract, repairing",
                extra={"request_id": request.request_id, "violations": list(validated.violations)},
            )
            fallback_reason = fallback_reason or f"contract:{','.join(validated.violations)}"
            validated = validate_response(fallback.compose(generation), expected_status=expected_status)

        logger.info(
            "url safety status check" if generation.category == "PHISHING_LINK" else "risk status check",
            extra={
                "request_id": request.request_id,
                "category": generation.category,
                "computed_risk": generation.risk_level,
                "expected_status": expected_status,
                "llm_status": llm_status,
                "status_mismatch": status_mismatch,
                "final_status": validated.status,
                "url_verdicts": generation.url_verdicts,
            },
        )

    if not validated.is_valid:
        # The deterministic composer failing its own contract is a code bug, not
        # a provider problem — surface it instead of sending a broken reply.
        raise MlError(
            "response_contract_violation",
            f"composer output invalid: {','.join(validated.violations)}",
            status_code=500,
            retryable=False,
        )

    model_version = fallback.model_version if fallback_reason else provider.model_version
    return envelope(
        request.request_id,
        {
            "message": validated.text,
            "sections": validated.as_sections(),
            "warnings": list(validated.warnings),
            "fallback_used": bool(fallback_reason),
            "fallback_reason": fallback_reason,
        },
        model_version,
        timer.elapsed_ms,
    )


@router.post("/train", response_model=MlResponse)
async def train_model(request: MlRequest) -> MlResponse:
    """Fit a fresh classifier from the samples the gateway sends inline.

    ml-service has no database of its own (the backend/ml-service split in
    02_Architecture/04_ML_Service.md) — the caller ships the dataset's rows in
    the request body rather than a reference this service could look up
    itself. The result is a CANDIDATE artifact only: nothing here promotes it
    to production (07_Model_Registry_and_Deployment §3-4) — that is a separate,
    explicit, human action recorded by the gateway.
    """
    dataset = request.payload.get("dataset") or {}
    samples = _parse_samples(dataset)

    model_version = f"clf-{uuid.uuid4().hex[:12]}"
    with Timer() as timer:
        # single uvicorn worker (Dockerfile) — a synchronous sklearn fit here
        # would block every other in-flight request (classify/generate for
        # the live bot included) for the whole training run. to_thread keeps
        # the event loop free.
        model = await asyncio.to_thread(classifier_module.train, samples)
        artifact_sha256 = await asyncio.to_thread(classifier_module.save, model, _artifact_path(model_version))
        registry.register_classifier(model_version, artifact_sha256, model)
        train_metrics = await asyncio.to_thread(model.evaluate, samples)

    return envelope(
        request.request_id,
        {
            "train_metrics": train_metrics,
            "artifact_sha256": artifact_sha256,
            "label_counts": dict(Counter(label for _, label in samples)),
        },
        model_version,
        timer.elapsed_ms,
    )


@router.post("/evaluate", response_model=MlResponse)
async def evaluate_model(request: MlRequest) -> MlResponse:
    """Score a trained model against a fixed, held-out eval dataset.

    `model_version`/`expected_sha256` are required in the payload for the same
    reason `/classify` needs them: ml-service has no registry of its own to
    consult, so the gateway states up front which artifact it trusts.
    """
    model_version = str(request.payload.get("model_version") or "")
    expected_sha256 = str(request.payload.get("expected_sha256") or "")
    if not model_version or not expected_sha256:
        raise MlError(
            "invalid_payload", "payload.model_version and payload.expected_sha256 are required", retryable=False
        )

    dataset = request.payload.get("dataset") or {}
    samples = _parse_samples(dataset)

    with Timer() as timer:
        # same reasoning as /train: keep this off the single event loop.
        model = await asyncio.to_thread(_load_classifier, model_version, expected_sha256)
        metrics = await asyncio.to_thread(model.evaluate, samples)

    return envelope(request.request_id, metrics, model_version, timer.elapsed_ms, confidence=metrics.get("accuracy"))


@router.post("/classify", response_model=MlResponse)
async def classify(request: MlRequest) -> MlResponse:
    """Threat classification against a specific, checksum-verified model.

    The gateway is the one that knows which version is currently PRODUCTION
    (07_Model_Registry_and_Deployment.md) — this endpoint has no notion of
    "the" model, only "a" model it's told to use. Called without a
    `model_version` (no production model promoted yet), it answers with the
    same structured error the stub used to: the gateway's documented behaviour
    on this error is to fall through to the deterministic Detection Rules path
    and mark the result `ml_unavailable` (02_Data_Pipeline §6).
    """
    text = str(request.payload.get("text") or "").strip()
    if not text:
        raise MlError("invalid_payload", "payload.text must be a non-empty string", retryable=False)

    model_version = str(request.payload.get("model_version") or "")
    expected_sha256 = str(request.payload.get("expected_sha256") or "")
    if not model_version or not expected_sha256:
        raise MlError(
            "model_not_available",
            "no threat classification model has been trained and promoted yet",
            status_code=503,
            retryable=False,
        )

    with Timer() as timer:
        model = _load_classifier(model_version, expected_sha256)
        label, probabilities = model.predict(text)

    return envelope(
        request.request_id,
        {"category": label, "probabilities": probabilities},
        model_version,
        timer.elapsed_ms,
        confidence=probabilities[label],
    )
