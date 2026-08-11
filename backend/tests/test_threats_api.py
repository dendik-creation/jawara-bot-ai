"""Threats: state derivation, category-filter mapping, and the resolve endpoint.

`app.services.threats.list_threats` short-circuits for `state=DETECTED|ACTIONED`
without touching the database — those tests call the service directly rather
than mocking a connection, since there is nothing to mock.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.core.security import require_operator
from app.main import app
from app.pipeline.threat_categories import ThreatCategory
from app.services import threats
from app.services.auth import Operator
from app.services.threats import _row_to_item, categories_for_threat

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
        "message_log_id": "22222222-2222-2222-2222-222222222222",
        "created_at": datetime(2026, 8, 10, 10, 0, tzinfo=UTC),
        "waha_session_id": "default",
        "chat_type": "GROUP",
        "user_hash": "abc123",
        "detected_intent": "PHISHING_LINK",
        "risk_score": "HIGH",
        "similarity_score": 0.9,
        "action": None,
        "notes": None,
        "actor_operator_id": None,
        "actor_name": None,
        "action_at": None,
    }
    base.update(overrides)
    return base


# --------------------------------------------------------------------------
# State derivation — never stored, always computed from row presence
# --------------------------------------------------------------------------


def test_open_threat_has_no_action_row_and_reads_as_analyzed():
    item = _row_to_item(_row())

    assert item["state"] == "ANALYZED"
    assert item["action"] is None
    assert item["action_by"] is None


def test_resolved_threat_has_an_action_row_and_reads_as_resolved():
    item = _row_to_item(
        _row(
            action="BLOCK",
            actor_operator_id=OPERATOR.id,
            actor_name=OPERATOR.full_name,
            action_at=datetime(2026, 8, 10, 11, 0, tzinfo=UTC),
            notes="confirmed phishing",
        )
    )

    assert item["state"] == "RESOLVED"
    assert item["action"] == "BLOCK"
    assert item["action_by"] == OPERATOR.full_name
    assert item["notes"] == "confirmed phishing"


def test_threat_category_is_mapped_from_pipeline_intent():
    item = _row_to_item(_row(detected_intent="PHISHING_LINK"))
    assert item["threat_category"] == "PHISHING"


# --------------------------------------------------------------------------
# Category filter — must push into SQL, not filter after pagination
# --------------------------------------------------------------------------


def test_categories_for_threat_maps_known_pipeline_category():
    assert categories_for_threat(ThreatCategory.PHISHING) == ["PHISHING_LINK"]


def test_categories_for_threat_is_empty_for_categories_no_pipeline_output_reaches():
    # No `Category` produces these today (threat_categories.py docstring) —
    # an empty list, not a guess, is the honest answer.
    assert categories_for_threat(ThreatCategory.SOCIAL_ENGINEERING) == []


async def test_list_threats_short_circuits_for_unreachable_states():
    # DETECTED/ACTIONED require pipeline stages that don't exist yet — this
    # must return an honest empty page without ever opening a connection.
    detected = await threats.list_threats(state="DETECTED")
    actioned = await threats.list_threats(state="ACTIONED")

    assert detected == {"total": 0, "items": []}
    assert actioned == {"total": 0, "items": []}


async def test_list_threats_short_circuits_for_unreachable_category():
    result = await threats.list_threats(category=ThreatCategory.IMPERSONATION)
    assert result == {"total": 0, "items": []}


# --------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------


def test_list_threats_route_returns_available_payload(monkeypatch):
    monkeypatch.setattr(
        "app.services.threats.list_threats",
        AsyncMock(return_value={"total": 1, "items": [_row_to_item(_row())]}),
    )

    body = client.get("/api/v1/threats").json()

    assert body["available"] is True
    assert body["total"] == 1
    assert body["items"][0]["state"] == "ANALYZED"


def test_list_threats_route_reports_unavailable_on_db_outage(monkeypatch):
    monkeypatch.setattr(
        "app.services.threats.list_threats", AsyncMock(side_effect=ConnectionError("db down"))
    )

    body = client.get("/api/v1/threats").json()

    assert body["available"] is False
    assert body["reason"] == "database_unavailable"


def test_action_on_threat_writes_audit_log_and_strips_internal_field(monkeypatch):
    resolved = _row_to_item(_row(action="BLOCK", actor_operator_id=OPERATOR.id, actor_name=OPERATOR.full_name))
    resolved["previous_action"] = None
    monkeypatch.setattr("app.services.threats.action_on_threat", AsyncMock(return_value=resolved))
    audit_mock = AsyncMock()
    monkeypatch.setattr("app.api.v1.endpoints.threats.record_audit", audit_mock)

    response = client.patch(
        "/api/v1/threats/22222222-2222-2222-2222-222222222222",
        json={"action": "BLOCK", "notes": "handled per policy"},
    )

    assert response.status_code == 200
    assert "previous_action" not in response.json()
    audit_mock.assert_awaited_once()
    assert audit_mock.await_args.kwargs["action"] == "threat.action_taken"
    assert audit_mock.await_args.kwargs["target_type"] == "threat"
    # BLOCK does not raise an alert — only ESCALATE does (see test below).
    assert audit_mock.await_args.kwargs["metadata"]["alert_id"] is None


def test_escalate_action_raises_a_matching_alert(monkeypatch):
    resolved = _row_to_item(
        _row(action="ESCALATE", actor_operator_id=OPERATOR.id, actor_name=OPERATOR.full_name)
    )
    resolved["previous_action"] = None
    monkeypatch.setattr("app.services.threats.action_on_threat", AsyncMock(return_value=resolved))
    create_alert_mock = AsyncMock(return_value={"id": "44444444-4444-4444-4444-444444444444"})
    monkeypatch.setattr("app.api.v1.endpoints.threats.alerts.create_from_threat_escalation", create_alert_mock)
    audit_mock = AsyncMock()
    monkeypatch.setattr("app.api.v1.endpoints.threats.record_audit", audit_mock)

    response = client.patch(
        "/api/v1/threats/22222222-2222-2222-2222-222222222222",
        json={"action": "ESCALATE", "notes": "handing to incident review"},
    )

    assert response.status_code == 200
    create_alert_mock.assert_awaited_once_with(
        "22222222-2222-2222-2222-222222222222", risk=resolved["risk"], threat_category=resolved["threat_category"]
    )
    assert audit_mock.await_args.kwargs["metadata"]["alert_id"] == "44444444-4444-4444-4444-444444444444"


def test_confirm_action_records_operator_feedback(monkeypatch):
    resolved = _row_to_item(_row(action="CONFIRM", actor_operator_id=OPERATOR.id, actor_name=OPERATOR.full_name))
    resolved["previous_action"] = None
    monkeypatch.setattr("app.services.threats.action_on_threat", AsyncMock(return_value=resolved))
    monkeypatch.setattr("app.api.v1.endpoints.threats.record_audit", AsyncMock())
    feedback_mock = AsyncMock()
    monkeypatch.setattr("app.api.v1.endpoints.threats.feedback.record_feedback", feedback_mock)

    response = client.patch(
        "/api/v1/threats/22222222-2222-2222-2222-222222222222",
        json={"action": "CONFIRM", "notes": "memang phishing"},
    )

    assert response.status_code == 200
    feedback_mock.assert_awaited_once_with(
        "22222222-2222-2222-2222-222222222222", "CONFIRM", OPERATOR.id, reason="memang phishing"
    )


def test_false_positive_action_records_operator_feedback(monkeypatch):
    resolved = _row_to_item(
        _row(action="FALSE_POSITIVE", actor_operator_id=OPERATOR.id, actor_name=OPERATOR.full_name)
    )
    resolved["previous_action"] = None
    monkeypatch.setattr("app.services.threats.action_on_threat", AsyncMock(return_value=resolved))
    monkeypatch.setattr("app.api.v1.endpoints.threats.record_audit", AsyncMock())
    feedback_mock = AsyncMock()
    monkeypatch.setattr("app.api.v1.endpoints.threats.feedback.record_feedback", feedback_mock)

    response = client.patch(
        "/api/v1/threats/22222222-2222-2222-2222-222222222222",
        json={"action": "FALSE_POSITIVE"},
    )

    assert response.status_code == 200
    feedback_mock.assert_awaited_once()


def test_block_action_does_not_record_operator_feedback(monkeypatch):
    resolved = _row_to_item(_row(action="BLOCK", actor_operator_id=OPERATOR.id, actor_name=OPERATOR.full_name))
    resolved["previous_action"] = None
    monkeypatch.setattr("app.services.threats.action_on_threat", AsyncMock(return_value=resolved))
    monkeypatch.setattr("app.api.v1.endpoints.threats.record_audit", AsyncMock())
    feedback_mock = AsyncMock()
    monkeypatch.setattr("app.api.v1.endpoints.threats.feedback.record_feedback", feedback_mock)

    response = client.patch(
        "/api/v1/threats/22222222-2222-2222-2222-222222222222",
        json={"action": "BLOCK"},
    )

    assert response.status_code == 200
    feedback_mock.assert_not_awaited()


def test_action_on_threat_404s_when_not_a_threat(monkeypatch):
    monkeypatch.setattr("app.services.threats.action_on_threat", AsyncMock(return_value=None))

    response = client.patch(
        "/api/v1/threats/22222222-2222-2222-2222-222222222222",
        json={"action": "ALLOW"},
    )

    assert response.status_code == 404


def test_action_on_threat_rejects_unknown_action_value():
    response = client.patch(
        "/api/v1/threats/22222222-2222-2222-2222-222222222222",
        json={"action": "DELETE_EVERYTHING"},
    )

    assert response.status_code == 422
