"""Creates the `fact_knowledge_base` Qdrant collection.

Usage: `python -m app.vector.qdrant_setup`

Config is fixed by 03_Database/02_VectorDB_Specifications.md — cosine distance,
1536-dim vectors (768 for IndoBERT, via `EMBEDDING_DIM`), HNSW m=16 /
ef_construct=100, payload stored on disk.
"""

import json
import logging

from qdrant_client import QdrantClient
from qdrant_client.http import models

from app.core.config import Settings, get_settings
from app.core.logging import configure_logging

logger = logging.getLogger("app.vector.qdrant_setup")

# Fields the RAG query filters on (see the hybrid-search example in the vector DB
# doc). Without an index, Qdrant falls back to a full payload scan per query.
PAYLOAD_INDEXES: dict[str, models.PayloadSchemaType] = {
    "category": models.PayloadSchemaType.KEYWORD,
    "fact_item_id": models.PayloadSchemaType.KEYWORD,
    "verdict": models.PayloadSchemaType.KEYWORD,
    "is_active": models.PayloadSchemaType.BOOL,
}


def get_client(settings: Settings | None = None) -> QdrantClient:
    settings = settings or get_settings()
    return QdrantClient(host=settings.qdrant_host, port=settings.qdrant_port, timeout=10)


def collection_exists(client: QdrantClient, name: str) -> bool:
    return any(c.name == name for c in client.get_collections().collections)


def ensure_collection(client: QdrantClient, settings: Settings | None = None) -> bool:
    """Create the collection if missing. Returns True when it was created here.

    Safe to re-run: an existing collection is left untouched (recreating it would
    drop every embedding), only the payload indexes are re-asserted.
    """
    settings = settings or get_settings()
    name = settings.qdrant_collection

    created = False
    if collection_exists(client, name):
        logger.info("collection already exists", extra={"collection": name})
    else:
        client.create_collection(
            collection_name=name,
            vectors_config=models.VectorParams(
                size=settings.embedding_dim,
                distance=models.Distance.COSINE,
            ),
            hnsw_config=models.HnswConfigDiff(
                m=settings.qdrant_hnsw_m,
                ef_construct=settings.qdrant_hnsw_ef_construct,
            ),
            on_disk_payload=True,
        )
        created = True
        logger.info("collection created", extra={"collection": name, "dim": settings.embedding_dim})

    for field, schema in PAYLOAD_INDEXES.items():
        client.create_payload_index(collection_name=name, field_name=field, field_schema=schema)

    return created


def describe_collection(client: QdrantClient, settings: Settings | None = None) -> dict[str, object]:
    """Read back the live config, for verifying it against the documented table."""
    settings = settings or get_settings()
    info = client.get_collection(settings.qdrant_collection)
    vectors = info.config.params.vectors
    hnsw = info.config.hnsw_config
    return {
        "collection": settings.qdrant_collection,
        "distance": vectors.distance.value,
        "vector_size": vectors.size,
        "hnsw_m": hnsw.m,
        "hnsw_ef_construct": hnsw.ef_construct,
        "on_disk_payload": info.config.params.on_disk_payload,
        "payload_indexes": sorted(info.payload_schema.keys()),
        "points_count": info.points_count,
    }


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    client = get_client(settings)
    ensure_collection(client, settings)
    print(json.dumps(describe_collection(client, settings), indent=2))


if __name__ == "__main__":
    main()
