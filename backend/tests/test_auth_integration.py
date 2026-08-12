"""Operator auth against a live PostgreSQL.

The unit tests stub the store; these prove the SQL is real — that the unique
index is case-insensitive, that a revoked session stops resolving, and that an
expired one does too. Skipped when Postgres is unreachable.
"""

import uuid
from datetime import UTC, datetime, timedelta

import asyncpg
import pytest

from app.core.config import Settings, get_settings
from app.db.migrate import apply_migrations
from app.services import auth

pytestmark = pytest.mark.integration

# Fixture value only — never a credential used outside this test module.
TEST_PASSWORD = "unit-test-fixture-pw-not-real"  # noqa: S105  pragma: allowlist secret


def _cheap_settings(dsn: str) -> Settings:
    """Real settings, minimum bcrypt cost.

    Cost 12 is right in production and wrong in a test loop: it would add
    seconds per account created here for no extra coverage.
    """
    settings = get_settings().model_copy(update={"database_url": dsn, "auth_bcrypt_rounds": 4})
    return settings


@pytest.fixture
async def store(postgres_dsn):
    await apply_migrations(postgres_dsn)
    settings = _cheap_settings(postgres_dsn)
    created: list[str] = []

    yield settings, created

    conn = await asyncpg.connect(postgres_dsn)
    try:
        await conn.execute("DELETE FROM operators WHERE id = ANY($1::uuid[])", created)
    finally:
        await conn.close()


async def _new_operator(store, password: str = TEST_PASSWORD, active: bool = True):
    settings, created = store
    email = f"pytest-{uuid.uuid4().hex[:12]}@example.test"
    operator = await auth.create_operator(email, "Pytest Operator", password, settings)
    created.append(operator.id)

    if not active:
        conn = await asyncpg.connect(settings.database_url)
        try:
            await conn.execute("UPDATE operators SET is_active = FALSE WHERE id = $1", operator.id)
        finally:
            await conn.close()
    return operator


async def test_login_then_resolve_then_logout(store):
    settings, _ = store
    operator = await _new_operator(store)

    authenticated = await auth.authenticate(operator.email, TEST_PASSWORD, settings)
    assert authenticated is not None

    token, expires_at = await auth.create_session(authenticated, settings)
    assert expires_at > datetime.now(UTC)

    resolved = await auth.resolve_session(token, settings)
    assert resolved is not None and resolved.id == operator.id

    assert await auth.revoke_session(token, settings) is True
    assert await auth.resolve_session(token, settings) is None
    # Revoking twice is not an error, it is just no longer the first time.
    assert await auth.revoke_session(token, settings) is False


async def test_the_plaintext_token_is_never_stored(store):
    settings, _ = store
    operator = await _new_operator(store)
    token, _ = await auth.create_session(operator, settings)

    conn = await asyncpg.connect(settings.database_url)
    try:
        stored = await conn.fetchval(
            "SELECT token_hash FROM operator_sessions WHERE token_hash = $1", auth.hash_token(token)
        )
        leaked = await conn.fetchval(
            "SELECT count(*) FROM operator_sessions WHERE token_hash = $1", token
        )
    finally:
        await conn.close()

    assert stored == auth.hash_token(token)
    assert leaked == 0


async def test_expired_session_stops_resolving(store):
    settings, _ = store
    operator = await _new_operator(store)
    token, _ = await auth.create_session(operator, settings)

    conn = await asyncpg.connect(settings.database_url)
    try:
        await conn.execute(
            "UPDATE operator_sessions SET expires_at = $2 WHERE token_hash = $1",
            auth.hash_token(token),
            datetime.now(UTC) - timedelta(seconds=1),
        )
    finally:
        await conn.close()

    assert await auth.resolve_session(token, settings) is None


async def test_deactivating_an_account_kills_its_live_sessions(store):
    settings, _ = store
    operator = await _new_operator(store)
    token, _ = await auth.create_session(operator, settings)
    assert await auth.resolve_session(token, settings) is not None

    conn = await asyncpg.connect(settings.database_url)
    try:
        await conn.execute("UPDATE operators SET is_active = FALSE WHERE id = $1", operator.id)
    finally:
        await conn.close()

    # No logout, no expiry — the account itself is the thing that was switched off.
    assert await auth.resolve_session(token, settings) is None


async def test_disabled_account_cannot_authenticate(store):
    settings, _ = store
    operator = await _new_operator(store, active=False)

    assert await auth.authenticate(operator.email, TEST_PASSWORD, settings) is None


async def test_email_uniqueness_ignores_case(store):
    settings, _ = store
    operator = await _new_operator(store)

    with pytest.raises(ValueError):
        await auth.create_operator(operator.email.upper(), "Duplicate", "another-password", settings)


async def test_login_accepts_the_email_in_any_case(store):
    settings, _ = store
    operator = await _new_operator(store)

    assert await auth.authenticate(operator.email.upper(), TEST_PASSWORD, settings) is not None


async def test_unknown_email_and_wrong_password_are_both_none(store):
    settings, _ = store
    operator = await _new_operator(store)

    assert await auth.authenticate(operator.email, "wrong-password", settings) is None
    assert await auth.authenticate("nobody@example.test", TEST_PASSWORD, settings) is None


async def test_password_reset_invalidates_the_old_password(store):
    settings, _ = store
    operator = await _new_operator(store)

    assert await auth.set_password(operator.email, "a-brand-new-password", settings) is True
    assert await auth.authenticate(operator.email, TEST_PASSWORD, settings) is None
    assert await auth.authenticate(operator.email, "a-brand-new-password", settings) is not None


async def test_purge_removes_only_dead_sessions(store):
    settings, _ = store
    operator = await _new_operator(store)
    live, _ = await auth.create_session(operator, settings)
    dead, _ = await auth.create_session(operator, settings)
    await auth.revoke_session(dead, settings)

    await auth.purge_expired_sessions(settings)

    assert await auth.resolve_session(live, settings) is not None
    conn = await asyncpg.connect(settings.database_url)
    try:
        remaining = await conn.fetchval(
            "SELECT count(*) FROM operator_sessions WHERE token_hash = $1", auth.hash_token(dead)
        )
    finally:
        await conn.close()
    assert remaining == 0


async def test_login_records_last_login_at(store):
    settings, _ = store
    operator = await _new_operator(store)
    assert operator.last_login_at is None

    await auth.create_session(operator, settings)
    refreshed = await auth.authenticate(operator.email, TEST_PASSWORD, settings)

    assert refreshed is not None and refreshed.last_login_at is not None
