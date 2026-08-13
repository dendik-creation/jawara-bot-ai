-- ==========================================================
-- 015 — Continuous fact-check evidence ingestion (04_AI_and_ML/03_Knowledge_Base.md)
--
-- `fact_items` stays the single source of truth for knowledge: this
-- migration adds provenance/freshness columns to it rather than standing up
-- a parallel "scraped facts" table that would then need its own sync path
-- into Qdrant. An automatically ingested fact is a fact_item like any other
-- — the only difference is that `external_id`/`raw_metadata` are filled in.
--
-- Three timestamps, deliberately distinct (they answer different questions
-- and the future temporal-relevance phase needs all three):
--   published_at — when the *source* published the fact-check
--   updated_at   — when this row last changed (existing trigger)
--   ingested_at  — when we pulled it in
-- Ingestion never writes ingestion time into published_at.
--
-- Dedup is a database guarantee, not a hope: the partial unique index on
-- (source_id, external_id) is what makes a re-run idempotent even if two
-- ingestion runs overlap. `content_fingerprint` is the fallback identity for
-- sources that expose no stable id, and the change detector for sources that
-- do — same external_id + different fingerprint means the source edited the
-- article, which is an UPDATE, not a duplicate.
--
-- No unique constraint on `source_url` or `fact_sources.name`: both already
-- carry hand-entered rows (seed_facts, the operator CRUD screen) that this
-- migration must not reject. `fact_sources.slug` is the new machine-stable
-- handle an adapter binds to; it is nullable so every existing row stays
-- valid, and the ingestion service adopts the seeded "TurnBackHoax" row by
-- name on first run rather than creating a twin.
-- ==========================================================

ALTER TABLE fact_items ADD COLUMN IF NOT EXISTS external_id TEXT;
ALTER TABLE fact_items ADD COLUMN IF NOT EXISTS content_fingerprint TEXT;
ALTER TABLE fact_items ADD COLUMN IF NOT EXISTS published_at TIMESTAMPTZ;
ALTER TABLE fact_items ADD COLUMN IF NOT EXISTS ingested_at TIMESTAMPTZ;
ALTER TABLE fact_items ADD COLUMN IF NOT EXISTS raw_metadata JSONB;

CREATE UNIQUE INDEX IF NOT EXISTS idx_fact_items_source_external
    ON fact_items (source_id, external_id) WHERE external_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_fact_items_fingerprint
    ON fact_items (content_fingerprint) WHERE content_fingerprint IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_fact_items_published_at ON fact_items (published_at DESC);

ALTER TABLE fact_sources ADD COLUMN IF NOT EXISTS slug TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS idx_fact_sources_slug
    ON fact_sources (slug) WHERE slug IS NOT NULL;

-- ==========================================================
-- Ingestion runs — the operational record every "is the knowledge base
-- still being fed?" question is answered from. PARTIAL is a real outcome,
-- not a rounding of SUCCESS: items persisted but the Qdrant sync (or some
-- of the items) failed, and an operator needs to see the difference.
-- ==========================================================
DO $$ BEGIN
    CREATE TYPE ingestion_run_status_enum AS ENUM ('RUNNING', 'SUCCESS', 'PARTIAL', 'FAILED');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

CREATE TABLE IF NOT EXISTS fact_ingestion_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_slug TEXT NOT NULL,
    status ingestion_run_status_enum NOT NULL DEFAULT 'RUNNING',
    -- SCHEDULE (Celery Beat) or MANUAL (operator button). Not an enum: this is
    -- a provenance label, not a state machine.
    triggered_by TEXT NOT NULL DEFAULT 'SCHEDULE',
    started_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at TIMESTAMPTZ,
    fetched INT NOT NULL DEFAULT 0,
    created INT NOT NULL DEFAULT 0,
    updated INT NOT NULL DEFAULT 0,
    duplicates INT NOT NULL DEFAULT 0,
    failed INT NOT NULL DEFAULT 0,
    synced INT NOT NULL DEFAULT 0,
    sync_failed INT NOT NULL DEFAULT 0,
    error TEXT,
    details JSONB
);
CREATE INDEX IF NOT EXISTS idx_fact_ingestion_runs_source_started
    ON fact_ingestion_runs (source_slug, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_fact_ingestion_runs_status ON fact_ingestion_runs (status);

-- ==========================================================
-- Per-source cursor. The feed itself carries no cursor parameter, so this is
-- a restart hint and a freshness record, never the dedup mechanism — the
-- unique index above is. Keeping them separate means a lost/corrupted cursor
-- costs one extra pass over ten feed entries, not duplicate facts.
-- ==========================================================
CREATE TABLE IF NOT EXISTS fact_ingestion_cursors (
    source_slug TEXT PRIMARY KEY,
    last_external_id TEXT,
    last_published_at TIMESTAMPTZ,
    last_success_at TIMESTAMPTZ,
    last_run_id UUID REFERENCES fact_ingestion_runs(id) ON DELETE SET NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
