-- ==========================================================
-- 009 — Security Policies (09_Security/02_Security_Policies.md)
--
-- IF <condition> THEN <action> response configuration. Answers "given a
-- signal, what do we do?" — distinct from Detection Rules (008), which
-- answers "is this suspicious?". Allowlist/Blocklist already live as
-- Detection Rules' ALLOWLIST/BLOCKLIST rule types, so this table only
-- covers the remaining §3 levers: category+threshold, user-specific,
-- default. Policies are visible/manageable only this stage — evaluating
-- them against live messages needs `app/pipeline/orchestrator.py`, a
-- separate, higher-risk follow-up. No columns for that unwritten data
-- are added here.
-- ==========================================================

DO $$ BEGIN
    CREATE TYPE policy_scope_enum AS ENUM ('DEFAULT', 'CATEGORY_THRESHOLD', 'USER_SPECIFIC');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE policy_action_enum AS ENUM ('ALLOW', 'WARN', 'BLOCK', 'ALERT', 'ESCALATE');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE policy_status_enum AS ENUM ('DRAFT', 'ACTIVE', 'DISABLED', 'ARCHIVED');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

CREATE TABLE IF NOT EXISTS policies (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    scope policy_scope_enum NOT NULL,
    condition JSONB NOT NULL,
    action policy_action_enum NOT NULL,
    priority INTEGER NOT NULL DEFAULT 100,
    status policy_status_enum NOT NULL DEFAULT 'DRAFT',
    created_by UUID NOT NULL REFERENCES operators(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_policies_status ON policies (status);
CREATE INDEX IF NOT EXISTS idx_policies_scope ON policies (scope);
CREATE INDEX IF NOT EXISTS idx_policies_priority ON policies (priority);

DROP TRIGGER IF EXISTS update_policies_modtime ON policies;
CREATE TRIGGER update_policies_modtime
    BEFORE UPDATE ON policies
    FOR EACH ROW
    EXECUTE PROCEDURE update_updated_at_column();
