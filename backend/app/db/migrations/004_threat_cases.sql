-- ==========================================================
-- 004 — Threat resolution overlay
-- Source of truth: 08_Dashboard/03_Threat_Monitoring.md
--
-- A "threat" is not a new fact to store — it is any `message_logs` row with
-- `risk_score IN ('HIGH','MEDIUM')`, viewed through the operator's triage
-- lens. `threat_cases` holds only the part that doesn't already exist
-- anywhere: the operator's resolving action. A `message_logs` row with no
-- matching `threat_cases` row is an *open* threat, not a missing one.
--
-- No `state` column: `DETECTED`/`ANALYZED`/`ACTIONED` describe pipeline and
-- security-policy stages this system doesn't have yet (classification is
-- synchronous today, and there is no policy engine to apply `ACTIONED`
-- automatically). Storing a state machine most of whose transitions cannot
-- happen would be schema for a capability that doesn't exist. The API layer
-- derives `state` instead: `RESOLVED` when a row exists here, `ANALYZED`
-- otherwise.
--
-- Every statement is guarded so the whole file is safe to re-run.
-- ==========================================================

DO $$ BEGIN
    CREATE TYPE threat_action_enum AS ENUM (
        'ALLOW',
        'WARN',
        'BLOCK',
        'ESCALATE',
        'CONFIRM',
        'FALSE_POSITIVE'
    );
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

CREATE TABLE IF NOT EXISTS threat_cases (
    message_log_id UUID PRIMARY KEY REFERENCES message_logs(id) ON DELETE CASCADE,
    action threat_action_enum NOT NULL,
    notes TEXT,
    actor_operator_id UUID NOT NULL REFERENCES operators(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_threat_cases_action ON threat_cases (action);

-- update_updated_at_column() is created by 001.
DROP TRIGGER IF EXISTS update_threat_cases_modtime ON threat_cases;
CREATE TRIGGER update_threat_cases_modtime
    BEFORE UPDATE ON threat_cases
    FOR EACH ROW
    EXECUTE PROCEDURE update_updated_at_column();
