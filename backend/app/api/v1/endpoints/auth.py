"""Operator authentication for the Control Panel.

Email + password in, bearer session token out. No RBAC: every operator who can
sign in sees the whole panel. That is a deliberate scope choice, not an
oversight — roles are Phase 3 ([[07_Users_and_Risk]]), and a half-enforced role
model is worse than an honest single tier.

Accounts are created out-of-band with `python -m app.scripts.create_operator`.
There is no public sign-up endpoint: this is an internal security console, and
anyone who can reach the machine that runs the migrations is already trusted.
"""

import logging

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status

from app.core.config import get_settings
from app.core.rate_limit import LOGIN_KEY_PREFIX, check_rate_limit
from app.core.redis_client import get_redis
from app.core.security import bearer_token, require_operator
from app.schemas.auth import LoginRequest, LoginResponse, OperatorOut
from app.services import auth
from app.services.auth import AuthUnavailableError, Operator

logger = logging.getLogger("app.api.auth")

router = APIRouter()


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.post("/auth/login", response_model=LoginResponse)
async def login(payload: LoginRequest, request: Request) -> LoginResponse:
    settings = get_settings()
    email = auth.normalise_email(payload.email)
    scope = f"{email}:{_client_ip(request) or 'unknown'}"

    verdict = await check_rate_limit(
        get_redis(),
        settings,
        scope,
        limit=settings.auth_login_max_attempts,
        window=settings.auth_login_window_seconds,
        prefix=LOGIN_KEY_PREFIX,
    )
    if not verdict.allowed:
        # Counted per (email, IP) before the password is checked, so a wrong
        # password and a right one cost the same number of attempts. bcrypt
        # alone already makes online brute force slow; this makes it pointless.
        logger.warning("login rate limited", extra={"scope": scope, "count": verdict.current})
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts",
            headers={"Retry-After": str(verdict.retry_after)},
        )

    try:
        operator = await auth.authenticate(email, payload.password, settings)
    except AuthUnavailableError:
        logger.error("login failed: account store unreachable", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication backend unavailable",
        ) from None

    if operator is None:
        # One message for wrong password, unknown address, and disabled account.
        # Anything more specific is an account-enumeration oracle.
        logger.info("login rejected", extra={"email": email})
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    token, expires_at = await auth.create_session(
        operator,
        settings,
        user_agent=request.headers.get("user-agent"),
        ip_address=_client_ip(request),
    )
    logger.info("login accepted", extra={"operator_id": operator.id})

    return LoginResponse(
        access_token=token,
        expires_at=expires_at,
        operator=OperatorOut(**operator.as_dict()),
    )


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    _: Operator = Depends(require_operator),
    authorization: str | None = Header(default=None),
) -> None:
    """Revoke the presented session.

    Server-side revocation, not "the client forgot the token": the row is marked
    revoked, so a token copied out of the browser before logout stops working
    too.
    """
    token = bearer_token(authorization)
    if token:
        await auth.revoke_session(token, get_settings())


@router.get("/auth/me", response_model=OperatorOut)
async def me(operator: Operator = Depends(require_operator)) -> OperatorOut:
    """Who the current token belongs to — the frontend's session check on load."""
    return OperatorOut(**operator.as_dict())
