"""Operator accounts and sessions for the Control Panel.

Two credential classes must never be confused (09_Security/06 §1): the operator
session token here is a per-person, short-lived identity; `WAHA_API_KEY` and
`ML_SERVICE_API_KEY` are machine credentials with a different threat model.
Nothing in this module authenticates a machine.

Design notes that are not obvious from the code:

**Sessions are rows, not signed tokens.** A stateless JWT cannot be revoked
without a denylist, which is a session table wearing a disguise. One indexed
lookup per request buys real logout, real "disable this account now", and a
list of who is currently signed in.

**The token is never stored.** Only its SHA-256. A leaked database backup then
contains no usable session.

**Errors from PostgreSQL are not swallowed.** An unreachable database during
authentication must surface as 503, never as "invalid credentials" — the
dashboard read endpoints degrade to `available: false`, but a security gate
that fails soft is not a gate.
"""

import hashlib
import logging
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import asyncpg

from app.core.config import Settings, get_settings
from app.core.passwords import dummy_verify, hash_password, verify_password

logger = logging.getLogger("app.services.auth")

# 32 bytes of urandom: guessing is not a threat model at that width, which is
# why the stored hash can be a plain SHA-256 instead of a slow KDF.
TOKEN_BYTES = 32


@dataclass(frozen=True)
class Operator:
    id: str
    email: str
    full_name: str
    is_active: bool
    last_login_at: datetime | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "email": self.email,
            "full_name": self.full_name,
            "last_login_at": self.last_login_at.isoformat() if self.last_login_at else None,
        }


class AuthUnavailableError(RuntimeError):
    """The account store could not be reached. Distinct from bad credentials."""


async def _connect(settings: Settings) -> asyncpg.Connection:
    try:
        return await asyncpg.connect(settings.database_url, timeout=5)
    except Exception as error:  # noqa: BLE001
        raise AuthUnavailableError(str(error)) from error


def normalise_email(email: str) -> str:
    return email.strip().lower()


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _operator_from_row(row: asyncpg.Record) -> Operator:
    return Operator(
        id=str(row["id"]),
        email=row["email"],
        full_name=row["full_name"],
        is_active=row["is_active"],
        last_login_at=row["last_login_at"],
    )


async def create_operator(
    email: str,
    full_name: str,
    password: str,
    settings: Settings | None = None,
) -> Operator:
    """Create an account, or raise `ValueError` if the email is taken."""
    settings = settings or get_settings()
    conn = await _connect(settings)
    try:
        row = await conn.fetchrow(
            """
            INSERT INTO operators (email, full_name, password_hash)
            VALUES ($1, $2, $3)
            RETURNING id, email, full_name, is_active, last_login_at
            """,
            normalise_email(email),
            full_name.strip(),
            hash_password(password, settings.auth_bcrypt_rounds),
        )
    except asyncpg.UniqueViolationError as error:
        raise ValueError(f"an operator with email {email!r} already exists") from error
    finally:
        await conn.close()
    return _operator_from_row(row)


async def set_password(email: str, password: str, settings: Settings | None = None) -> bool:
    """Reset one account's password. Returns False if no such account."""
    settings = settings or get_settings()
    conn = await _connect(settings)
    try:
        result = await conn.execute(
            "UPDATE operators SET password_hash = $2 WHERE lower(email) = $1",
            normalise_email(email),
            hash_password(password, settings.auth_bcrypt_rounds),
        )
    finally:
        await conn.close()
    return result.endswith(" 1")


async def set_full_name(operator_id: str, full_name: str, settings: Settings | None = None) -> Operator | None:
    """Update one account's display name. Returns None if no such account."""
    settings = settings or get_settings()
    conn = await _connect(settings)
    try:
        row = await conn.fetchrow(
            """
            UPDATE operators SET full_name = $2 WHERE id = $1
            RETURNING id, email, full_name, is_active, last_login_at
            """,
            operator_id,
            full_name.strip(),
        )
    finally:
        await conn.close()
    return _operator_from_row(row) if row else None


async def authenticate(email: str, password: str, settings: Settings | None = None) -> Operator | None:
    """Verify credentials. Returns None for wrong password, unknown or disabled account.

    The three failures are deliberately indistinguishable to the caller: telling
    an attacker that an address exists, or that it exists but is disabled, is a
    free account-enumeration oracle.
    """
    settings = settings or get_settings()
    conn = await _connect(settings)
    try:
        row = await conn.fetchrow(
            """
            SELECT id, email, full_name, password_hash, is_active, last_login_at
            FROM operators
            WHERE lower(email) = $1
            """,
            normalise_email(email),
        )
    finally:
        await conn.close()

    if row is None:
        dummy_verify(settings.auth_bcrypt_rounds)
        return None
    if not verify_password(password, row["password_hash"]):
        return None
    if not row["is_active"]:
        # Verified first, then refused: skipping the check for disabled accounts
        # would make them answer measurably faster than active ones.
        return None
    return _operator_from_row(row)


async def create_session(
    operator: Operator,
    settings: Settings | None = None,
    user_agent: str | None = None,
    ip_address: str | None = None,
) -> tuple[str, datetime]:
    """Issue a bearer token. Returns the plaintext token and its expiry.

    The plaintext is returned exactly once, here. It is not recoverable
    afterwards — only its hash is stored.
    """
    settings = settings or get_settings()
    token = secrets.token_urlsafe(TOKEN_BYTES)
    expires_at = datetime.now(UTC) + timedelta(minutes=settings.auth_session_ttl_minutes)

    conn = await _connect(settings)
    try:
        async with conn.transaction():
            await conn.execute(
                """
                INSERT INTO operator_sessions (operator_id, token_hash, expires_at, user_agent, ip_address)
                VALUES ($1, $2, $3, $4, $5::inet)
                """,
                operator.id,
                hash_token(token),
                expires_at,
                user_agent,
                ip_address,
            )
            await conn.execute(
                "UPDATE operators SET last_login_at = now() WHERE id = $1",
                operator.id,
            )
    finally:
        await conn.close()

    logger.info("operator session issued", extra={"operator_id": operator.id})
    return token, expires_at


async def resolve_session(token: str, settings: Settings | None = None) -> Operator | None:
    """Return the operator behind a bearer token, or None if it is not usable.

    Expiry, revocation and account deactivation are all checked in the query, so
    a session cannot outlive any of them by a single request.
    """
    settings = settings or get_settings()
    conn = await _connect(settings)
    try:
        row = await conn.fetchrow(
            """
            SELECT o.id, o.email, o.full_name, o.is_active, o.last_login_at
            FROM operator_sessions s
            JOIN operators o ON o.id = s.operator_id
            WHERE s.token_hash = $1
              AND s.revoked_at IS NULL
              AND s.expires_at > now()
              AND o.is_active
            """,
            hash_token(token),
        )
    finally:
        await conn.close()
    return _operator_from_row(row) if row else None


async def revoke_session(token: str, settings: Settings | None = None) -> bool:
    """Log out one session. Returns False if it was already gone or expired."""
    settings = settings or get_settings()
    conn = await _connect(settings)
    try:
        result = await conn.execute(
            "UPDATE operator_sessions SET revoked_at = now()"
            " WHERE token_hash = $1 AND revoked_at IS NULL",
            hash_token(token),
        )
    finally:
        await conn.close()
    return result.endswith(" 1")


async def purge_expired_sessions(settings: Settings | None = None) -> int:
    """Delete sessions that can no longer authenticate anything.

    Nothing calls this on a schedule yet — the table grows by one row per login.
    It is here so the cleanup is a function call rather than an improvised
    DELETE typed into psql when the table gets noticed.
    """
    settings = settings or get_settings()
    conn = await _connect(settings)
    try:
        result = await conn.execute(
            "DELETE FROM operator_sessions WHERE expires_at < now() OR revoked_at IS NOT NULL"
        )
    finally:
        await conn.close()
    return int(result.rsplit(" ", 1)[-1])
