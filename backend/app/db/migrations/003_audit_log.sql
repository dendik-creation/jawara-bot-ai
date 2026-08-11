-- ==========================================================
-- 003 — Operator action audit trail
-- Source of truth: 09_Security/05_Audit_Logs.md
--
-- This is distinct from `message_logs` (a *message processing* trail keyed by
-- anonymous `user_hash`). `audit_log` records what a signed-in *operator* did:
-- actor, action, target, timestamp, result, metadata.
--
-- Append-only by convention: no UPDATE/DELETE route exists anywhere in the
-- application for this table (§4 — "tidak boleh di-update atau dihapus lewat
-- jalur aplikasi"). Retention duration and a DB-level write-protection
-- mechanism (constraint, separate DB role, or both) are explicitly undecided
-- in the spec (§4 open question) — not resolved here, only inherited.
--
-- Every statement is guarded so the whole file is safe to re-run.
-- ==========================================================

CREATE TABLE IF NOT EXISTS audit_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    -- Nullable: a failed login against an email with no matching account has
    -- no operator to attribute it to. The attempted email goes in `metadata`
    -- instead, never a fabricated or guessed actor id.
    actor_operator_id UUID REFERENCES operators(id),
    action TEXT NOT NULL,
    target_type TEXT NOT NULL,
    target_id TEXT,
    result TEXT NOT NULL CHECK (result IN ('SUCCESS', 'FAILED', 'DENIED')),
    -- Old vs new value, reason, related IDs — shape varies by action.
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    ip_address INET,
    user_agent TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_audit_log_created_at ON audit_log (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_log_actor ON audit_log (actor_operator_id);
CREATE INDEX IF NOT EXISTS idx_audit_log_action ON audit_log (action);
CREATE INDEX IF NOT EXISTS idx_audit_log_target_type ON audit_log (target_type);
