-- ==========================================================
-- 012 — AI/ML Training Jobs (04_AI_and_ML/05_Training_Jobs.md)
--
-- Orchestration/tracking layer for a controlled async training operation —
-- job record, status lifecycle, config-for-reproducibility. `dataset_id`
-- alone captures "dataset version" (datasets.id already uniquely identifies
-- one (name, version) row, migration 011). `ml-service`'s /v1/train doesn't
-- exist yet, so COMPLETED/metrics/generated_model_version are real columns
-- with no reachable path today — a job that runs will genuinely fail with a
-- real error, not a fabricated success. See services/training_jobs.py.
-- ==========================================================

DO $$ BEGIN
    CREATE TYPE training_job_status_enum AS ENUM
        ('QUEUED', 'RUNNING', 'EVALUATING', 'COMPLETED', 'FAILED', 'CANCELLED');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

CREATE TABLE IF NOT EXISTS training_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    dataset_id UUID NOT NULL REFERENCES datasets(id),
    base_model TEXT NOT NULL,
    epochs INTEGER,
    learning_rate FLOAT,
    batch_size INTEGER,
    validation_split FLOAT,
    extra_config JSONB,
    status training_job_status_enum NOT NULL DEFAULT 'QUEUED',
    progress FLOAT,
    metrics JSONB,
    error_message TEXT,
    generated_model_version TEXT,
    celery_task_id TEXT,
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    created_by UUID NOT NULL REFERENCES operators(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_training_jobs_status ON training_jobs (status);
CREATE INDEX IF NOT EXISTS idx_training_jobs_dataset ON training_jobs (dataset_id);

DROP TRIGGER IF EXISTS update_training_jobs_modtime ON training_jobs;
CREATE TRIGGER update_training_jobs_modtime
    BEFORE UPDATE ON training_jobs
    FOR EACH ROW
    EXECUTE PROCEDURE update_updated_at_column();
