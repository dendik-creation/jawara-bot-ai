"""Alerts: the RESOLVE-requires-a-reason rule, severity mapping, and routes."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.core.security import require_operator
from app.main import app
from app.services import alerts
from app.services.alerts import _row_to_item
from app.services.auth import Operator

client = TestClient(app)

OPERATOR = Operator(
    id="11111111-1111-1111-1111-111111111111",
    email="ops@example.com",
    full_name="Operator Satu",
    is_active=True,
)


@pytest.fixture(autouse=True)
def signed_in():
    app.dependency_overrides[require_operator] = lambda: OPERATOR
    yield
    app.dependency_overrides.pop(require_operator, None)


def _row(**overrides: object) -> dict[str, object]:
    base = {
        "id": "33333333-3333-3333-3333-333333333333",
        "severity": "CRITICAL",
        "title": "Threat escalated: PHISHING (HIGH)",
        "source": "threat_escalation",
        "source_threat_id": "22222222-2222-2222-2222-222222222222",
        "source_incident_id": None,
        "state": "NEW",
        "assigned_operator_id": None,
        "assigned_operator_name": None,
        "resolution_reason": None,
        "created_at": datetime(2026, 8, 10, 10, 0, tzinfo=UTC),
        "updated_at": datetime(2026, 8, 10, 10, 0, tzinfo=UTC),
    }
    base.update(overrides)
    return base


# --------------------------------------------------------------------------
# Severity mapping for the one wired source
# --------------------------------------------------------------------------


def test_escalated_high_risk_threat_maps_to_critical_severity():
    assert alerts._SEVERITY_FROM_RISK["HIGH"] == "CRITICAL"


def test_escalated_medium_risk_threat_maps_to_high_severity():
    assert alerts._SEVERITY_FROM_RISK["MEDIUM"] == "HIGH"


def test_row_to_item_maps_fields():
    item = _row_to_item(_row())
    assert item["severity"] == "CRITICAL"
    assert item["source"] == "threat_escalation"
    assert item["source_threat_id"] == "22222222-2222-2222-2222-222222222222"
    assert item["source_incident_id"] is None


def test_row_to_item_maps_incident_source():
    item = _row_to_item(
        _row(
            source="incident_escalation",
            source_threat_id=None,
            source_incident_id="55555555-5555-5555-5555-555555555555",
        )
    )
    assert item["source"] == "incident_escalation"
    assert item["source_threat_id"] is None
    assert item["source_incident_id"] == "55555555-5555-5555-5555-555555555555"


# --------------------------------------------------------------------------
# RESOLVE requires a reason — the one hard rule §4 states
# --------------------------------------------------------------------------


async def test_resolve_without_reason_is_rejected_before_touching_the_database():
    # Raises before `_connect` is ever called — no DB needed for this test.
    with pytest.raises(ValueError, match="requires a reason"):
        await alerts.apply_alert_action(
            "33333333-3333-3333-3333-333333333333",
            action="RESOLVE",
            reason=None,
            actor_operator_id=OPERATOR.id,
        )


# --------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------


def test_list_alerts_route_returns_available_payload(monkeypatch):
    monkeypatch.setattr(
        "app.services.alerts.list_alerts",
        AsyncMock(return_value={"total": 1, "items": [_row_to_item(_row())]}),
    )

    body = client.get("/api/v1/alerts").json()

    assert body["available"] is True
    assert body["total"] == 1
    assert body["items"][0]["state"] == "NEW"


def test_list_alerts_route_reports_unavailable_on_db_outage(monkeypatch):
    monkeypatch.setattr(
        "app.services.alerts.list_alerts", AsyncMock(side_effect=ConnectionError("db down"))
    )

    body = client.get("/api/v1/alerts").json()

    assert body["available"] is False
    assert body["reason"] == "database_unavailable"


def test_action_on_alert_writes_audit_log(monkeypatch):
    acknowledged = _row_to_item(_row(state="ACKNOWLEDGED"))
    monkeypatch.setattr("app.services.alerts.apply_alert_action", AsyncMock(return_value=acknowledged))
    audit_mock = AsyncMock()
    monkeypatch.setattr("app.api.v1.endpoints.alerts.record_audit", audit_mock)

    response = client.patch(
        "/api/v1/alerts/33333333-3333-3333-3333-333333333333", json={"action": "ACKNOWLEDGE"}
    )

    assert response.status_code == 200
    assert response.json()["state"] == "ACKNOWLEDGED"
    audit_mock.assert_awaited_once()
    assert audit_mock.await_args.kwargs["action"] == "alert.action_taken"
    assert audit_mock.await_args.kwargs["target_type"] == "alert"


def test_action_on_alert_404s_when_not_found(monkeypatch):
    monkeypatch.setattr("app.services.alerts.apply_alert_action", AsyncMock(return_value=None))

    response = client.patch(
        "/api/v1/alerts/33333333-3333-3333-3333-333333333333", json={"action": "ACKNOWLEDGE"}
    )

    assert response.status_code == 404


def test_action_on_alert_400s_when_service_rejects_missing_reason(monkeypatch):
    monkeypatch.setattr(
        "app.services.alerts.apply_alert_action",
        AsyncMock(side_effect=ValueError("resolving an alert requires a reason")),
    )

    response = client.patch(
        "/api/v1/alerts/33333333-3333-3333-3333-333333333333", json={"action": "RESOLVE"}
    )

    assert response.status_code == 400


def test_action_on_alert_rejects_unknown_action_value():
    response = client.patch(
        "/api/v1/alerts/33333333-3333-3333-3333-333333333333", json={"action": "DELETE_EVERYTHING"}
    )

    assert response.status_code == 422
