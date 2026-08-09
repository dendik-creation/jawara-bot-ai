"""Password hashing for Control Panel operators.

bcrypt, because it is the conservative choice that ships as a wheel everywhere
and needs no tuning to be safe. The cost factor is configurable
(`AUTH_BCRYPT_ROUNDS`) so it can be raised as hardware gets faster without a
code change; existing hashes carry their own cost and keep verifying.
"""

import base64
import hashlib
import secrets
from functools import lru_cache

import bcrypt


def _prepare(password: str) -> bytes:
    """Fold the password into 44 bytes so bcrypt's 72-byte limit never bites.

    bcrypt silently ignores everything past byte 72: without this, two long
    passphrases sharing a prefix would be the same password. SHA-256 first,
    base64 second (bcrypt also stops at the first NUL byte, which raw digest
    bytes can contain).
    """
    return base64.b64encode(hashlib.sha256(password.encode("utf-8")).digest())


def hash_password(password: str, rounds: int = 12) -> str:
    return bcrypt.hashpw(_prepare(password), bcrypt.gensalt(rounds)).decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(_prepare(password), password_hash.encode("ascii"))
    except (ValueError, TypeError):
        # A malformed stored hash is a failed login, not a 500.
        return False


@lru_cache(maxsize=4)
def _dummy_hash(rounds: int) -> bytes:
    """A hash of a value no caller can produce, at the same cost as a real one."""
    return bcrypt.hashpw(secrets.token_bytes(32), bcrypt.gensalt(rounds))


def dummy_verify(rounds: int = 12) -> None:
    """Burn one bcrypt verification against a throwaway hash.

    Called when the email does not exist. Without it, "no such account" returns
    in microseconds while a real account costs the full bcrypt work factor, and
    the difference is a reliable account-enumeration oracle. `rounds` must match
    the cost real accounts were hashed at, or the timing gap reopens.
    """
    bcrypt.checkpw(_prepare("dummy"), _dummy_hash(rounds))
