"""Knowledge-base ingestion: embed fact items and store them in Qdrant.

Ingestion is *orchestrated* by the gateway — it owns `fact_items` in PostgreSQL
and decides what gets ingested — but the embedding and the vector write happen
here, because the gateway is not allowed to compute vectors
(02_Architecture/04_ML_Service.md §5).

Upsert, not insert: the Qdrant point id is `fact_items.id`, so re-ingesting an
edited fact replaces its vector instead of leaving a stale twin behind that can
still be retrieved.

Embedding a knowledge document never changes model parameters
(02_Data_Pipeline §5) — this endpoint is knowledge, not training.
"""

import logging
from typing import Any

from fastapi import APIRouter, Depends

from app.api.deps import Timer, envelope, get_repository
from app.core.errors import MlError
from app.core.security import verify_internal_key
from app.models.registry import registry
from app.rag.qdrant_repo import QdrantRepository
from app.schemas.contract import MlRequest, MlResponse

logger = logging.getLogger("app.api.knowledge")

router = APIRouter(dependencies=[Depends(verify_internal_key)])

REQUIRED_FIELDS = ("fact_item_id", "category", "title", "claim_text")


def _embedding_text(item: dict[str, Any]) -> str:
    """What actually gets embedded.

    Title plus claim, not the full explanation: the query side is a user's
    version of the *claim*, so embedding the debunking text alongside it would
    pull the vector away from the thing being matched.
    """
    return f"{item.get('title', '')}. {item.get('claim_text', '')}".strip()


@router.post("/kb/upsert", response_model=MlResponse)
async def upsert_knowledge(
    request: MlRequest,
    repository: QdrantRepository = Depends(get_repository),
) -> MlResponse:
    items = request.payload.get("items")
    if not isinstance(items, list) or not items:
        raise MlError("invalid_payload", "payload.items must be a non-empty list", retryable=False)

    valid: list[dict[str, Any]] = []
    rejected: list[dict[str, str]] = []
    for item in items:
        missing = [field for field in REQUIRED_FIELDS if not item.get(field)]
        if missing:
            rejected.append({"fact_item_id": str(item.get("fact_item_id", "")), "missing": ",".join(missing)})
            continue
        valid.append(item)

    if not valid:
        raise MlError("invalid_payload", "no ingestible items in request", retryable=False)

    embedder = registry.embedder()
    with Timer() as timer:
        vectors = await embedder.embed([_embedding_text(item) for item in valid])
        try:
            embedder.ensure_dimension(vectors)
        except ValueError as exc:
            raise MlError("embedding_dimension_mismatch", str(exc), retryable=False) from exc

        points = [
            repository.build_point(
                fact_item_id=str(item["fact_item_id"]),
                vector=vector,
                payload={
                    "fact_item_id": str(item["fact_item_id"]),
                    "category": item["category"],
                    "title": item["title"],
                    "claim_text": item["claim_text"],
                    "fact_explanation": item.get("fact_explanation", ""),
                    "verdict": item.get("verdict", "UNVERIFIED"),
                    "source_name": item.get("source_name", ""),
                    "source_url": item.get("source_url", ""),
                    "is_active": bool(item.get("is_active", True)),
                    "updated_at": item.get("updated_at"),
                },
            )
            for item, vector in zip(valid, vectors)
        ]

        try:
            upserted = await repository.upsert_facts(points)
        except Exception as exc:  # noqa: BLE001
            logger.warning("qdrant upsert failed", extra={"error": type(exc).__name__})
            raise MlError(
                "vector_store_unavailable", type(exc).__name__, status_code=503, retryable=True
            ) from exc

    logger.info("knowledge upserted", extra={"count": upserted, "rejected": len(rejected)})
    return envelope(
        request.request_id,
        {"upserted": upserted, "rejected": rejected, "dim": embedder.dim},
        embedder.model_version,
        timer.elapsed_ms,
    )
