# Create Qdrant Collection

## Status

Done

## Priority

Critical

## Sprint

Sprint 1

## Deadline

2026-08-08

## Description

Create the `fact_knowledge_base` Qdrant collection: cosine distance, 1536-dim vectors (768 for IndoBERT), HNSW index (M=16, ef_construct=100), on-disk payload storage.

## Background

Text hoax verification (RAG) cannot function without this collection existing at the exact documented configuration.

## Deliverables

- Collection creation script matching the documented config table exactly
- Payload schema matching the documented JSON (`fact_item_id`, `category`, `claim_text`, `fact_explanation`, `verdict`, `source_name`, `source_url`, `is_active`, `updated_at`)

## Dependencies

- [[Setup Docker Environment]]

## Acceptance Criteria

- Collection config matches documented values, verified via the Qdrant API
- Payload filtering on `category` and `is_active` works per the documented query example
- `fact_item_id` in payload correlates 1:1 with `fact_items.id` in Postgres

## Related Documentation

- [[02_VectorDB_Specifications]]

## Notes

Config verified live against the Qdrant REST API, not just asserted in code: `Cosine`, size `1536`, `hnsw_config.m=16`, `ef_construct=100`, `on_disk_payload=true`.

**Payload indexes added beyond the doc's config table:** `category`, `is_active`, `fact_item_id`, `verdict`. The documented hybrid-search query filters on `category` + `is_active`; without an index Qdrant falls back to a full payload scan per query, which defeats the point of on-disk payload storage. `fact_item_id` is indexed because it is the 1:1 join key back to `fact_items.id` in Postgres.

**Re-run is safe by design:** an existing collection is left untouched (recreating it would drop every embedding) — only the payload indexes are re-asserted. `ensure_collection()` returns `True` only when it actually created the collection.

Vector dimension is config (`EMBEDDING_DIM`), not a constant: 1536 for `text-embedding-3-small`, 768 for IndoBERT. Switching models means recreating the collection and re-embedding — a dimension change is not a migration Qdrant can do in place.

Run: `python -m app.vector.qdrant_setup` (prints the live config back for verification).

**Implementation:** `backend/app/vector/qdrant_setup.py`, `qdrant-client==1.8.2` pinned to match the `qdrant/qdrant:v1.8.0` server. Tests: `backend/tests/test_qdrant_collection.py` — including the documented filtered query, asserting an `is_active=false` point is excluded.
