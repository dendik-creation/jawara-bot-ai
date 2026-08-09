-- ==========================================================
-- 002 — Control Panel operator accounts and sessions
-- Source of truth: 09_Security/06_Platform_Security_Requirements.md §1
--
-- These are *operators* (the humans who open the Control Panel), deliberately
-- not called "users": `user_subscriptions.user_hash` already means a WhatsApp
-- end user, who is anonymous by design and never has an account here. Mixing
-- the two names in one schema would eventually mix them in one query.
--
-- Sessions are rows, not signed tokens. A JWT cannot be revoked without a
-- denylist, and "logout" that leaves a working token is not logout.
--
-- Every statement is guarded so the whole file is safe to re-run.
-- ==========================================================

CREATE TABLE IF NOT EXISTS operators (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email VARCHAR(255) NOT NULL,
    full_name VARCHAR(120) NOT NULL,
    -- bcrypt output, never the password. TEXT rather than a fixed width: the
    -- algorithm prefix and cost factor are part of the value and will change.
    password_hash TEXT NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    last_login_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Uniqueness on lower(email): addresses are case-insensitive in practice, and
-- two accounts differing only by capitalisation are an account-takeover trick,
-- not a feature. The application also normalises before writing.
CREATE UNIQUE INDEX IF NOT EXISTS idx_operators_email_lower ON operators (lower(email));

-- update_updated_at_column() is created by 001.
DROP TRIGGER IF EXISTS update_operators_modtime ON operators;
CREATE TRIGGER update_operators_modtime
    BEFORE UPDATE ON operators
    FOR EACH ROW
    EXECUTE PROCEDURE update_updated_at_column();

CREATE TABLE IF NOT EXISTS operator_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    operator_id UUID NOT NULL REFERENCES operators(id) ON DELETE CASCADE,
    -- SHA-256 of the bearer token, never the token. A database dump must not
    -- hand out live sessions. No bcrypt here on purpose: the token is 32 random
    -- bytes, so there is nothing to brute-force and a slow hash on every
    -- request would only cost latency.
    token_hash CHAR(64) UNIQUE NOT NULL,
    issued_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMPTZ NOT NULL,
    revoked_at TIMESTAMPTZ,
    user_agent TEXT,
    ip_address INET
);

CREATE INDEX IF NOT EXISTS idx_operator_sessions_operator ON operator_sessions(operator_id);
CREATE INDEX IF NOT EXISTS idx_operator_sessions_expires ON operator_sessions(expires_at);
