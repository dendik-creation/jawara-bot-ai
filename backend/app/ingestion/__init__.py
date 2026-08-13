"""External fact-check source adapters.

Everything in this package is *source-shaped*: feed URLs, HTML quirks,
verdict vocabularies. Nothing here touches PostgreSQL, Qdrant or Celery —
`app.services.fact_ingestion` owns the generic
fetch/parse/normalize/validate/deduplicate/persist/sync pipeline and calls
adapters through the `FactCheckSourceAdapter` interface only. Adding
CekFakta or Tirto later means one new module here plus one registry line,
with no change to the pipeline.
"""

from app.ingestion.base import (
    FactCheckSourceAdapter,
    NormalizedFactRecord,
    SourceCandidate,
    SourceFetchError,
    SourceParseError,
)
from app.ingestion.registry import available_sources, get_adapter

__all__ = [
    "FactCheckSourceAdapter",
    "NormalizedFactRecord",
    "SourceCandidate",
    "SourceFetchError",
    "SourceParseError",
    "available_sources",
    "get_adapter",
]
