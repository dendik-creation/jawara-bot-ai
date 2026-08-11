-- ==========================================================
-- 014 — AI/ML Model Registry & Deployment (04_AI_and_ML/07_Model_Registry_and_Deployment.md)
--
-- Lifecycle: CANDIDATE -> VALIDATED -> PRODUCTION -> ARCHIVED. A row is
-- always system-created (no `created_by`) the moment a model_evaluation
-- reaches COMPLETED (see services/model_evaluations.py's
-- execute_model_evaluation) — never by a human, and never automatically
-- promoted (07_Model_Registry_and_Deployment §3's own rule). From CANDIDATE
-- onward, only explicit human PATCH actions (VALIDATE/PROMOTE/ARCHIVE) move
-- a row forward. No per-transition actor/timestamp columns (validated_by,
-- promoted_by, ...): audit_log + the existing updated_at trigger are the
-- single source of truth for who/when, same convention `policies`/
-- `datasets` already use. `training_job_id` is derivable from
-- `model_evaluation_id` but kept as a direct column — it's set once at
-- insert by the one code path that creates rows, so there's no drift risk,
-- and it makes "all versions from this job" queryable without a two-hop
-- join. `/v1/evaluate` doesn't exist in ml-service yet (migration 013's own
-- header), so this table is genuinely unreachable today — no fabricated
-- production model, no fabricated data.
-- ==========================================================

DO $$ BEGIN
    CREATE TYPE model_version_status_enum AS ENUM
        ('CANDIDATE', 'VALIDATED', 'PRODUCTION', 'ARCHIVED');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

CREATE TABLE IF NOT EXISTS model_versions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    training_job_id UUID NOT NULL REFERENCES training_jobs(id),
    model_evaluation_id UUID NOT NULL REFERENCES model_evaluations(id),
    status model_version_status_enum NOT NULL DEFAULT 'CANDIDATE',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_model_versions_status ON model_versions (status);
CREATE INDEX IF NOT EXISTS idx_model_versions_training_job ON model_versions (training_job_id);
-- Only one PRODUCTION row at a time — hard DB backstop behind the
-- application-level demote-then-promote transaction (07_Model_Registry §5's
-- rollback rule: previous production is demoted to ARCHIVED, never deleted).
CREATE UNIQUE INDEX IF NOT EXISTS idx_model_versions_single_production
    ON model_versions (status) WHERE status = 'PRODUCTION';

DROP TRIGGER IF EXISTS update_model_versions_modtime ON model_versions;
CREATE TRIGGER update_model_versions_modtime
    BEFORE UPDATE ON model_versions
    FOR EACH ROW
    EXECUTE PROCEDURE update_updated_at_column();
