-- ==========================================================
-- 013 — AI/ML Model Evaluation (04_AI_and_ML/06_Model_Evaluation.md)
--
-- Gate between "model finished training" and "model may serve production."
-- `training_job_id` names the trained model under test (its
-- generated_model_version); `dataset_id` is an independent VALIDATED
-- dataset used as the fixed eval/test set — not assumed equal to the
-- training job's own dataset. `ml-service`'s /v1/evaluate doesn't exist
-- yet, same bucket /v1/train was in before migration 012 — a real
-- evaluation run will genuinely fail with a real error, not a fabricated
-- score. See services/model_evaluations.py.
-- ==========================================================

DO $$ BEGIN
    CREATE TYPE model_evaluation_status_enum AS ENUM
        ('QUEUED', 'RUNNING', 'COMPLETED', 'FAILED', 'CANCELLED');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

CREATE TABLE IF NOT EXISTS model_evaluations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    training_job_id UUID NOT NULL REFERENCES training_jobs(id),
    dataset_id UUID NOT NULL REFERENCES datasets(id),
    status model_evaluation_status_enum NOT NULL DEFAULT 'QUEUED',
    progress FLOAT,
    metrics JSONB,
    error_message TEXT,
    celery_task_id TEXT,
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    created_by UUID NOT NULL REFERENCES operators(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_model_evaluations_status ON model_evaluations (status);
CREATE INDEX IF NOT EXISTS idx_model_evaluations_training_job ON model_evaluations (training_job_id);
CREATE INDEX IF NOT EXISTS idx_model_evaluations_dataset ON model_evaluations (dataset_id);

DROP TRIGGER IF EXISTS update_model_evaluations_modtime ON model_evaluations;
CREATE TRIGGER update_model_evaluations_modtime
    BEFORE UPDATE ON model_evaluations
    FOR EACH ROW
    EXECUTE PROCEDURE update_updated_at_column();
