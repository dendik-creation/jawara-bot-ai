"""Qdrant retrieval and knowledge upsert.

Qdrant sits behind ML Service by design (02_Architecture/04_ML_Service.md §5):
embedding and similarity comparison are inference-adjacent work, so the gateway
never computes or compares a vector itself.

The query shape is fixed by 03_Database/02_VectorDB_Specifications.md §3 —
cosine similarity, `top_k=3`, `score_threshold=0.80`, filtered by `category` and
`is_active=true`. Both filter fields carry payload indexes; without them Qdrant
falls back to a full payload scan on every query, which is exactly what makes
`on_disk_payload=true` expensive.
"""

import logging
from typing import Any

from qdrant_client import AsyncQdrantClient
from qdrant_client.http import models

from app.core.config import Settings, get_settings

logger = logging.getLogger("app.rag.qdrant")


class QdrantRepository:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._client = AsyncQdrantClient(
            host=self._settings.qdrant_host,
            port=self._settings.qdrant_port,
            timeout=self._settings.qdrant_timeout_seconds,
        )

    @property
    def collection(self) -> str:
        return self._settings.qdrant_collection

    async def close(self) -> None:
        await self._client.close()

    async def health(self) -> dict[str, Any]:
        """Collection reachability + vector dimension, for the readiness probe."""
        info = await self._client.get_collection(self.collection)
        vectors = info.config.params.vectors
        return {
            "collection": self.collection,
            "vector_size": vectors.size,
            "distance": vectors.distance.value,
            "points_count": info.points_count,
        }

    async def search(
        self,
        vector: list[float],
        category: str | None = None,
        top_k: int | None = None,
        score_threshold: float | None = None,
    ) -> list[dict[str, Any]]:
        """Filtered similarity search. Returns payloads with their scores.

        An empty list means "nothing at or above the threshold" — the caller must
        report that as unverified rather than reaching for the nearest weak
        match, which is how a RAG pipeline starts inventing confident wrong
        answers.
        """
        conditions: list[models.FieldCondition] = [
            models.FieldCondition(key="is_active", match=models.MatchValue(value=True))
        ]
        if category:
            conditions.append(
                models.FieldCondition(key="category", match=models.MatchValue(value=category))
            )

        hits = await self._client.search(
            collection_name=self.collection,
            query_vector=vector,
            query_filter=models.Filter(must=conditions),
            limit=top_k or self._settings.rag_top_k,
            score_threshold=(
                self._settings.rag_score_threshold if score_threshold is None else score_threshold
            ),
            with_payload=True,
        )

        return [{**(hit.payload or {}), "score": hit.score} for hit in hits]

    async def upsert_facts(self, points: list[models.PointStruct]) -> int:
        await self._client.upsert(collection_name=self.collection, points=points, wait=True)
        return len(points)

    @staticmethod
    def build_point(fact_item_id: str, vector: list[float], payload: dict[str, Any]) -> models.PointStruct:
        """One knowledge point.

        The Qdrant point id *is* `fact_items.id`, so re-ingesting a fact updates
        its vector in place instead of leaving a stale duplicate behind — and the
        1:1 join back to PostgreSQL stays trivially derivable.
        """
        return models.PointStruct(id=fact_item_id, vector=vector, payload=payload)
