-- ==========================================================
-- 006 — Incident Management
-- Source of truth: 08_Dashboard/05_Incident_Management.md
--
-- MVP is operator-created/confirmed grouping only — automatic cross-signal
-- correlation is explicitly Post-MVP (05_Product_Scope_and_Roadmap §4). An
-- incident is built by picking existing Threats (message_logs rows already
-- HIGH/MEDIUM); nothing here groups anything on its own.
--
-- "Multiple users" and "related threat categories" (§1) are not stored
-- columns — both are computed at read time from the linked threats
-- (DISTINCT user_hash / DISTINCT detected_intent) so there is nothing here
-- that can drift from the messages it describes.
--
-- `severity` reuses `alert_severity_enum` (migration 005) instead of a third
-- severity scale — Incidents and Alerts already mean the same four levels.
--
-- Every statement is guarded so the whole file is safe to re-run.
-- ==========================================================

DO $$ BEGIN
    CREATE TYPE incident_state_enum AS ENUM ('OPEN', 'INVESTIGATING', 'CONTAINED', 'RESOLVED', 'FALSE_POSITIVE');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

CREATE TABLE IF NOT EXISTS incidents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    -- Backs the human-readable INC-<year>-<0001> code, computed at read time
    -- (app/services/incidents.py) rather than stored as a formatted string.
    sequence_number BIGINT GENERATED ALWAYS AS IDENTITY,
    title TEXT NOT NULL,
    severity alert_severity_enum NOT NULL,
    state incident_state_enum NOT NULL DEFAULT 'OPEN',
    assigned_operator_id UUID REFERENCES operators(id),
    resolution_reason TEXT,
    created_by UUID NOT NULL REFERENCES operators(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_incidents_state ON incidents (state);
CREATE INDEX IF NOT EXISTS idx_incidents_created_at ON incidents (created_at DESC);

-- update_updated_at_column() is created by 001.
DROP TRIGGER IF EXISTS update_incidents_modtime ON incidents;
CREATE TRIGGER update_incidents_modtime
    BEFORE UPDATE ON incidents
    FOR EACH ROW
    EXECUTE PROCEDURE update_updated_at_column();

CREATE TABLE IF NOT EXISTS incident_threats (
    incident_id UUID NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,
    message_log_id UUID NOT NULL REFERENCES message_logs(id),
    added_by UUID NOT NULL REFERENCES operators(id),
    added_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (incident_id, message_log_id)
);

CREATE INDEX IF NOT EXISTS idx_incident_threats_message ON incident_threats (message_log_id);

-- Append-only: no UPDATE/DELETE route exists for this table anywhere in the
-- app ("tidak bisa dihapus diam-diam", §4) — same discipline as audit_log.
CREATE TABLE IF NOT EXISTS incident_notes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    incident_id UUID NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,
    author_operator_id UUID NOT NULL REFERENCES operators(id),
    note TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_incident_notes_incident ON incident_notes (incident_id, created_at);

-- Additive only — mirrors source_threat_id so an Incident escalation raises
-- an Alert the same way a Threat escalation already does (migration 005).
-- No existing alerts row is affected.
ALTER TABLE alerts ADD COLUMN IF NOT EXISTS source_incident_id UUID REFERENCES incidents(id);
