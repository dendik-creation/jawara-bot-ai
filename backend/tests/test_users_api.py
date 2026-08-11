"""Users & Risk: the v1 risk-score formula, tier derivation, and routes."""

from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.core.security import require_operator
from app.main import app
from app.services import users
from app.services.auth import Operator
from app.services.users import _tier_from_rank, compute_risk_score

client = TestClient(app)

OPERATOR = Operator(
    id="11111111-1111-1111-1111-111111111111",
    email="ops@example.com",
    full_name="Operator Satu",
    is_active=True,
)

USER_HASH = "a" * 64


@pytest.fixture(autouse=True)
def signed_in():
    app.dependency_overrides[require_operator] = lambda: OPERATOR
    yield
    app.dependency_overrides.pop(require_operator, None)


def _user_result(**overrides: object) -> dict[str, object]:
    base = {
        "user_hash": USER_HASH,
        "chat_type": "GROUP",
        "is_active": True,
        "subscribed_at": "2026-08-01T00:00:00+00:00",
        "threat_count": 3,
        "tier": "HIGH",
        "score": 40,
        "last_seen": "2026-08-10T10:00:00+00:00",
        "blocked": False,
        "block_reason": None,
        "blocked_by": None,
        "blocked_by_name": None,
        "blocked_at": None,
        "dominant_category": "OTHER",
        "recent_threats": [],
    }
    base.update(overrides)
    return base


# --------------------------------------------------------------------------
# compute_risk_score — JAWARA's own v1 default
# --------------------------------------------------------------------------


def test_no_threats_scores_zero():
    assert compute_risk_score(0, None, ever_blocked=False) == 0


def test_medium_only_threats_score_from_frequency_and_severity():
    assert compute_risk_score(3, "MEDIUM", ever_blocked=False) == 3 * 5 + 15


def test_high_severity_outweighs_medium():
    assert compute_risk_score(1, "HIGH", ever_blocked=False) == 5 + 30


def test_block_history_adds_a_flat_bonus():
    without_block = compute_risk_score(2, "HIGH", ever_blocked=False)
    with_block = compute_risk_score(2, "HIGH", ever_blocked=True)
    assert with_block == without_block + 20


def test_score_is_clamped_at_100():
    assert compute_risk_score(50, "HIGH", ever_blocked=True) == 100


def test_frequency_bonus_is_capped_at_ten_threats():
    assert compute_risk_score(10, None, ever_blocked=False) == compute_risk_score(999, None, ever_blocked=False)


# --------------------------------------------------------------------------
# tier — pure function of the SQL severity_rank aggregate
# --------------------------------------------------------------------------


def test_tier_from_rank():
    assert _tier_from_rank(1) == "HIGH"
    assert _tier_from_rank(2) == "MEDIUM"
    assert _tier_from_rank(None) == "NONE"


# --------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------


def test_list_users_route_returns_available_payload(monkeypatch):
    monkeypatch.setattr(
        "app.services.users.list_users", AsyncMock(return_value={"total": 1, "items": [_user_result()]})
    )

    body = client.get("/api/v1/users").json()

    assert body["available"] is True
    assert body["items"][0]["tier"] == "HIGH"


def test_list_users_route_reports_unavailable_on_db_outage(monkeypatch):
    monkeypatch.setattr("app.services.users.list_users", AsyncMock(side_effect=ConnectionError("db down")))

    body = client.get("/api/v1/users").json()

    assert body["available"] is False
    assert body["reason"] == "database_unavailable"


def test_get_user_404s_when_missing(monkeypatch):
    monkeypatch.setattr("app.services.users.get_user", AsyncMock(return_value=None))

    response = client.get(f"/api/v1/users/{USER_HASH}")

    assert response.status_code == 404


def test_action_requires_a_reason_via_schema_not_service():
    # 422 from Pydantic (min_length=1) — the service is never called.
    response = client.patch(f"/api/v1/users/{USER_HASH}", json={"action": "BLOCK", "reason": ""})
    assert response.status_code == 422

    response = client.patch(f"/api/v1/users/{USER_HASH}", json={"action": "BLOCK"})
    assert response.status_code == 422


def test_unblock_also_requires_a_reason():
    response = client.patch(f"/api/v1/users/{USER_HASH}", json={"action": "UNBLOCK"})
    assert response.status_code == 422


def test_block_action_writes_audit_log(monkeypatch):
    result = _user_result(blocked=True, block_reason="repeated phishing", blocked_by_name=OPERATOR.full_name)
    result["previous_blocked"] = False
    monkeypatch.setattr("app.services.users.apply_user_action", AsyncMock(return_value=result))
    audit_mock = AsyncMock()
    monkeypatch.setattr("app.api.v1.endpoints.users.record_audit", audit_mock)

    response = client.patch(
        f"/api/v1/users/{USER_HASH}", json={"action": "BLOCK", "reason": "repeated phishing"}
    )

    assert response.status_code == 200
    assert "previous_blocked" not in response.json()
    assert response.json()["blocked"] is True
    audit_mock.assert_awaited_once()
    assert audit_mock.await_args.kwargs["action"] == "user.block_changed"
    assert audit_mock.await_args.kwargs["target_type"] == "user"
    assert audit_mock.await_args.kwargs["metadata"]["previous_blocked"] is False


def test_action_404s_when_user_missing(monkeypatch):
    monkeypatch.setattr("app.services.users.apply_user_action", AsyncMock(return_value=None))

    response = client.patch(f"/api/v1/users/{USER_HASH}", json={"action": "BLOCK", "reason": "test"})

    assert response.status_code == 404
