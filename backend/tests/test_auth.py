"""Operator authentication: password handling, the session gate, login limits.

The gate is tested through the HTTP layer, not by calling `resolve_session`
directly — what matters is that an unauthenticated request cannot reach a
Control Panel endpoint, and that is a routing fact as much as a service one.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.core import passwords
from app.core.security import bearer_token, require_operator
from app.main import app
from app.services.auth import AuthUnavailableError, Operator

client = TestClient(app)

# Fixture value only — never a credential used outside this test module.
TEST_PASSWORD = "unit-test-fixture-pw-not-real"  # noqa: S105  pragma: allowlist secret

OPERATOR = Operator(
    id="11111111-1111-1111-1111-111111111111",
    email="ops@example.com",
    full_name="Operator Satu",
    is_active=True,
)


@pytest.fixture
def signed_in():
    """Bypass the session lookup — the gate itself has its own tests below."""
    app.dependency_overrides[require_operator] = lambda: OPERATOR
    yield
    app.dependency_overrides.pop(require_operator, None)


@pytest.fixture(autouse=True)
def no_login_rate_limit(monkeypatch):
    """Keep Redis out of the unit tests; the limiter has its own test module."""
    from app.core.rate_limit import RateLimitResult

    monkeypatch.setattr(
        "app.api.v1.endpoints.auth.check_rate_limit",
        AsyncMock(return_value=RateLimitResult(allowed=True, current=1, limit=5, retry_after=300)),
    )


# --------------------------------------------------------------------------
# Password hashing
# --------------------------------------------------------------------------


def test_password_round_trips():
    stored = passwords.hash_password(TEST_PASSWORD, rounds=4)

    assert stored != TEST_PASSWORD
    assert passwords.verify_password(TEST_PASSWORD, stored)
    assert not passwords.verify_password(TEST_PASSWORD + "-wrong", stored)


def test_same_password_hashes_differently_each_time():
    """Distinct salts: two operators with the same password must not collide."""
    assert passwords.hash_password("same-password", 4) != passwords.hash_password("same-password", 4)


def test_passwords_longer_than_bcrypts_72_byte_limit_stay_distinct():
    """Without the SHA-256 fold, bcrypt would ignore everything past byte 72."""
    base = "x" * 80
    stored = passwords.hash_password(base + "-alpha", rounds=4)

    assert passwords.verify_password(base + "-alpha", stored)
    assert not passwords.verify_password(base + "-omega", stored)


def test_malformed_stored_hash_is_a_failed_login_not_a_crash():
    assert passwords.verify_password("anything", "not-a-bcrypt-hash") is False


# --------------------------------------------------------------------------
# Bearer header parsing
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "header",
    [None, "", "token-without-scheme", "Basic abc123", "Bearer", "Bearer   "],
)
def test_bearer_token_rejects_anything_that_is_not_a_bearer_header(header):
    assert bearer_token(header) is None


def test_bearer_token_is_case_insensitive_on_the_scheme():
    assert bearer_token("bearer abc123") == "abc123"


# --------------------------------------------------------------------------
# The gate
# --------------------------------------------------------------------------


def test_control_panel_rejects_requests_without_a_token():
    response = client.get("/api/v1/dashboard/summary")

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_control_panel_rejects_an_unknown_token(monkeypatch):
    monkeypatch.setattr("app.services.auth.resolve_session", AsyncMock(return_value=None))

    response = client.get(
        "/api/v1/dashboard/summary", headers={"Authorization": "Bearer made-up"}
    )

    assert response.status_code == 401


def test_unreachable_account_store_is_503_not_401(monkeypatch):
    """A database outage must not be reported as "wrong password"."""
    monkeypatch.setattr(
        "app.services.auth.resolve_session",
        AsyncMock(side_effect=AuthUnavailableError("connection refused")),
    )

    response = client.get("/api/v1/dashboard/summary", headers={"Authorization": "Bearer any"})

    assert response.status_code == 503


def test_valid_session_reaches_the_endpoint(monkeypatch, signed_in):
    monkeypatch.setattr(
        "app.services.dashboard.summary",
        AsyncMock(return_value={"window_hours": 24, "messages_processed": 0}),
    )

    response = client.get("/api/v1/dashboard/summary", headers={"Authorization": "Bearer ok"})

    assert response.status_code == 200
    assert response.json()["available"] is True


def test_every_control_panel_route_is_behind_the_gate():
    """A new endpoint on this router must not be able to forget the dependency."""
    guarded = [
        route
        for route in app.routes
        if getattr(route, "path", "").startswith(("/api/v1/dashboard", "/api/v1/system", "/api/v1/whatsapp"))
    ]

    assert guarded, "no Control Panel routes found — did the router move?"
    for route in guarded:
        names = {dependency.call.__name__ for dependency in route.dependant.dependencies}
        assert "require_operator" in names, f"{route.path} is unprotected"


# --------------------------------------------------------------------------
# Login
# --------------------------------------------------------------------------


def test_login_returns_a_token_and_the_operator(monkeypatch):
    expires = datetime.now(UTC) + timedelta(hours=8)
    monkeypatch.setattr("app.services.auth.authenticate", AsyncMock(return_value=OPERATOR))
    monkeypatch.setattr("app.services.auth.create_session", AsyncMock(return_value=("tok-123", expires)))

    body = client.post(
        "/api/v1/auth/login", json={"email": "ops@example.com", "password": TEST_PASSWORD}
    ).json()

    assert body["access_token"] == "tok-123"
    assert body["token_type"] == "bearer"
    assert body["operator"]["email"] == "ops@example.com"
    assert "password" not in str(body)


def test_login_rejects_bad_credentials_without_saying_which_part_was_wrong(monkeypatch):
    monkeypatch.setattr("app.services.auth.authenticate", AsyncMock(return_value=None))

    response = client.post(
        "/api/v1/auth/login", json={"email": "ops@example.com", "password": "wrong-password"}
    )

    assert response.status_code == 401
    # "Invalid email or password" — never "no such account" or "account disabled".
    assert response.json()["detail"] == "Invalid email or password"


def test_login_is_rate_limited(monkeypatch):
    from app.core.rate_limit import RateLimitResult

    monkeypatch.setattr(
        "app.api.v1.endpoints.auth.check_rate_limit",
        AsyncMock(return_value=RateLimitResult(allowed=False, current=6, limit=5, retry_after=300)),
    )
    authenticate = AsyncMock(return_value=OPERATOR)
    monkeypatch.setattr("app.services.auth.authenticate", authenticate)

    response = client.post(
        "/api/v1/auth/login", json={"email": "ops@example.com", "password": TEST_PASSWORD}
    )

    assert response.status_code == 429
    assert response.headers["Retry-After"] == "300"
    # Refused before the password is checked: a throttled attempt must not even
    # reach bcrypt, or the throttle becomes a way to measure hashing time.
    authenticate.assert_not_awaited()


def test_login_reports_503_when_the_account_store_is_down(monkeypatch):
    monkeypatch.setattr(
        "app.services.auth.authenticate", AsyncMock(side_effect=AuthUnavailableError("down"))
    )

    response = client.post(
        "/api/v1/auth/login", json={"email": "ops@example.com", "password": TEST_PASSWORD}
    )

    assert response.status_code == 503


def test_login_validates_the_request_shape():
    assert client.post("/api/v1/auth/login", json={"email": "not-an-email", "password": "x" * 10}).status_code == 422
    assert client.post("/api/v1/auth/login", json={"email": "ops@example.com", "password": "short"}).status_code == 422


def test_logout_revokes_the_presented_session(monkeypatch, signed_in):
    revoke = AsyncMock(return_value=True)
    monkeypatch.setattr("app.services.auth.revoke_session", revoke)

    response = client.post("/api/v1/auth/logout", headers={"Authorization": "Bearer tok-123"})

    assert response.status_code == 204
    revoke.assert_awaited_once()
    assert revoke.await_args.args[0] == "tok-123"


def test_me_returns_the_signed_in_operator(signed_in):
    body = client.get("/api/v1/auth/me", headers={"Authorization": "Bearer tok-123"}).json()

    assert body["email"] == "ops@example.com"
    assert body["full_name"] == "Operator Satu"


def test_logout_requires_a_session():
    assert client.post("/api/v1/auth/logout").status_code == 401


# --------------------------------------------------------------------------
# Change password
# --------------------------------------------------------------------------


def test_change_password_verifies_the_current_password_first(monkeypatch, signed_in):
    authenticate = AsyncMock(return_value=OPERATOR)
    set_password = AsyncMock(return_value=True)
    monkeypatch.setattr("app.services.auth.authenticate", authenticate)
    monkeypatch.setattr("app.services.auth.set_password", set_password)

    response = client.post(
        "/api/v1/auth/change-password",
        headers={"Authorization": "Bearer tok-123"},
        json={"current_password": "old-password", "new_password": "new-password-2026"},
    )

    assert response.status_code == 204
    authenticate.assert_awaited_once()
    assert authenticate.await_args.args[0] == OPERATOR.email
    assert authenticate.await_args.args[1] == "old-password"
    set_password.assert_awaited_once()
    assert set_password.await_args.args[0] == OPERATOR.email
    assert set_password.await_args.args[1] == "new-password-2026"


def test_change_password_rejects_a_wrong_current_password(monkeypatch, signed_in):
    monkeypatch.setattr("app.services.auth.authenticate", AsyncMock(return_value=None))
    set_password = AsyncMock()
    monkeypatch.setattr("app.services.auth.set_password", set_password)

    response = client.post(
        "/api/v1/auth/change-password",
        headers={"Authorization": "Bearer tok-123"},
        json={"current_password": "wrong-password", "new_password": "new-password-2026"},
    )

    assert response.status_code == 400
    set_password.assert_not_awaited()


def test_change_password_reports_503_when_the_account_store_is_down(monkeypatch, signed_in):
    monkeypatch.setattr(
        "app.services.auth.authenticate", AsyncMock(side_effect=AuthUnavailableError("down"))
    )

    response = client.post(
        "/api/v1/auth/change-password",
        headers={"Authorization": "Bearer tok-123"},
        json={"current_password": "old-password", "new_password": "new-password-2026"},
    )

    assert response.status_code == 503


def test_change_password_requires_a_session():
    response = client.post(
        "/api/v1/auth/change-password",
        json={"current_password": "old-password", "new_password": "new-password-2026"},
    )

    assert response.status_code == 401


def test_change_password_validates_the_request_shape(signed_in):
    response = client.post(
        "/api/v1/auth/change-password",
        headers={"Authorization": "Bearer tok-123"},
        json={"current_password": "old-password", "new_password": "short"},
    )

    assert response.status_code == 422
