-- ==========================================================
-- 008 — Detection Rules (09_Security/03_Detection_Rules.md)
--
-- Deterministic rule CRUD (keyword/domain/URL/threshold/pattern/repeated-
-- offender/rate-limit/allowlist/blocklist). Rules are visible/manageable
-- only this stage — matching them against live messages (trigger counts,
-- false-positive rates, "Applied detection rule" on Message Inspection)
-- needs `app/pipeline/orchestrator.py` to evaluate rules, a separate,
-- higher-risk follow-up. No columns for that unwritten data are added here.
-- ==========================================================

DO $$ BEGIN
    CREATE TYPE detection_rule_type_enum AS ENUM (
        'KEYWORD',
        'DOMAIN',
        'URL',
        'RISK_THRESHOLD',
        'PATTERN',
        'REPEATED_OFFENDER',
        'RATE_LIMIT',
        'ALLOWLIST',
        'BLOCKLIST'
    );
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE detection_rule_status_enum AS ENUM ('DRAFT', 'ACTIVE', 'DISABLED', 'ARCHIVED');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

CREATE TABLE IF NOT EXISTS detection_rules (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    rule_type detection_rule_type_enum NOT NULL,
    condition JSONB NOT NULL,
    severity risk_level_enum NOT NULL,
    status detection_rule_status_enum NOT NULL DEFAULT 'DRAFT',
    created_by UUID NOT NULL REFERENCES operators(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_detection_rules_status ON detection_rules (status);
CREATE INDEX IF NOT EXISTS idx_detection_rules_type ON detection_rules (rule_type);

-- reuse update_updated_at_column() trigger, same as operators/threat_cases/alerts/incidents/user_blocks
DROP TRIGGER IF EXISTS update_detection_rules_modtime ON detection_rules;
CREATE TRIGGER update_detection_rules_modtime
    BEFORE UPDATE ON detection_rules
    FOR EACH ROW
    EXECUTE PROCEDURE update_updated_at_column();
