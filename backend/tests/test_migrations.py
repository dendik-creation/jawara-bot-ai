import asyncpg
import pytest

from app.db.migrate import apply_migrations, migration_files

pytestmark = pytest.mark.integration

EXPECTED_ENUMS = {
    "category_enum": ["HEALTH_HOAX", "FINANCIAL_FRAUD", "GENERAL_NEWS", "PHISHING_LINK", "FILE_APK"],
    "verdict_enum": ["HOAX", "FACT", "MISLEADING", "UNVERIFIED"],
    "risk_level_enum": ["HIGH", "MEDIUM", "LOW", "UNKNOWN"],
    "input_type_enum": ["TEXT", "IMAGE_OCR", "URL_LINK", "FILE_APK", "BANK_ACCOUNT"],
}


@pytest.fixture
async def migrated(postgres_dsn):
    await apply_migrations(postgres_dsn)
    return postgres_dsn


@pytest.fixture
async def conn(migrated):
    connection = await asyncpg.connect(migrated)
    try:
        yield connection
    finally:
        await connection.close()


async def test_rerunning_migrations_is_a_noop(migrated):
    assert await apply_migrations(migrated) == []


async def test_migration_sql_is_idempotent_on_its_own(migrated):
    """Ledger aside, replaying the raw DDL must not error — CI may run it on a
    database that already has the schema but no `schema_migrations` row."""
    connection = await asyncpg.connect(migrated)
    try:
        for path in migration_files():
            await connection.execute(path.read_text(encoding="utf-8"))
    finally:
        await connection.close()


@pytest.mark.parametrize("enum_name,values", list(EXPECTED_ENUMS.items()))
async def test_enum_values_match_documentation(conn, enum_name, values):
    rows = await conn.fetch(
        "SELECT e.enumlabel FROM pg_enum e JOIN pg_type t ON t.oid = e.enumtypid"
        " WHERE t.typname = $1 ORDER BY e.enumsortorder",
        enum_name,
    )
    assert [r["enumlabel"] for r in rows] == values


@pytest.mark.parametrize(
    "table,column,expected_action",
    [
        ("fact_items", "source_id", "n"),  # SET NULL
        ("message_logs", "user_hash", "c"),  # CASCADE
        ("message_logs", "matched_fact_id", "n"),  # SET NULL
    ],
)
async def test_foreign_key_delete_actions(conn, table, column, expected_action):
    action = await conn.fetchval(
        """
        SELECT c.confdeltype::text
        FROM pg_constraint c
        JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = ANY (c.conkey)
        WHERE c.contype = 'f' AND c.conrelid = $1::regclass AND a.attname = $2
        """,
        table,
        column,
    )
    assert action == expected_action


async def test_indexes_exist(conn):
    rows = await conn.fetch("SELECT indexname FROM pg_indexes WHERE schemaname = 'public'")
    names = {r["indexname"] for r in rows}
    assert {
        "idx_message_logs_created_at",
        "idx_message_logs_intent",
        "idx_message_logs_user_hash",
        "idx_fact_items_category",
    } <= names


async def test_fraud_blacklists_is_out_of_sprint_scope(conn):
    exists = await conn.fetchval("SELECT to_regclass('public.fraud_blacklists')")
    assert exists is None


async def test_updated_at_trigger_fires_on_update(conn):
    # Insert and update must be separate transactions: the trigger uses
    # CURRENT_TIMESTAMP, which is the transaction start time, so both rows would
    # carry the identical timestamp inside one transaction.
    source_id = await conn.fetchval(
        "INSERT INTO fact_sources (name, base_url) VALUES ('pytest', 'https://example.test')"
        " RETURNING id"
    )
    fact_id, created = await conn.fetchrow(
        """
        INSERT INTO fact_items (source_id, category, title, claim_summary, fact_explanation,
                                verdict, source_url)
        VALUES ($1, 'HEALTH_HOAX', 't', 'c', 'e', 'HOAX', 'https://example.test/x')
        RETURNING id, updated_at
        """,
        source_id,
    )
    try:
        updated = await conn.fetchval(
            "UPDATE fact_items SET title = 't2' WHERE id = $1 RETURNING updated_at", fact_id
        )
        assert updated > created
    finally:
        await conn.execute("DELETE FROM fact_items WHERE id = $1", fact_id)
        await conn.execute("DELETE FROM fact_sources WHERE id = $1", source_id)


async def test_duplicate_waha_message_id_is_rejected(conn):
    tx = conn.transaction()
    await tx.start()
    try:
        user_hash = "0" * 64
        await conn.execute(
            "INSERT INTO user_subscriptions (user_hash, chat_type) VALUES ($1, 'PERSONAL')", user_hash
        )
        insert = """
            INSERT INTO message_logs (waha_message_id, user_hash, chat_type, input_type)
            VALUES ('pytest_dup_id', $1, 'PERSONAL', 'TEXT')
        """
        await conn.execute(insert, user_hash)
        with pytest.raises(asyncpg.UniqueViolationError):
            await conn.execute(insert, user_hash)
    finally:
        await tx.rollback()
