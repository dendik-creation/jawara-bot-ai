import hashlib

from app.core.config import Settings


def hash_user_identifier(identifier: str, settings: Settings) -> str:
    """SHA-256 of a salted WhatsApp phone number / group ID.

    Convention (fixed here, referenced by 03_Database/01_PostgreSQL_Schema):
    `sha256(USER_HASH_SALT + ':' + identifier)`, lowercase hex, 64 chars —
    matching `user_subscriptions.user_hash VARCHAR(64)`.

    The salt is a single application-wide secret held in `USER_HASH_SALT`, not a
    per-row salt: `user_hash` must be a stable lookup key across messages, so it
    has to be reproducible from the raw chat ID alone. Rotating the salt
    invalidates every existing `user_hash` (subscriptions and their logs are
    orphaned by the FK cascade) — treat rotation as a data migration, not a
    config change.
    """
    if not identifier:
        raise ValueError("identifier must not be empty")
    return hashlib.sha256(f"{settings.user_hash_salt}:{identifier}".encode()).hexdigest()
