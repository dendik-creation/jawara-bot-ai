-- ==========================================================
-- 005 — Alert Center
-- Source of truth: 09_Security/04_Alert_Center.md
--
-- An alert is a notification that needs operator attention — distinct from a
-- Threat (a finding) and an Incident (an investigation unit, not built yet).
-- Only one source is wired this stage: a Threat resolved with the `ESCALATE`
-- action (see `app/services/threats.py`). `source` is a plain string, not an
-- enum, so later stages (platform health, aggregate thresholds, AI/ML ops —
-- all §5 of the spec doc) can add sources without a migration.
--
-- `ESCALATED` is a defined but currently unreachable state: it means
-- "promoted to an Incident" (§4), and Incidents don't exist yet. Same
-- reasoning migration 004 used for Threats' `ACTIONED`.
--
-- Every statement is guarded so the whole file is safe to re-run.
-- ==========================================================

DO $$ BEGIN
    CREATE TYPE alert_severity_enum AS ENUM ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE alert_state_enum AS ENUM ('NEW', 'ACKNOWLEDGED', 'RESOLVED', 'ESCALATED');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

CREATE TABLE IF NOT EXISTS alerts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    severity alert_severity_enum NOT NULL,
    title TEXT NOT NULL,
    source TEXT NOT NULL,
    source_threat_id UUID REFERENCES message_logs(id),
    state alert_state_enum NOT NULL DEFAULT 'NEW',
    assigned_operator_id UUID REFERENCES operators(id),
    resolution_reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_alerts_state ON alerts (state);
CREATE INDEX IF NOT EXISTS idx_alerts_severity ON alerts (severity);
CREATE INDEX IF NOT EXISTS idx_alerts_created_at ON alerts (created_at DESC);

-- update_updated_at_column() is created by 001.
DROP TRIGGER IF EXISTS update_alerts_modtime ON alerts;
CREATE TRIGGER update_alerts_modtime
    BEFORE UPDATE ON alerts
    FOR EACH ROW
    EXECUTE PROCEDURE update_updated_at_column();
