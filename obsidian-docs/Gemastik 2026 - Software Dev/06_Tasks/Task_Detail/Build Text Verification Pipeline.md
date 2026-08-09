# Build Text Verification Pipeline

## Status

Done

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

## Implementation (2026-08-08)

Embedding dan retrieval hidup di `ml-service/` sesuai [[04_ML_Service]] §5, bukan di gateway.

- `ml-service/app/embeddings/` — antarmuka provider-agnostic; `hash-embed-v0` (offline, deterministik, default) dan `text-embedding-3-small`.
- `ml-service/app/rag/qdrant_repo.py` — pencarian terfilter `category` + `is_active`, `top_k=3`, `score_threshold=0.80`, cosine 1536-dim.
- `POST /v1/rag-query` — di bawah threshold mengembalikan `matches: []` + `unverified: true`, bukan match terdekat.
- `POST /v1/kb/upsert` + `backend/app/scripts/ingest_knowledge.py` — ingestion diorkestrasi gateway, embedding dihitung ML Service. Point id = `fact_items.id` sehingga re-ingest memperbarui di tempat.
- `backend/app/scripts/seed_facts.py` — 4 fakta demo dari contoh few-shot vault.

Terverifikasi live: skor similarity 0.8707 pada Qdrant nyata. Test integrasi membuktikan filter kategori/aktif benar-benar menyaring.

Batasan embedder default (leksikal, bukan semantik) dan cara mengaktifkan embedder produksi: [[Build_Text_Verification_Pipeline]].
