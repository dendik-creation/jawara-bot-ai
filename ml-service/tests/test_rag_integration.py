"""Retrieval against a live Qdrant, on a throwaway collection.

Skipped when Qdrant is unreachable. The point is to verify the things a fake
repository cannot: that the payload filters really exclude, that the score
threshold really cuts, and that the point id really is `fact_items.id`.

A dedicated collection is created and dropped per run — the real
`fact_knowledge_base` is never written to by a test.
"""

import uuid

import pytest
from qdrant_client import AsyncQdrantClient
from qdrant_client.http import models

from app.core.config import Settings
from app.embeddings.hashing import HashingEmbedder
from app.rag.qdrant_repo import QdrantRepository

pytestmark = pytest.mark.integration

CLAIM = "air rebusan daun kitolod menyembuhkan katarak tanpa operasi"
RESTATED = "air rebusan daun kitolod menyembuhkan katarak tanpa operasi dokter"
UNRELATED = "jadwal kereta api jakarta bandung besok pagi"


def payload(category: str, is_active: bool, title: str) -> dict:
    return {
        "fact_item_id": str(uuid.uuid4()),
        "category": category,
        "title": title,
        "claim_text": CLAIM,
        "fact_explanation": "Kemenkes menegaskan hal ini berbahaya.",
        "verdict": "HOAX",
        "source_name": "Kemenkes",
        "source_url": "https://turnbackhoax.id/x",
        "is_active": is_active,
    }


@pytest.fixture
async def seeded(live_qdrant):
    """A temporary collection holding three points: active, inactive, other-category."""
    settings = Settings(
        qdrant_host=live_qdrant.qdrant_host,
        qdrant_port=live_qdrant.qdrant_port,
        qdrant_collection=f"test_kb_{uuid.uuid4().hex[:8]}",
        embedding_dim=1536,
    )
    admin = AsyncQdrantClient(host=settings.qdrant_host, port=settings.qdrant_port, timeout=10)
    await admin.create_collection(
        collection_name=settings.qdrant_collection,
        vectors_config=models.VectorParams(size=settings.embedding_dim, distance=models.Distance.COSINE),
    )
    for field, schema in (
        ("category", models.PayloadSchemaType.KEYWORD),
        ("is_active", models.PayloadSchemaType.BOOL),
    ):
        await admin.create_payload_index(
            collection_name=settings.qdrant_collection, field_name=field, field_schema=schema
        )

    embedder = HashingEmbedder(settings.embedding_dim)
    repository = QdrantRepository(settings)
    items = [
        payload("HEALTH_HOAX", True, "aktif health"),
        payload("HEALTH_HOAX", False, "nonaktif health"),
        payload("GENERAL_NEWS", True, "aktif news"),
    ]
    vectors = await embedder.embed([CLAIM] * len(items))
    await repository.upsert_facts(
        [
            repository.build_point(item["fact_item_id"], vector, item)
            for item, vector in zip(items, vectors)
        ]
    )

    yield repository, embedder, items

    await repository.close()
    await admin.delete_collection(settings.qdrant_collection)
    await admin.close()


async def test_active_category_filter_excludes_everything_else(seeded):
    repository, embedder, items = seeded
    vector = (await embedder.embed([RESTATED]))[0]

    hits = await repository.search(vector, category="HEALTH_HOAX", score_threshold=0.5)

    titles = {hit["title"] for hit in hits}
    assert titles == {"aktif health"}  # inactive and other-category are filtered out


async def test_score_threshold_cuts_unrelated_text(seeded):
    repository, embedder, _ = seeded
    vector = (await embedder.embed([UNRELATED]))[0]

    assert await repository.search(vector, category="HEALTH_HOAX", score_threshold=0.80) == []


async def test_top_k_is_respected(seeded):
    repository, embedder, _ = seeded
    vector = (await embedder.embed([RESTATED]))[0]

    hits = await repository.search(vector, top_k=1, score_threshold=0.5)
    assert len(hits) == 1


async def test_point_id_is_the_fact_item_id_so_reingest_updates_in_place(seeded):
    repository, embedder, items = seeded
    target = items[0]
    vector = (await embedder.embed(["teks yang sudah diperbarui"]))[0]

    updated = {**target, "title": "judul baru"}
    await repository.upsert_facts([repository.build_point(target["fact_item_id"], vector, updated)])

    hits = await repository.search(
        (await embedder.embed(["teks yang sudah diperbarui"]))[0],
        category="HEALTH_HOAX",
        score_threshold=0.5,
    )
    assert [hit["title"] for hit in hits] == ["judul baru"]


async def test_health_reports_the_live_collection(seeded):
    repository, _, _ = seeded
    health = await repository.health()

    assert health["vector_size"] == 1536
    assert health["distance"].lower() == "cosine"
