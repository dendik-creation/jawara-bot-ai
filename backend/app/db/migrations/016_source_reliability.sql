-- ==========================================================
-- 016 — Source reliability scoring (audit §16, migration step 3)
--
-- `fact_sources.is_trusted` is a boolean, and retrieval needs a gradient: a
-- MAFINDO ruling and a "generally reliable ministry press page" are both
-- trusted, but when two matches are equally similar the ranker has to prefer
-- one. `reliability_score` is that gradient, in [0,1], and it feeds the
-- re-ranking step in ml-service (app/rag/ranking.py) — it never filters, so
-- a low score demotes a source's facts, it does not hide them.
--
-- Default 0.80, not 1.0: an unscored source should sit slightly below one an
-- operator has explicitly vouched for, without being treated as suspect.
-- Existing rows all take that default, so nothing already in the knowledge
-- base changes rank relative to anything else on the day this lands.
--
-- No decay column and no per-fact score: recency is computed at query time
-- from `fact_items.published_at` (migration 015), so there is nothing to
-- recompute on a schedule and nothing that can go stale between runs. The
-- score itself is a human judgement about a publisher, changed by an operator
-- through PATCH /knowledge/sources/{id} and recorded in audit_log — deriving
-- it automatically from outcome statistics is a later phase, deliberately not
-- faked here.
--
-- The score reaches Qdrant only through the existing sync path: it is
-- denormalised into each fact's payload by services/knowledge.py, so changing
-- a source's score requires re-syncing that source's facts. The API route
-- says so in its response rather than silently leaving Qdrant stale.
-- ==========================================================

ALTER TABLE fact_sources
    ADD COLUMN IF NOT EXISTS reliability_score NUMERIC(3, 2) NOT NULL DEFAULT 0.80;

DO $$ BEGIN
    ALTER TABLE fact_sources
        ADD CONSTRAINT fact_sources_reliability_range
        CHECK (reliability_score >= 0 AND reliability_score <= 1);
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
