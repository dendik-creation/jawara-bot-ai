# Create Qdrant Collection

## Status

ToDo

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

None
