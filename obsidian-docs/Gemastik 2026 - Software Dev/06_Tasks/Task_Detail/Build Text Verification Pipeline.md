# Build Text Verification Pipeline

## Status

ToDo

## Priority

Critical

## Sprint

Sprint 1

## Deadline

2026-08-09

## Description

For `HEALTH_HOAX`/`GENERAL_NEWS` intents: generate an embedding for the user's claim (`text-embedding-3-small`, 1536-dim, or `IndoBERT`, 768-dim), and run a filtered cosine-similarity search against `fact_knowledge_base` (top-K=3, `score_threshold=0.80`, filtered by `category` + `is_active=true`).

## Background

Primary verification path for the two text-based threat categories in Sprint 1 scope — this is the RAG integration the milestone's "text messages can be verified" criterion depends on.

## Deliverables

- Embedding client wrapper (provider-agnostic interface)
- KB ingestion script embedding existing `fact_items` rows into Qdrant
- Retrieval function matching the documented query shape
- Below-threshold handling: mark result as Unverified/Low Confidence rather than forcing a match

## Dependencies

- [[Create Qdrant Collection]]
- [[Design PostgreSQL Schema]]
- [[Build Intent Router]]

## Acceptance Criteria

- Returns top-3 matches at or above 0.80 cosine similarity
- Below-threshold query returns an explicit "unverified" signal, not the nearest weak match
- Vector dimension matches the Qdrant collection config exactly
- Category/active filters applied correctly, verified against a seeded test collection

## Related Documentation

- [[02_VectorDB_Specifications]]
- [[02_Data_Pipeline]]

## Notes

Qdrant-down fallback (Postgres full-text search) is a resilience feature, not required for the Sprint 1 milestone — defer unless time allows.
