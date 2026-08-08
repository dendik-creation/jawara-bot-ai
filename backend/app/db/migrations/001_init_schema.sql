-- ==========================================================
-- 001 — Sprint 1 relational schema
-- Source of truth: 03_Database/01_PostgreSQL_Schema.md
--
-- `fraud_blacklists` is intentionally absent: financial-fraud verification is
-- out of Sprint 1 scope, and an empty table would advertise a capability the
-- pipeline does not have yet.
--
-- Every statement is guarded so the whole file is safe to re-run (CI, partially
-- applied database, fresh volume).
-- ==========================================================

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ==========================================================
-- ENUM Types
-- ==========================================================
DO $$ BEGIN
    CREATE TYPE category_enum AS ENUM (
        'HEALTH_HOAX',
        'FINANCIAL_FRAUD',
        'GENERAL_NEWS',
        'PHISHING_LINK',
        'FILE_APK'
    );
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE verdict_enum AS ENUM (
        'HOAX',
        'FACT',
        'MISLEADING',
        'UNVERIFIED'
    );
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE risk_level_enum AS ENUM (
        'HIGH',
        'MEDIUM',
        'LOW',
        'UNKNOWN'
    );
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE input_type_enum AS ENUM (
        'TEXT',
        'IMAGE_OCR',
        'URL_LINK',
        'FILE_APK',
        'BANK_ACCOUNT'
    );
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- ==========================================================
-- 1. Fact Sources
-- ==========================================================
CREATE TABLE IF NOT EXISTS fact_sources (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    base_url VARCHAR(255) NOT NULL,
    is_trusted BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- ==========================================================
-- 2. Fact Items
-- ==========================================================
CREATE TABLE IF NOT EXISTS fact_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id INT REFERENCES fact_sources(id) ON DELETE SET NULL,
    category category_enum NOT NULL,
    title VARCHAR(255) NOT NULL,
    claim_summary TEXT NOT NULL,
    fact_explanation TEXT NOT NULL,
    verdict verdict_enum NOT NULL,
    source_url TEXT NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
   NEW.updated_at = CURRENT_TIMESTAMP;
   RETURN NEW;
END;
$$ language 'plpgsql';

DROP TRIGGER IF EXISTS update_fact_items_modtime ON fact_items;
CREATE TRIGGER update_fact_items_modtime
    BEFORE UPDATE ON fact_items
    FOR EACH ROW
    EXECUTE PROCEDURE update_updated_at_column();

-- ==========================================================
-- 3. User Subscriptions
-- user_hash = SHA-256(USER_HASH_SALT + ':' + phone/group id), see
-- backend/app/core/hashing.py — raw WhatsApp identifiers are never stored.
-- ==========================================================
CREATE TABLE IF NOT EXISTS user_subscriptions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_hash VARCHAR(64) UNIQUE NOT NULL,
    chat_type VARCHAR(20) NOT NULL CHECK (chat_type IN ('PERSONAL', 'GROUP')),
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- ==========================================================
-- 4. Message Logs (anonymous audit trail)
-- ==========================================================
CREATE TABLE IF NOT EXISTS message_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    waha_message_id VARCHAR(100) UNIQUE NOT NULL,
    waha_session_id VARCHAR(50) DEFAULT 'default',
    user_hash VARCHAR(64) NOT NULL REFERENCES user_subscriptions(user_hash) ON DELETE CASCADE,
    chat_type VARCHAR(20) NOT NULL CHECK (chat_type IN ('PERSONAL', 'GROUP')),
    input_type input_type_enum NOT NULL,
    extracted_text TEXT,
    detected_intent category_enum,
    risk_score risk_level_enum DEFAULT 'UNKNOWN',
    matched_fact_id UUID REFERENCES fact_items(id) ON DELETE SET NULL,
    similarity_score FLOAT CHECK (similarity_score >= 0.0 AND similarity_score <= 1.0),
    response_latency_ms INT,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- ==========================================================
-- Indexes
-- ==========================================================
CREATE INDEX IF NOT EXISTS idx_message_logs_created_at ON message_logs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_message_logs_intent ON message_logs(detected_intent);
CREATE INDEX IF NOT EXISTS idx_message_logs_user_hash ON message_logs(user_hash);
CREATE INDEX IF NOT EXISTS idx_fact_items_category ON fact_items(category) WHERE is_active = TRUE;
