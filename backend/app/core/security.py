import logging

from fastapi import Header, HTTPException, status

from app.core.config import get_settings
from app.services import auth
from app.services.auth import AuthUnavailableError, Operator

logger = logging.getLogger("app.core.security")

# Sent on every 401 so a client can tell "log in again" apart from "you are not
# allowed to do this" without parsing the message.
_BEARER_CHALLENGE = {"WWW-Authenticate": "Bearer"}


async def verify_api_key(x_api_key: str | None = Header(default=None)) -> None:
    """WAHA webhook authentication — a machine credential, not an operator."""
    settings = get_settings()
    if not x_api_key or x_api_key != settings.waha_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing X-Api-Key",
        )


def bearer_token(authorization: str | None) -> str | None:
    """Extract the token from an `Authorization: Bearer <token>` header."""
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


async def require_operator(authorization: str | None = Header(default=None)) -> Operator:
    """Resolve the signed-in operator, or refuse the request.

    Failure modes are kept apart on purpose:

    - no/!bearer/unknown/expired/revoked token → **401**, log in again;
    - account store unreachable → **503**, because answering 401 would tell an
      operator their password is wrong when the truth is that PostgreSQL is
      down. Unlike the dashboard read endpoints, this one never degrades to
      "available: false" — a security gate that fails soft is not a gate.
    """
    token = bearer_token(authorization)
    if token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
            headers=_BEARER_CHALLENGE,
        )

    try:
        operator = await auth.resolve_session(token, get_settings())
    except AuthUnavailableError:
        logger.error("session lookup failed: account store unreachable", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication backend unavailable",
        ) from None

    if operator is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired session",
            headers=_BEARER_CHALLENGE,
        )
    return operator
