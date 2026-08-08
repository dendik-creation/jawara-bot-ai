import uuid

import pytest
from qdrant_client.http import models

from app.vector.qdrant_setup import describe_collection, ensure_collection

pytestmark = pytest.mark.integration


@pytest.fixture
def collection(qdrant_client, settings):
    ensure_collection(qdrant_client, settings)
    return settings.qdrant_collection


def test_ensure_collection_is_idempotent(qdrant_client, settings, collection):
    assert ensure_collection(qdrant_client, settings) is False


def test_config_matches_documented_values(qdrant_client, settings, collection):
    config = describe_collection(qdrant_client, settings)
    assert config["distance"] == "Cosine"
    assert config["vector_size"] == settings.embedding_dim
    assert config["hnsw_m"] == 16
    assert config["hnsw_ef_construct"] == 100
    assert config["on_disk_payload"] is True
    assert {"category", "is_active", "fact_item_id"} <= set(config["payload_indexes"])


def test_payload_filtering_matches_documented_query(qdrant_client, settings, collection):
    dim = settings.embedding_dim
    fact_item_id = str(uuid.uuid4())
    wanted, unwanted = str(uuid.uuid4()), str(uuid.uuid4())

    qdrant_client.upsert(
        collection_name=collection,
        wait=True,
        points=[
            models.PointStruct(
                id=wanted,
                vector=[1.0] + [0.0] * (dim - 1),
                payload={
                    "fact_item_id": fact_item_id,
                    "category": "HEALTH_HOAX",
                    "title": "pytest fixture",
                    "claim_text": "klaim uji",
                    "fact_explanation": "penjelasan uji",
                    "verdict": "HOAX",
                    "source_name": "pytest",
                    "source_url": "https://example.test/pytest",
                    "is_active": True,
                    "updated_at": "2026-01-01T00:00:00Z",
                },
            ),
            models.PointStruct(
                id=unwanted,
                vector=[1.0] + [0.0] * (dim - 1),
                payload={
                    "fact_item_id": str(uuid.uuid4()),
                    "category": "HEALTH_HOAX",
                    "is_active": False,
                },
            ),
        ],
    )

    try:
        hits = qdrant_client.search(
            collection_name=collection,
            query_vector=[1.0] + [0.0] * (dim - 1),
            query_filter=models.Filter(
                must=[
                    models.FieldCondition(key="category", match=models.MatchValue(value="HEALTH_HOAX")),
                    models.FieldCondition(key="is_active", match=models.MatchValue(value=True)),
                ]
            ),
            limit=3,
            score_threshold=0.80,
        )
        ids = {str(h.id) for h in hits}
        assert wanted in ids
        assert unwanted not in ids  # is_active=false filtered out
        hit = next(h for h in hits if str(h.id) == wanted)
        # 1:1 with fact_items.id in Postgres
        assert hit.payload["fact_item_id"] == fact_item_id
    finally:
        qdrant_client.delete(
            collection_name=collection,
            points_selector=models.PointIdsList(points=[wanted, unwanted]),
            wait=True,
        )
