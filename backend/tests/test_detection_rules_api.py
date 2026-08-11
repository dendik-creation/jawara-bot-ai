"""Detection Rules: condition validation per rule_type, lifecycle guards, and routes."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.core.security import require_operator
from app.main import app
from app.services import detection_rules
from app.services.auth import Operator
from app.services.detection_rules import _row_to_item, _validate_condition

client = TestClient(app)

OPERATOR = Operator(
    id="11111111-1111-1111-1111-111111111111",
    email="ops@example.com",
    full_name="Operator Satu",
    is_active=True,
)

RULE_ID = "44444444-4444-4444-4444-444444444444"


@pytest.fixture(autouse=True)
def signed_in():
    app.dependency_overrides[require_operator] = lambda: OPERATOR
    yield
    app.dependency_overrides.pop(require_operator, None)


def _row(**overrides: object) -> dict[str, object]:
    base = {
        "id": RULE_ID,
        "name": "Blokir domain penipuan",
        "rule_type": "DOMAIN",
        "condition": {"values": ["scam-bank.example"]},
        "severity": "HIGH",
        "status": "DRAFT",
        "created_by": OPERATOR.id,
        "created_by_name": OPERATOR.full_name,
        "created_at": datetime(2026, 8, 10, 10, 0, tzinfo=UTC),
        "updated_at": datetime(2026, 8, 10, 10, 0, tzinfo=UTC),
    }
    base.update(overrides)
    return base


# --------------------------------------------------------------------------
# `_validate_condition` — per rule_type shape, raises before touching the DB
# --------------------------------------------------------------------------


@pytest.mark.parametrize("rule_type", ["KEYWORD", "DOMAIN", "URL", "ALLOWLIST", "BLOCKLIST"])
def test_values_condition_requires_non_empty_list(rule_type):
    with pytest.raises(ValueError, match="values"):
        _validate_condition(rule_type, {})
    with pytest.raises(ValueError, match="non-empty"):
        _validate_condition(rule_type, {"values": []})
    _validate_condition(rule_type, {"values": ["x"]})  # does not raise


def test_risk_threshold_requires_int_in_range():
    with pytest.raises(ValueError, match="threshold"):
        _validate_condition("RISK_THRESHOLD", {})
    with pytest.raises(ValueError, match="between 0 and 100"):
        _validate_condition("RISK_THRESHOLD", {"threshold": 150})
    _validate_condition("RISK_THRESHOLD", {"threshold": 80})  # does not raise


def test_pattern_requires_non_empty_components():
    with pytest.raises(ValueError, match="components"):
        _validate_condition("PATTERN", {})
    _validate_condition("PATTERN", {"components": ["nomor_rekening", "urgensi", "tautan"]})


def test_repeated_offender_requires_occurrences_and_window():
    with pytest.raises(ValueError, match="occurrences"):
        _validate_condition("REPEATED_OFFENDER", {"window_hours": 24})
    with pytest.raises(ValueError, match="window_hours"):
        _validate_condition("REPEATED_OFFENDER", {"occurrences": 3})
    _validate_condition("REPEATED_OFFENDER", {"occurrences": 3, "window_hours": 24})


def test_rate_limit_requires_max_messages_and_window():
    with pytest.raises(ValueError, match="max_messages"):
        _validate_condition("RATE_LIMIT", {"window_minutes": 10})
    with pytest.raises(ValueError, match="window_minutes"):
        _validate_condition("RATE_LIMIT", {"max_messages": 20})
    _validate_condition("RATE_LIMIT", {"max_messages": 20, "window_minutes": 10})


def test_row_to_item_parses_jsonb_condition_string():
    row = _row(condition='{"values": ["scam-bank.example"]}')
    item = _row_to_item(row)
    assert item["condition"] == {"values": ["scam-bank.example"]}


# --------------------------------------------------------------------------
# `apply_rule_action` guards — all raise before touching the database
# --------------------------------------------------------------------------


async def test_update_with_no_fields_is_rejected_before_touching_the_database():
    with pytest.raises(ValueError, match="requires at least one"):
        await detection_rules.apply_rule_action(RULE_ID, action="UPDATE")


# --------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------


def test_list_detection_rules_route_returns_available_payload(monkeypatch):
    monkeypatch.setattr(
        "app.services.detection_rules.list_detection_rules",
        AsyncMock(return_value={"total": 1, "items": [_row_to_item(_row())]}),
    )

    body = client.get("/api/v1/detection-rules").json()

    assert body["available"] is True
    assert body["total"] == 1
    assert body["items"][0]["status"] == "DRAFT"


def test_list_detection_rules_route_reports_unavailable_on_db_outage(monkeypatch):
    monkeypatch.setattr(
        "app.services.detection_rules.list_detection_rules", AsyncMock(side_effect=ConnectionError("db down"))
    )

    body = client.get("/api/v1/detection-rules").json()

    assert body["available"] is False
    assert body["reason"] == "database_unavailable"


def test_create_detection_rule_writes_audit_log(monkeypatch):
    monkeypatch.setattr(
        "app.services.detection_rules.create_detection_rule", AsyncMock(return_value=_row_to_item(_row()))
    )
    audit_mock = AsyncMock()
    monkeypatch.setattr("app.api.v1.endpoints.detection_rules.record_audit", audit_mock)

    response = client.post(
        "/api/v1/detection-rules",
        json={
            "name": "Blokir domain penipuan",
            "rule_type": "DOMAIN",
            "condition": {"values": ["scam-bank.example"]},
            "severity": "HIGH",
        },
    )

    assert response.status_code == 201
    assert response.json()["status"] == "DRAFT"
    audit_mock.assert_awaited_once()
    assert audit_mock.await_args.kwargs["action"] == "detection_rule.created"


def test_create_detection_rule_rejects_bad_condition(monkeypatch):
    monkeypatch.setattr(
        "app.services.detection_rules.create_detection_rule",
        AsyncMock(side_effect=ValueError("DOMAIN condition requires 'values'")),
    )

    response = client.post(
        "/api/v1/detection-rules",
        json={"name": "Bad rule", "rule_type": "DOMAIN", "condition": {}, "severity": "HIGH"},
    )

    assert response.status_code == 400


def test_create_detection_rule_rejects_unknown_rule_type():
    response = client.post(
        "/api/v1/detection-rules",
        json={"name": "Bad rule", "rule_type": "NOT_A_TYPE", "condition": {}, "severity": "HIGH"},
    )
    assert response.status_code == 422


def test_action_on_detection_rule_activates_and_writes_audit_log(monkeypatch):
    activated = _row_to_item(_row(status="ACTIVE"))
    activated["previous_status"] = "DRAFT"
    monkeypatch.setattr("app.services.detection_rules.apply_rule_action", AsyncMock(return_value=activated))
    audit_mock = AsyncMock()
    monkeypatch.setattr("app.api.v1.endpoints.detection_rules.record_audit", audit_mock)

    response = client.patch(f"/api/v1/detection-rules/{RULE_ID}", json={"action": "ACTIVATE"})

    assert response.status_code == 200
    assert response.json()["status"] == "ACTIVE"
    assert "previous_status" not in response.json()
    metadata = audit_mock.await_args.kwargs["metadata"]
    assert metadata["previous_status"] == "DRAFT"
    assert metadata["new_status"] == "ACTIVE"
    assert audit_mock.await_args.kwargs["action"] == "detection_rule.status_changed"


def test_action_on_detection_rule_404s_when_missing(monkeypatch):
    monkeypatch.setattr("app.services.detection_rules.apply_rule_action", AsyncMock(return_value=None))

    response = client.patch(f"/api/v1/detection-rules/{RULE_ID}", json={"action": "ACTIVATE"})

    assert response.status_code == 404


def test_action_on_detection_rule_400s_on_invalid_transition(monkeypatch):
    monkeypatch.setattr(
        "app.services.detection_rules.apply_rule_action",
        AsyncMock(side_effect=ValueError("cannot ACTIVATE a rule in status ARCHIVED")),
    )

    response = client.patch(f"/api/v1/detection-rules/{RULE_ID}", json={"action": "ACTIVATE"})

    assert response.status_code == 400


def test_action_on_detection_rule_update_uses_updated_audit_action(monkeypatch):
    updated = _row_to_item(_row(name="Nama baru"))
    updated["previous_status"] = None
    monkeypatch.setattr("app.services.detection_rules.apply_rule_action", AsyncMock(return_value=updated))
    audit_mock = AsyncMock()
    monkeypatch.setattr("app.api.v1.endpoints.detection_rules.record_audit", audit_mock)

    response = client.patch(f"/api/v1/detection-rules/{RULE_ID}", json={"action": "UPDATE", "name": "Nama baru"})

    assert response.status_code == 200
    assert audit_mock.await_args.kwargs["action"] == "detection_rule.updated"


def test_action_on_detection_rule_rejects_unknown_action_value():
    response = client.patch(f"/api/v1/detection-rules/{RULE_ID}", json={"action": "DELETE_EVERYTHING"})
    assert response.status_code == 422
