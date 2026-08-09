"""Audit trail write path ([[Create Audit Logging]]).

The integration tests need a live PostgreSQL with migration 001 applied; they
skip otherwise (same policy as `test_migrations.py`).
"""

import uuid

import asyncpg
import pytest

from app.core.config import get_settings
from app.core.hashing import hash_user_identifier
from app.db.migrate import apply_migrations
from app.pipeline.categories import Category, InputType, RiskLevel
from app.services.message_log import MessageLogEntry, chat_type_for, record_message


def test_chat_type_is_derived_from_the_whatsapp_id():
    assert chat_type_for("628111@c.us") == "PERSONAL"
    assert chat_type_for("62811-1234@g.us") == "GROUP"
    assert chat_type_for(None) == "PERSONAL"


def make_entry(**overrides) -> MessageLogEntry:
    settings = get_settings()
    base = {
        "waha_message_id": f"test_{uuid.uuid4().hex}",
        "user_hash": hash_user_identifier(f"628{uuid.uuid4().int % 10**9}@c.us", settings),
        "chat_type": "PERSONAL",
        "input_type": InputType.TEXT,
        "extracted_text": "air rebusan daun kitolod menyembuhkan katarak",
        "detected_intent": Category.HEALTH_HOAX,
        "risk_score": RiskLevel.HIGH,
        "similarity_score": 0.91,
        "response_latency_ms": 1420,
    }
    base.update(overrides)
    return MessageLogEntry(**base)


@pytest.fixture
async def migrated(postgres_dsn):
    await apply_migrations(postgres_dsn)
    return postgres_dsn


@pytest.mark.integration
async def test_every_dispatched_response_gets_a_row(migrated):
    entry = make_entry()
    assert await record_message(entry) is True

    conn = await asyncpg.connect(migrated)
    try:
        row = await conn.fetchrow(
            "SELECT * FROM message_logs WHERE waha_message_id = $1", entry.waha_message_id
        )
        assert row["detected_intent"] == "HEALTH_HOAX"
        assert row["risk_score"] == "HIGH"
        assert row["input_type"] == "TEXT"
        assert row["similarity_score"] == pytest.approx(0.91)
        assert row["response_latency_ms"] == 1420
        assert row["user_hash"] == entry.user_hash
    finally:
        await conn.execute("DELETE FROM message_logs WHERE waha_message_id = $1", entry.waha_message_id)
        await conn.execute("DELETE FROM user_subscriptions WHERE user_hash = $1", entry.user_hash)
        await conn.close()


@pytest.mark.integration
async def test_webhook_retry_does_not_duplicate_the_row(migrated):
    entry = make_entry()
    assert await record_message(entry) is True
    assert await record_message(entry) is False  # same waha_message_id

    conn = await asyncpg.connect(migrated)
    try:
        count = await conn.fetchval(
            "SELECT count(*) FROM message_logs WHERE waha_message_id = $1", entry.waha_message_id
        )
        assert count == 1
    finally:
        await conn.execute("DELETE FROM message_logs WHERE waha_message_id = $1", entry.waha_message_id)
        await conn.execute("DELETE FROM user_subscriptions WHERE user_hash = $1", entry.user_hash)
        await conn.close()


@pytest.mark.integration
async def test_subscription_is_created_for_a_first_time_chat(migrated):
    entry = make_entry()
    await record_message(entry)

    conn = await asyncpg.connect(migrated)
    try:
        row = await conn.fetchrow(
            "SELECT chat_type, is_active FROM user_subscriptions WHERE user_hash = $1", entry.user_hash
        )
        assert row["chat_type"] == "PERSONAL"
        assert row["is_active"] is True
    finally:
        await conn.execute("DELETE FROM message_logs WHERE waha_message_id = $1", entry.waha_message_id)
        await conn.execute("DELETE FROM user_subscriptions WHERE user_hash = $1", entry.user_hash)
        await conn.close()


@pytest.mark.integration
async def test_content_logging_can_be_switched_off(migrated, monkeypatch):
    from app.core.config import Settings

    settings = Settings(log_message_content=False, database_url=migrated)
    entry = make_entry()
    await record_message(entry, settings)

    conn = await asyncpg.connect(migrated)
    try:
        text = await conn.fetchval(
            "SELECT extracted_text FROM message_logs WHERE waha_message_id = $1", entry.waha_message_id
        )
        assert text is None
    finally:
        await conn.execute("DELETE FROM message_logs WHERE waha_message_id = $1", entry.waha_message_id)
        await conn.execute("DELETE FROM user_subscriptions WHERE user_hash = $1", entry.user_hash)
        await conn.close()
