-- ==========================================================
-- 007 — End-user blocklist
-- Source of truth: 08_Dashboard/07_Users_and_Risk.md §3
--
-- "Blocklist end user adalah keputusan keamanan: perlu alasan, punya jejak
-- audit, dan bisa dicabut" — a security decision that needs a reason, an
-- audit trail (app.services.audit, already built), and must be revocable.
-- Indicator-level (domain/URL) blocklisting is explicitly separate, owned by
-- Detection Rules — not this table.
--
-- A row exists only once an operator has taken a block/unblock action on
-- that user — absence of a row means "never actioned," the same
-- row-existence-is-the-signal pattern threat_cases (migration 004)
-- established. `reason` is required on both directions: revoking a block is
-- itself framed as a decision in the spec, not a no-op undo.
--
-- Every statement is guarded so the whole file is safe to re-run.
-- ==========================================================

CREATE TABLE IF NOT EXISTS user_blocks (
    user_hash VARCHAR(64) PRIMARY KEY REFERENCES user_subscriptions(user_hash) ON DELETE CASCADE,
    blocked BOOLEAN NOT NULL,
    reason TEXT NOT NULL,
    actor_operator_id UUID NOT NULL REFERENCES operators(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_user_blocks_blocked ON user_blocks (blocked);

-- update_updated_at_column() is created by 001.
DROP TRIGGER IF EXISTS update_user_blocks_modtime ON user_blocks;
CREATE TRIGGER update_user_blocks_modtime
    BEFORE UPDATE ON user_blocks
    FOR EACH ROW
    EXECUTE PROCEDURE update_updated_at_column();
