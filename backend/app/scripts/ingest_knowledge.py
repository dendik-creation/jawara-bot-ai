"""Embed `fact_items` into Qdrant ([[Build Text Verification Pipeline]]).

Usage:

    python -m app.scripts.ingest_knowledge            # all active fact items
    python -m app.scripts.ingest_knowledge --all      # including inactive ones
    python -m app.scripts.ingest_knowledge --batch 50

The gateway orchestrates ingestion — it owns `fact_items` and decides what is
ingested — while the embedding and the Qdrant write happen inside the ML Service
(02_Architecture/04_ML_Service.md §5). This script is a thin CLI wrapper around
`app.services.knowledge.sync_fact_items`, the same function the Knowledge Base
operator screen's "Sync"/"Sync All" buttons call (04_AI_and_ML/03_Knowledge_Base.md)
— one implementation of "read PostgreSQL, POST to `/v1/kb/upsert`," not two.

Uploading knowledge does not retrain anything (02_Data_Pipeline §5). Inactive
items are shipped too when `--all` is given, because the payload carries
`is_active` and the retrieval filter — not the absence of the point — is what
keeps a retired fact out of results. That keeps re-activating a fact a metadata
change rather than a re-embed.
"""

import argparse
import asyncio
import logging

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.services.knowledge import sync_fact_items

logger = logging.getLogger("app.scripts.ingest_knowledge")


def main() -> None:
    parser = argparse.ArgumentParser(description="Embed fact_items into the Qdrant knowledge base")
    parser.add_argument("--all", action="store_true", help="include inactive fact items")
    parser.add_argument("--batch", type=int, default=25, help="items per ML Service request")
    args = parser.parse_args()

    settings = get_settings()
    configure_logging(settings.log_level)
    result = asyncio.run(sync_fact_items(include_inactive=args.all, batch_size=args.batch, settings=settings))
    logger.info("ingestion finished", extra=result)


if __name__ == "__main__":
    main()
