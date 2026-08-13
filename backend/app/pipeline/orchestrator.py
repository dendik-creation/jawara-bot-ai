"""End-to-end orchestration of one WhatsApp message.

Stages 4–12 of 02_Architecture/02_Data_Pipeline.md, in order:

    normalise → extract indicators → classify (rules, ML when available)
    → verify (RAG or URL reputation) → risk assessment → policy
    → generate reply → dispatch via WAHA → audit row

The worker owns the *ordering*; each stage owns its logic. Every stage is
allowed to degrade: a missing ML Service falls back to rules-only, a missing
threat-intel key produces `UNKNOWN` instead of an exception, an undeliverable
reply still leaves an audit row. The one thing the pipeline never does is claim
more certainty than it has — `UNKNOWN` never renders as "safe".
"""

import base64
import binascii
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import redis.asyncio as aioredis

from app.clients.ml_client import MlClient, MlServiceError
from app.clients.waha_client import WahaClient
from app.core.config import Settings, get_settings
from app.core.hashing import hash_user_identifier
from app.pipeline import group_policy, intent_router
from app.pipeline.categories import Category, InputType, RiskLevel, Verdict, worst_risk
from app.pipeline.normalizer import normalize_text
from app.pipeline.url_extractor import extract_urls
from app.pipeline.url_safety import UrlScanResult, scan_urls
from app.schemas.queue import MessageJob
from app.services.message_log import MessageLogEntry, chat_type_for, record_message
from app.services.model_versions import get_production_model

logger = logging.getLogger("app.pipeline.orchestrator")

# Events that carry a user message. `session.status` and friends arrive on the
# same webhook and must not be run through detection.
MESSAGE_EVENTS = frozenset({"message", "message.any"})

# Answer to a bare mention. Fixed text, not LLM-generated: there is nothing to
# analyse, and a generated reply to an empty prompt is where a chatbot starts
# making things up.
EMPTY_MENTION_REPLY = (
    "Halo! 👋 Saya JAWARA, asisten pemeriksa hoaks dan penipuan.\n\n"
    "Silakan sebut saya sambil menyertakan pesannya, misalnya:\n"
    "• Balas (reply) pesan yang mencurigakan, lalu sebut saya\n"
    "• Atau tulis: @JAWARA tolong cek kabar ini ...\n\n"
    "Saya bisa memeriksa klaim kesehatan dan link mencurigakan."
)

# A knowledge-base verdict is a statement about the claim, so it maps directly
# onto risk. UNVERIFIED is MEDIUM, never LOW: "no one has checked this" is not
# reassurance.
VERDICT_RISK: dict[str, RiskLevel] = {
    Verdict.HOAX.value: RiskLevel.HIGH,
    Verdict.MISLEADING.value: RiskLevel.MEDIUM,
    Verdict.UNVERIFIED.value: RiskLevel.MEDIUM,
    Verdict.FACT.value: RiskLevel.LOW,
}

# The ML classifier's own view of risk per predicted category. Additive only —
# folded into `risk_signals` alongside the rules engine's own signal, and
# `worst_risk()` takes the max, so this can only ever push risk up, never
# suppress a HIGH the rules engine already found. `NOT_A_THREAT` (a real
# negative class the DB-locked `Category` enum can't represent — see
# `app.services.datasets`) contributes no elevated risk.
CATEGORY_RISK: dict[str, RiskLevel] = {
    Category.HEALTH_HOAX.value: RiskLevel.MEDIUM,
    Category.FINANCIAL_FRAUD.value: RiskLevel.HIGH,
    Category.GENERAL_NEWS.value: RiskLevel.LOW,
    Category.PHISHING_LINK.value: RiskLevel.HIGH,
    Category.FILE_APK.value: RiskLevel.HIGH,
    "NOT_A_THREAT": RiskLevel.LOW,
}

# In-process cache for "which model_version is PRODUCTION" — promotion is a
# rare, explicit human action (07_Model_Registry_and_Deployment §3-4), so a
# DB round-trip per message is pure waste. Short TTL, not a long one: a
# rollback/promotion should take effect for new messages within seconds, not
# ride out a full worker restart.
_PRODUCTION_MODEL_CACHE_TTL_SECONDS = 30.0
_production_model_cache: dict[str, Any] = {"value": None, "checked_at": 0.0}


async def _cached_production_model(settings: Settings) -> dict[str, str] | None:
    now = time.monotonic()
    if now - _production_model_cache["checked_at"] < _PRODUCTION_MODEL_CACHE_TTL_SECONDS:
        return _production_model_cache["value"]
    value = await get_production_model(settings)
    _production_model_cache["value"] = value
    _production_model_cache["checked_at"] = now
    return value


@dataclass
class PipelineOutcome:
    """What happened to one message, in the shape the log and the caller want."""

    status: str = "processed"
    intent: str = "UNKNOWN"
    intent_confidence: float = 0.0
    engine: str = intent_router.ENGINE_NONE
    risk: str = RiskLevel.UNKNOWN.value
    url_count: int = 0
    match_count: int = 0
    similarity_score: float | None = None
    matched_fact_id: str | None = None
    # How the retrieval query was produced ("llm", "heuristic", "passthrough")
    # and whether ml-service re-ranked what came back. Both are diagnostics for
    # "why did retrieval match this" — logged, not stored on the audit row,
    # whose columns are fixed by 03_Database/01_PostgreSQL_Schema.md.
    claim_method: str | None = None
    reranked: bool = False
    ml_category: str | None = None
    ml_confidence: float | None = None
    # Diagnostics for "did this message start as a picture" — logged, not
    # persisted (17_Database: no new column unless one earns its keep;
    # `input_type=IMAGE_OCR` on the audit row already records the modality).
    ocr_used: bool = False
    ocr_confidence: float | None = None
    response_dispatched: bool = False
    response_latency_ms: int | None = None
    logged: bool = False
    degradations: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "intent": self.intent,
            "intent_confidence": round(self.intent_confidence, 3),
            "engine": self.engine,
            "risk": self.risk,
            "url_count": self.url_count,
            "match_count": self.match_count,
            "similarity_score": self.similarity_score,
            "claim_method": self.claim_method,
            "reranked": self.reranked,
            "ml_category": self.ml_category,
            "ml_confidence": self.ml_confidence,
            "ocr_used": self.ocr_used,
            "ocr_confidence": self.ocr_confidence,
            "response_dispatched": self.response_dispatched,
            "response_latency_ms": self.response_latency_ms,
            "logged": self.logged,
            "degradations": self.degradations,
        }


def _payload_of(message: MessageJob) -> dict[str, Any]:
    payload = message.event.get("payload")
    return payload if isinstance(payload, dict) else {}


def _attachment_names(payload: dict[str, Any]) -> list[str]:
    """Filenames WAHA reports for an attachment, across engine payload shapes."""
    names: list[str] = []
    for key in ("filename", "fileName"):
        value = payload.get(key)
        if isinstance(value, str):
            names.append(value)
    media = payload.get("media")
    if isinstance(media, dict):
        for key in ("filename", "fileName"):
            value = media.get(key)
            if isinstance(value, str):
                names.append(value)
    return names


_IMAGE_MIME_PREFIX = "image/"


@dataclass(frozen=True)
class ImageAttachment:
    """One image WAHA attached to a message, however that engine reports it."""

    mimetype: str
    filename: str
    url: str | None = None
    data: bytes | None = None


def _image_attachment(payload: dict[str, Any]) -> ImageAttachment | None:
    """The image attachment on this message, if any — across WAHA engine shapes.

    WAHA reports media two ways depending on its own `downloadMedia` webhook
    setting: a `media.url` to fetch, or the bytes already inline as
    `media.data` (base64). Neither is assumed; either is accepted. `type ==
    "image"` or an `image/*` mimetype both count as "this is a picture" —
    WEBJS and NOWEB spell the field slightly differently.

    Returns `None` for anything that isn't a fetchable image, including a
    payload that merely *claims* to be one but carries neither a URL nor
    inline bytes — there is nothing this pipeline could OCR from that.
    """
    media = payload.get("media")
    media = media if isinstance(media, dict) else {}
    mimetype = str(media.get("mimetype") or payload.get("mimetype") or "")
    is_image = mimetype.lower().startswith(_IMAGE_MIME_PREFIX) or payload.get("type") == "image"
    if not is_image:
        return None

    filename = str(
        media.get("filename")
        or media.get("fileName")
        or payload.get("filename")
        or payload.get("fileName")
        or "image"
    )
    url = media.get("url") if isinstance(media.get("url"), str) and media.get("url") else None
    data: bytes | None = None
    raw_data = media.get("data")
    if isinstance(raw_data, str) and raw_data:
        try:
            data = base64.b64decode(raw_data, validate=False)
        except (binascii.Error, ValueError):
            data = None

    if not url and not data:
        return None
    return ImageAttachment(mimetype=mimetype or "image/jpeg", filename=filename, url=url, data=data)


def _input_type(urls_found: int, apk: bool, image_ocr: bool = False) -> InputType:
    if apk:
        return InputType.FILE_APK
    if image_ocr:
        return InputType.IMAGE_OCR
    if urls_found:
        return InputType.URL_LINK
    return InputType.TEXT


def _elapsed_ms(received_at: datetime) -> int:
    return max(0, int((datetime.now(timezone.utc) - received_at).total_seconds() * 1000))


async def process_message_job(
    message: MessageJob,
    log_context: dict[str, Any],
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Run one queued message through the whole pipeline."""
    settings = settings or get_settings()
    outcome = PipelineOutcome()
    started = time.perf_counter()

    if message.event_name not in MESSAGE_EVENTS:
        outcome.status = "ignored_non_message_event"
        return outcome.as_dict()

    payload = _payload_of(message)
    if payload.get("fromMe") is True:
        # Our own outbound reply comes back as an event; analysing it would put
        # the bot in a loop with itself.
        outcome.status = "ignored_own_message"
        return outcome.as_dict()

    chat_id = message.chat_id or payload.get("from")
    if not chat_id:
        outcome.status = "ignored_missing_chat_id"
        return outcome.as_dict()

    body = payload.get("body") or payload.get("caption") or ""
    attachments = _attachment_names(payload)
    quoted_id = group_policy.quoted_message_id(payload)
    image_attachment = _image_attachment(payload)
    if not body.strip() and not attachments and not quoted_id and not image_attachment:
        outcome.status = "ignored_empty_body"
        return outcome.as_dict()

    ml = MlClient(settings)
    request_id = message.waha_message_id or f"{message.session}:{chat_id}"

    # --- stage 3b: may the bot speak here? -------------------------------
    # Decided before any analysis, deliberately. A group message the bot was not
    # addressed in costs no ML call, and — more importantly — leaves no
    # `extracted_text` row: the system reads what it is asked to read, not
    # everything said in the room.
    bot_ids = (
        await WahaClient(settings).session_identity(message.session)
        if group_policy.is_group_chat(chat_id)
        else frozenset()
    )
    decision = group_policy.decide(
        payload,
        chat_id,
        body,
        bot_ids=bot_ids,
        require_trigger=settings.group_reply_requires_trigger,
    )
    if not decision.should_reply:
        logger.info(
            "group message not addressed to the bot, skipped",
            extra={**log_context, "reason": decision.reason},
        )
        outcome.status = "ignored_group_not_addressed"
        return outcome.as_dict()

    if decision.is_group:
        body = group_policy.strip_bot_mentions(body, bot_ids)

    # A reply carries its own new text (often empty — "@JAWARA, is this true?"
    # or just the mention) plus a pointer to the message being asked about. The
    # pointer is what must actually be checked, so it is fetched and folded in
    # before anything downstream reads `body` — a bare "@JAWARA" on a reply is
    # a complete request, not an empty one.
    if decision.quoted_message_id:
        quoted_text = await WahaClient(settings).get_message_text(
            message.session, chat_id, decision.quoted_message_id
        )
        if quoted_text:
            body = f"{quoted_text}\n\n{body}".strip() if body.strip() else quoted_text
        else:
            outcome.degradations.append("quoted_message_unavailable")

    if decision.is_group:
        if not body.strip() and not attachments:
            # "@JAWARA" and nothing else — no reply, no attachment, no quoted
            # text recovered: called, but given nothing to check. Silence would
            # read as a broken bot, so say what it needs — and say it as a
            # quote of the summons, so the group sees who asked.
            send = await WahaClient(settings).send_text(
                chat_id, EMPTY_MENTION_REPLY, session=message.session, reply_to=message.waha_message_id
            )
            outcome.status = "mention_without_content"
            outcome.response_dispatched = send.delivered
            return outcome.as_dict()

    # --- stage 3c: OCR (image input becomes text) -------------------------
    # Folding OCR text into `body` here — before normalize_text() runs — is
    # the entire feature: every stage after this line (normalisation, intent
    # routing, claim extraction with its injection guard, RAG, verification)
    # runs the exact path a typed message already takes. OCR only changes
    # which text that path receives; it never produces a verdict itself.
    if image_attachment and settings.ocr_enabled:
        max_bytes = int(settings.ocr_max_image_size_mb * 1024 * 1024)
        image_bytes = image_attachment.data
        if image_bytes is None and image_attachment.url:
            image_bytes = await WahaClient(settings).download_media(image_attachment.url)

        if not image_bytes:
            outcome.degradations.append("ocr_media_unavailable")
        elif len(image_bytes) > max_bytes:
            # Cheap, dependency-free rejection at the gateway — no reason to
            # ship an obviously oversized file to ml-service just to have it
            # reject the same thing after paying the upload cost.
            outcome.degradations.append("ocr_image_too_large")
        else:
            try:
                ocr_response = await ml.ocr(
                    request_id, image_bytes, image_attachment.filename, image_attachment.mimetype
                )
            except MlServiceError as exc:
                outcome.degradations.append(f"ocr_unavailable:{exc.error_code}")
            else:
                ocr_result = ocr_response.result
                ocr_text = str(ocr_result.get("text") or "").strip()
                ocr_success = bool(ocr_result.get("success", True))
                if settings.ocr_debug_log:
                    logger.debug("ocr result", extra={**log_context, "ocr_text": ocr_text})
                if ocr_success and ocr_text:
                    body = f"{body}\n\n{ocr_text}".strip() if body.strip() else ocr_text
                    outcome.ocr_used = True
                    outcome.ocr_confidence = ocr_response.confidence
                    if ocr_response.confidence is not None and ocr_response.confidence < settings.ocr_min_confidence:
                        # Text still flows into the pipeline as real evidence —
                        # never discarded merely for scoring low — but the
                        # audit trail records that this reading was shaky
                        # (13_Low_Confidence_OCR).
                        outcome.degradations.append("ocr_low_confidence")
                else:
                    # No usable text: never fabricate a claim from a picture
                    # that had nothing readable in it. `body` is left exactly
                    # as it was (any caption text still goes through
                    # normally); if there was none either, the message falls
                    # through to the same "nothing to check" path plain text
                    # already takes, ending in UNKNOWN/insufficient-evidence,
                    # never HOAX (12_Empty_Poor_OCR_Handling).
                    outcome.degradations.append("ocr_empty_result")

    # --- stage 4: preprocessing ------------------------------------------
    normalized = normalize_text(body)
    urls = extract_urls(body)
    outcome.url_count = len(urls)
    has_apk = any(name.lower().endswith(".apk") for name in attachments)

    # --- stage 5a: deterministic detection rules --------------------------
    intent = intent_router.classify(
        normalized.text,
        urls=urls,
        attachment_names=attachments,
    )
    outcome.intent = intent.category.value if intent.category else "UNKNOWN"
    outcome.intent_confidence = intent.confidence
    outcome.engine = intent.engine

    redis = aioredis.from_url(settings.redis_url, socket_connect_timeout=2, decode_responses=True)

    matches: list[dict[str, Any]] = []
    url_scan: UrlScanResult | None = None
    risk_signals: list[RiskLevel] = []

    try:
        # --- stage 5c: ML classification (additive, independent of the
        # rules engine that fired above) -----------------------------------
        # Inert until an operator explicitly promotes a model
        # (07_Model_Registry_and_Deployment §3-4) — `production_model` is
        # `None` for every message until that happens, so this is a no-op by
        # default rather than a behaviour change on deploy.
        production_model = await _cached_production_model(settings)
        if production_model and normalized.text.strip():
            try:
                ml_classification = await ml.classify(
                    request_id,
                    normalized.text,
                    production_model["model_version"],
                    production_model["artifact_sha256"],
                )
                predicted_category = str(ml_classification.result.get("category") or "")
                outcome.ml_category = predicted_category or None
                outcome.ml_confidence = ml_classification.confidence
                if predicted_category in CATEGORY_RISK:
                    risk_signals.append(CATEGORY_RISK[predicted_category])
            except MlServiceError as exc:
                outcome.degradations.append(f"ml_classify_unavailable:{exc.error_code}")

        # --- stage 5b/6: verification ------------------------------------
        if intent.engine == intent_router.ENGINE_URL_SAFETY and urls:
            url_scan = await scan_urls(urls, redis=redis, settings=settings)
            risk_signals.append(url_scan.risk)
            if url_scan.degraded:
                outcome.degradations.append("url_intel_unavailable")

        elif intent.engine == intent_router.ENGINE_TEXT_VERIFICATION:
            # Retrieve on the claim, not on the forward. A chain letter's
            # greeting, emoji and "TOLONG SEBARKAN!!!" are embedded too, and
            # they pull the vector away from the curated claim the knowledge
            # base actually stores. Extraction degrades rather than fails —
            # ml-service falls back to a deterministic heuristic internally —
            # so a failure here costs match quality, never the answer.
            rag_query_text = normalized.text
            if settings.rag_claim_extraction_enabled and normalized.text.strip():
                try:
                    extraction = await ml.extract_claim(
                        request_id,
                        normalized.text,
                        category=intent.category.value if intent.category else None,
                    )
                    extracted = str(extraction.result.get("claim") or "").strip()
                    if extracted:
                        rag_query_text = extracted
                        outcome.claim_method = str(extraction.result.get("method") or "")
                except MlServiceError as exc:
                    outcome.degradations.append(f"claim_extraction_unavailable:{exc.error_code}")

            try:
                response = await ml.rag_query(
                    request_id,
                    query=rag_query_text,
                    category=intent.category.value if intent.category else None,
                )
                matches = list(response.result.get("matches") or [])
                outcome.reranked = bool(response.result.get("reranked"))
            except MlServiceError as exc:
                outcome.degradations.append(f"ml_unavailable:{exc.error_code}")
            if matches:
                top = matches[0]
                outcome.match_count = len(matches)
                outcome.similarity_score = float(top.get("score", 0.0))
                outcome.matched_fact_id = top.get("fact_item_id")
                risk_signals.append(VERDICT_RISK.get(str(top.get("verdict")), RiskLevel.MEDIUM))
            else:
                # Nothing above the similarity threshold: explicitly unverified,
                # never "closest weak match wins".
                risk_signals.append(RiskLevel.MEDIUM)
                outcome.degradations.append("knowledge_unverified")

        elif intent.engine == intent_router.ENGINE_APK_WARNING:
            # MVP recognises the attachment and warns. Static analysis of the APK
            # is Optional/Future (06_Optional_APK_Inspector).
            risk_signals.append(RiskLevel.HIGH if has_apk else RiskLevel.MEDIUM)

        elif intent.engine == intent_router.ENGINE_UNSUPPORTED:
            outcome.degradations.append(f"engine_unsupported:{outcome.intent}")

        # A dangerous link inside an otherwise text-shaped message still counts.
        if url_scan is None and urls and intent.engine != intent_router.ENGINE_URL_SAFETY:
            url_scan = await scan_urls(urls, redis=redis, settings=settings)
            risk_signals.append(url_scan.risk)

        # --- stage 7: risk assessment ------------------------------------
        risk = worst_risk(*risk_signals) if risk_signals else RiskLevel.UNKNOWN
        outcome.risk = risk.value

        # --- stage 8/9: policy + action ----------------------------------
        # MVP policy: the system is consent-based — the user asked, so the user
        # gets an answer. Graded ALLOW/WARN/BLOCK/ESCALATE actions arrive with
        # the Security Policy engine (02_Security_Policies, Planned).
        reply_text = ""
        try:
            generated = await ml.generate(
                request_id,
                user_text=normalized.raw,
                category=intent.category.value if intent.category else None,
                risk_level=risk.value,
                context=matches,
                url_verdicts=[item.as_dict() for item in (url_scan.urls if url_scan else ())],
            )
            reply_text = str(generated.result.get("message") or "")
            if generated.result.get("fallback_used"):
                outcome.degradations.append(
                    f"llm_fallback:{generated.result.get('fallback_reason', 'unknown')}"
                )
        except MlServiceError as exc:
            outcome.degradations.append(f"generation_unavailable:{exc.error_code}")

        # --- stage 11: dispatch ------------------------------------------
        if reply_text:
            # Quote the message that summoned the bot, but only in groups: in a
            # one-to-one chat there is nothing to disambiguate, and the quote
            # would just add clutter.
            send = await WahaClient(settings).send_text(
                chat_id,
                reply_text,
                session=message.session,
                reply_to=message.waha_message_id if decision.is_group else None,
            )
            outcome.response_dispatched = send.delivered
            if not send.delivered:
                outcome.degradations.append(f"dispatch_failed:{send.error}")

        outcome.response_latency_ms = _elapsed_ms(message.received_at)
        if outcome.response_latency_ms > settings.end_to_end_target_ms:
            logger.warning(
                "end-to-end latency over target",
                extra={
                    **log_context,
                    "response_latency_ms": outcome.response_latency_ms,
                    "target_ms": settings.end_to_end_target_ms,
                },
            )

        # --- stage 10: audit row -----------------------------------------
        outcome.logged = await _write_audit_row(
            message=message,
            chat_id=chat_id,
            normalized_raw=normalized.raw,
            intent_category=intent.category,
            risk=risk,
            outcome=outcome,
            has_apk=has_apk,
            settings=settings,
        )
    finally:
        await redis.aclose()

    logger.info(
        "pipeline complete",
        extra={
            **log_context,
            **outcome.as_dict(),
            "worker_ms": int((time.perf_counter() - started) * 1000),
        },
    )
    return outcome.as_dict()


async def _write_audit_row(
    message: MessageJob,
    chat_id: str,
    normalized_raw: str,
    intent_category: Category | None,
    risk: RiskLevel,
    outcome: PipelineOutcome,
    has_apk: bool,
    settings: Settings,
) -> bool:
    """Persist the audit row. A logging failure must not lose the reply already sent."""
    if not message.waha_message_id:
        outcome.degradations.append("audit_skipped_no_message_id")
        return False

    entry = MessageLogEntry(
        waha_message_id=message.waha_message_id,
        waha_session_id=message.session,
        user_hash=hash_user_identifier(chat_id, settings),
        chat_type=chat_type_for(chat_id),
        input_type=_input_type(outcome.url_count, has_apk, outcome.ocr_used),
        extracted_text=normalized_raw,
        detected_intent=intent_category,
        risk_score=risk,
        matched_fact_id=outcome.matched_fact_id,
        similarity_score=outcome.similarity_score,
        response_latency_ms=outcome.response_latency_ms,
    )

    try:
        return await record_message(entry, settings)
    except Exception:  # noqa: BLE001
        logger.error(
            "audit row write failed",
            extra={"waha_message_id": message.waha_message_id},
            exc_info=True,
        )
        outcome.degradations.append("audit_write_failed")
        return False
