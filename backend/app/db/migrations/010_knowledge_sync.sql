-- ==========================================================
-- 010 — Knowledge Base sync tracking (04_AI_and_ML/03_Knowledge_Base.md)
--
-- Tracks whether a fact_item has been pushed to the ML Service's real
-- /v1/kb/upsert endpoint (Qdrant collection `fact_knowledge_base`). Not the
-- spec's full UPLOADED/VALIDATED/PARSED/INDEXED/FAILED pipeline — that
-- machine describes a raw-document upload/parse/chunk pipeline this stage
-- deliberately does not build (parsing/chunking ownership is an open
-- question in the spec itself). This is a plain sync status for the
-- fact_item model that already exists and is already embeddable.
-- ==========================================================

ALTER TABLE fact_items ADD COLUMN IF NOT EXISTS synced_at TIMESTAMPTZ;
ALTER TABLE fact_items ADD COLUMN IF NOT EXISTS sync_error TEXT;
