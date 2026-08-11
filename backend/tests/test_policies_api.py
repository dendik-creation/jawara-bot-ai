"""Security Policies: condition validation per scope, lifecycle guards, and routes."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.core.security import require_operator
from app.main import app
from app.services import policies
from app.services.auth import Operator
from app.services.policies import _row_to_item, _validate_policy_condition

client = TestClient(app)

OPERATOR = Operator(
    id="11111111-1111-1111-1111-111111111111",
    email="ops@example.com",
    full_name="Operator Satu",
    is_active=True,
)

POLICY_ID = "55555555-5555-5555-5555-555555555555"


@pytest.fixture(autouse=True)
def signed_in():
    app.dependency_overrides[require_operator] = lambda: OPERATOR
    yield
    app.dependency_overrides.pop(require_operator, None)


def _row(**overrides: object) -> dict[str, object]:
    base = {
        "id": POLICY_ID,
        "name": "Blokir kategori scam risiko tinggi",
        "scope": "CATEGORY_THRESHOLD",
        "condition": {"threat_category": "SCAM", "threshold": 80},
        "action": "BLOCK",
        "priority": 100,
        "status": "DRAFT",
        "created_by": OPERATOR.id,
        "created_by_name": OPERATOR.full_name,
        "created_at": datetime(2026, 8, 11, 10, 0, tzinfo=UTC),
        "updated_at": datetime(2026, 8, 11, 10, 0, tzinfo=UTC),
    }
    base.update(overrides)
    return base


# --------------------------------------------------------------------------
# `_validate_policy_condition` — per scope shape, raises before touching the DB
# --------------------------------------------------------------------------


async def test_default_scope_requires_empty_condition():
    with pytest.raises(ValueError, match="must be empty"):
        await _validate_policy_condition("DEFAULT", {"threshold": 50}, conn=None)
    await _validate_policy_condition("DEFAULT", {}, conn=None)  # does not raise


async def test_category_threshold_requires_valid_category_and_range():
    with pytest.raises(ValueError, match="threat_category"):
        await _validate_policy_condition("CATEGORY_THRESHOLD", {"threshold": 80}, conn=None)
    with pytest.raises(ValueError, match="threshold"):
        await _validate_policy_condition("CATEGORY_THRESHOLD", {"threat_category": "SCAM"}, conn=None)
    with pytest.raises(ValueError, match="threat_category"):
        await _validate_policy_condition(
            "CATEGORY_THRESHOLD", {"threat_category": "NOT_A_CATEGORY", "threshold": 80}, conn=None
        )
    with pytest.raises(ValueError, match="between 0 and 100"):
        await _validate_policy_condition("CATEGORY_THRESHOLD", {"threat_category": "SCAM", "threshold": 150}, conn=None)
    await _validate_policy_condition(
        "CATEGORY_THRESHOLD", {"threat_category": "SCAM", "threshold": 80}, conn=None
    )  # does not raise


async def test_user_specific_requires_existing_user_hash():
    conn = AsyncMock()
    conn.fetchval.return_value = None
    with pytest.raises(ValueError, match="no user found"):
        await _validate_policy_condition("USER_SPECIFIC", {"user_hash": "unknown"}, conn=conn)

    conn.fetchval.return_value = 1
    await _validate_policy_condition("USER_SPECIFIC", {"user_hash": "known"}, conn=conn)  # does not raise


async def test_user_specific_requires_non_empty_string():
    with pytest.raises(ValueError, match="user_hash"):
        await _validate_policy_condition("USER_SPECIFIC", {}, conn=None)
    with pytest.raises(ValueError, match="non-empty string"):
        await _validate_policy_condition("USER_SPECIFIC", {"user_hash": ""}, conn=None)


def test_row_to_item_parses_jsonb_condition_string():
    row = _row(condition='{"threat_category": "SCAM", "threshold": 80}')
    item = _row_to_item(row)
    assert item["condition"] == {"threat_category": "SCAM", "threshold": 80}


# --------------------------------------------------------------------------
# `apply_policy_action` guards — all raise before touching the database
# --------------------------------------------------------------------------


async def test_update_with_no_fields_is_rejected_before_touching_the_database():
    with pytest.raises(ValueError, match="requires at least one"):
        await policies.apply_policy_action(POLICY_ID, operation="UPDATE")


# --------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------


def test_list_policies_route_returns_available_payload(monkeypatch):
    monkeypatch.setattr(
        "app.services.policies.list_policies",
        AsyncMock(return_value={"total": 1, "items": [_row_to_item(_row())]}),
    )

    body = client.get("/api/v1/policies").json()

    assert body["available"] is True
    assert body["total"] == 1
    assert body["items"][0]["status"] == "DRAFT"


def test_list_policies_route_reports_unavailable_on_db_outage(monkeypatch):
    monkeypatch.setattr("app.services.policies.list_policies", AsyncMock(side_effect=ConnectionError("db down")))

    body = client.get("/api/v1/policies").json()

    assert body["available"] is False
    assert body["reason"] == "database_unavailable"


def test_create_policy_writes_audit_log(monkeypatch):
    monkeypatch.setattr("app.services.policies.create_policy", AsyncMock(return_value=_row_to_item(_row())))
    audit_mock = AsyncMock()
    monkeypatch.setattr("app.api.v1.endpoints.policies.record_audit", audit_mock)

    response = client.post(
        "/api/v1/policies",
        json={
            "name": "Blokir kategori scam risiko tinggi",
            "scope": "CATEGORY_THRESHOLD",
            "condition": {"threat_category": "SCAM", "threshold": 80},
            "action": "BLOCK",
        },
    )

    assert response.status_code == 201
    assert response.json()["status"] == "DRAFT"
    audit_mock.assert_awaited_once()
    assert audit_mock.await_args.kwargs["action"] == "policy.created"


def test_create_policy_rejects_bad_condition(monkeypatch):
    monkeypatch.setattr(
        "app.services.policies.create_policy",
        AsyncMock(side_effect=ValueError("CATEGORY_THRESHOLD condition requires 'threshold'")),
    )

    response = client.post(
        "/api/v1/policies",
        json={"name": "Bad policy", "scope": "CATEGORY_THRESHOLD", "condition": {}, "action": "BLOCK"},
    )

    assert response.status_code == 400


def test_create_policy_rejects_unknown_scope():
    response = client.post(
        "/api/v1/policies",
        json={"name": "Bad policy", "scope": "NOT_A_SCOPE", "condition": {}, "action": "BLOCK"},
    )
    assert response.status_code == 422


def test_action_on_policy_activates_and_writes_audit_log(monkeypatch):
    activated = _row_to_item(_row(status="ACTIVE"))
    activated["previous_status"] = "DRAFT"
    monkeypatch.setattr("app.services.policies.apply_policy_action", AsyncMock(return_value=activated))
    audit_mock = AsyncMock()
    monkeypatch.setattr("app.api.v1.endpoints.policies.record_audit", audit_mock)

    response = client.patch(f"/api/v1/policies/{POLICY_ID}", json={"operation": "ACTIVATE"})

    assert response.status_code == 200
    assert response.json()["status"] == "ACTIVE"
    assert "previous_status" not in response.json()
    metadata = audit_mock.await_args.kwargs["metadata"]
    assert metadata["previous_status"] == "DRAFT"
    assert metadata["new_status"] == "ACTIVE"
    assert audit_mock.await_args.kwargs["action"] == "policy.status_changed"


def test_action_on_policy_404s_when_missing(monkeypatch):
    monkeypatch.setattr("app.services.policies.apply_policy_action", AsyncMock(return_value=None))

    response = client.patch(f"/api/v1/policies/{POLICY_ID}", json={"operation": "ACTIVATE"})

    assert response.status_code == 404


def test_action_on_policy_400s_on_invalid_transition(monkeypatch):
    monkeypatch.setattr(
        "app.services.policies.apply_policy_action",
        AsyncMock(side_effect=ValueError("cannot ACTIVATE a policy in status ARCHIVED")),
    )

    response = client.patch(f"/api/v1/policies/{POLICY_ID}", json={"operation": "ACTIVATE"})

    assert response.status_code == 400


def test_action_on_policy_400s_when_another_default_is_active(monkeypatch):
    monkeypatch.setattr(
        "app.services.policies.apply_policy_action",
        AsyncMock(side_effect=ValueError("another DEFAULT policy is already ACTIVE")),
    )

    response = client.patch(f"/api/v1/policies/{POLICY_ID}", json={"operation": "ACTIVATE"})

    assert response.status_code == 400


def test_action_on_policy_update_uses_updated_audit_action(monkeypatch):
    updated = _row_to_item(_row(name="Nama baru"))
    updated["previous_status"] = None
    monkeypatch.setattr("app.services.policies.apply_policy_action", AsyncMock(return_value=updated))
    audit_mock = AsyncMock()
    monkeypatch.setattr("app.api.v1.endpoints.policies.record_audit", audit_mock)

    response = client.patch(f"/api/v1/policies/{POLICY_ID}", json={"operation": "UPDATE", "name": "Nama baru"})

    assert response.status_code == 200
    assert audit_mock.await_args.kwargs["action"] == "policy.updated"


def test_action_on_policy_rejects_unknown_operation_value():
    response = client.patch(f"/api/v1/policies/{POLICY_ID}", json={"operation": "DELETE_EVERYTHING"})
    assert response.status_code == 422
