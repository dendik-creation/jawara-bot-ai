-- ==========================================================
-- 011 — AI/ML Datasets & Operator Feedback (04_AI_and_ML/04_Datasets_and_Operator_Feedback.md)
--
-- Operator Feedback: append-only human-in-the-loop correction events, fed
-- from Threats' CONFIRM/FALSE_POSITIVE actions (Stage 2). Independent of
-- `threat_cases`, which is a resolution *overlay* (one row per message,
-- overwritten on re-action) — feedback needs durable history, not a
-- current-state row.
--
-- Datasets: curated/versioned/validated training data. `dataset_samples.label`
-- is TEXT, not `category_enum` — a real negative class ("NOT_A_THREAT", from
-- false-positive feedback) doesn't fit that content-topic taxonomy, which is
-- already schema- and test-locked against extension (Stage 8's own finding).
-- Validated against an application-level set instead of a DB enum.
-- ==========================================================

DO $$ BEGIN
    CREATE TYPE feedback_type_enum AS ENUM ('CONFIRM', 'FALSE_POSITIVE');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE dataset_source_enum AS ENUM ('CURATED', 'OPERATOR_FEEDBACK', 'IMPORTED', 'APPROVED_INTERNAL');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE dataset_status_enum AS ENUM ('DRAFT', 'VALIDATING', 'VALIDATED', 'REJECTED', 'ARCHIVED');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

CREATE TABLE IF NOT EXISTS operator_feedback (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    message_log_id UUID NOT NULL REFERENCES message_logs(id) ON DELETE CASCADE,
    original_classification category_enum,
    feedback_type feedback_type_enum NOT NULL,
    model_version TEXT,
    reason TEXT,
    actor_operator_id UUID NOT NULL REFERENCES operators(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_operator_feedback_message ON operator_feedback (message_log_id);
CREATE INDEX IF NOT EXISTS idx_operator_feedback_type ON operator_feedback (feedback_type);

CREATE TABLE IF NOT EXISTS datasets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    source dataset_source_enum NOT NULL,
    status dataset_status_enum NOT NULL DEFAULT 'DRAFT',
    description TEXT,
    validation_notes TEXT,
    created_by UUID NOT NULL REFERENCES operators(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (name, version)
);
CREATE INDEX IF NOT EXISTS idx_datasets_status ON datasets (status);

CREATE TABLE IF NOT EXISTS dataset_samples (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    dataset_id UUID NOT NULL REFERENCES datasets(id) ON DELETE CASCADE,
    text TEXT NOT NULL,
    label TEXT NOT NULL,
    source_message_log_id UUID REFERENCES message_logs(id) ON DELETE SET NULL,
    source_feedback_id UUID REFERENCES operator_feedback(id) ON DELETE SET NULL,
    added_by UUID NOT NULL REFERENCES operators(id),
    added_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_dataset_samples_dataset ON dataset_samples (dataset_id);

DROP TRIGGER IF EXISTS update_datasets_modtime ON datasets;
CREATE TRIGGER update_datasets_modtime
    BEFORE UPDATE ON datasets
    FOR EACH ROW
    EXECUTE PROCEDURE update_updated_at_column();
