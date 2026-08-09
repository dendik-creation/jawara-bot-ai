"""Embed `fact_items` into Qdrant ([[Build Text Verification Pipeline]]).

Usage:

    python -m app.scripts.ingest_knowledge            # all active fact items
    python -m app.scripts.ingest_knowledge --all      # including inactive ones
    python -m app.scripts.ingest_knowledge --batch 50

The gateway orchestrates ingestion — it owns `fact_items` and decides what is
ingested — while the embedding and the Qdrant write happen inside the ML Service
(02_Architecture/04_ML_Service.md §5). This script therefore reads PostgreSQL and
POSTs to `/v1/kb/upsert`; it never loads an embedding model and never opens a
Qdrant connection.

Uploading knowledge does not retrain anything (02_Data_Pipeline §5). Inactive
items are shipped too when `--all` is given, because the payload carries
`is_active` and the retrieval filter — not the absence of the point — is what
keeps a retired fact out of results. That keeps re-activating a fact a metadata
change rather than a re-embed.
"""

import argparse
import asyncio
import logging
from typing import Any

import asyncpg

from app.clients.ml_client import MlClient, MlServiceError
from app.core.config import get_settings
from app.core.logging import configure_logging

logger = logging.getLogger("app.scripts.ingest_knowledge")

SELECT_FACTS = """
SELECT
    fi.id::text        AS fact_item_id,
    fi.category::text  AS category,
    fi.title,
    fi.claim_summary   AS claim_text,
    fi.fact_explanation,
    fi.verdict::text   AS verdict,
    fi.source_url,
    fi.is_active,
    fi.updated_at,
    coalesce(fs.name, '') AS source_name
FROM fact_items fi
LEFT JOIN fact_sources fs ON fs.id = fi.source_id
WHERE ($1::boolean OR fi.is_active = TRUE)
ORDER BY fi.updated_at
"""


async def fetch_facts(dsn: str, include_inactive: bool) -> list[dict[str, Any]]:
    conn = await asyncpg.connect(dsn, timeout=10)
    try:
        rows = await conn.fetch(SELECT_FACTS, include_inactive)
    finally:
        await conn.close()

    return [
        {
            "fact_item_id": row["fact_item_id"],
            "category": row["category"],
            "title": row["title"],
            "claim_text": row["claim_text"],
            "fact_explanation": row["fact_explanation"],
            "verdict": row["verdict"],
            "source_name": row["source_name"],
            "source_url": row["source_url"],
            "is_active": row["is_active"],
            "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
        }
        for row in rows
    ]


async def ingest(include_inactive: bool = False, batch_size: int = 25) -> dict[str, int]:
    settings = get_settings()
    facts = await fetch_facts(settings.database_url, include_inactive)
    if not facts:
        logger.warning("no fact_items to ingest — knowledge base is empty")
        return {"total": 0, "upserted": 0, "failed": 0}

    client = MlClient(settings)
    upserted = 0
    failed = 0

    for start in range(0, len(facts), batch_size):
        batch = facts[start : start + batch_size]
        request_id = f"kb-ingest-{start // batch_size}"
        try:
            response = await client.upsert_knowledge(request_id, batch)
        except MlServiceError as exc:
            failed += len(batch)
            logger.error(
                "batch failed",
                extra={"offset": start, "size": len(batch), "error": exc.error_code},
            )
            continue

        count = int(response.result.get("upserted", 0))
        upserted += count
        logger.info(
            "batch ingested",
            extra={
                "offset": start,
                "upserted": count,
                "rejected": response.result.get("rejected"),
                "model_version": response.model_version,
            },
        )

    return {"total": len(facts), "upserted": upserted, "failed": failed}


def main() -> None:
    parser = argparse.ArgumentParser(description="Embed fact_items into the Qdrant knowledge base")
    parser.add_argument("--all", action="store_true", help="include inactive fact items")
    parser.add_argument("--batch", type=int, default=25, help="items per ML Service request")
    args = parser.parse_args()

    settings = get_settings()
    configure_logging(settings.log_level)
    result = asyncio.run(ingest(include_inactive=args.all, batch_size=args.batch))
    logger.info("ingestion finished", extra=result)


if __name__ == "__main__":
    main()
