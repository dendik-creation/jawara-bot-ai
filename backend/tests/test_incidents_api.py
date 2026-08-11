"""Incidents: state-machine guards, the code formatter, and routes."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.core.security import require_operator
from app.main import app
from app.services import incidents
from app.services.auth import Operator

client = TestClient(app)

OPERATOR = Operator(
    id="11111111-1111-1111-1111-111111111111",
    email="ops@example.com",
    full_name="Operator Satu",
    is_active=True,
)

INCIDENT_ID = "66666666-6666-6666-6666-666666666666"


@pytest.fixture(autouse=True)
def signed_in():
    app.dependency_overrides[require_operator] = lambda: OPERATOR
    yield
    app.dependency_overrides.pop(require_operator, None)


def _incident_result(**overrides: object) -> dict[str, object]:
    base = {
        "id": INCIDENT_ID,
        "code": "INC-2026-0001",
        "title": "Phishing Campaign",
        "severity": "CRITICAL",
        "state": "OPEN",
        "assigned_operator_id": None,
        "assigned_operator_name": None,
        "resolution_reason": None,
        "created_by": OPERATOR.id,
        "created_by_name": OPERATOR.full_name,
        "created_at": "2026-08-10T10:00:00+00:00",
        "updated_at": "2026-08-10T10:00:00+00:00",
        "message_count": 2,
        "affected_user_count": 1,
        "threats": [],
        "categories": [],
        "notes": [],
    }
    base.update(overrides)
    return base


# --------------------------------------------------------------------------
# Human-readable code
# --------------------------------------------------------------------------


def test_code_formats_sequence_and_year():
    assert incidents._code(1, datetime(2026, 8, 10, tzinfo=UTC)) == "INC-2026-0001"
    assert incidents._code(42, datetime(2026, 1, 1, tzinfo=UTC)) == "INC-2026-0042"


# --------------------------------------------------------------------------
# apply_incident_action guards — all raise before touching the database
# --------------------------------------------------------------------------


async def test_set_state_rejects_terminal_states():
    with pytest.raises(ValueError, match="use CLOSE"):
        await incidents.apply_incident_action(
            INCIDENT_ID, action="SET_STATE", state="RESOLVED", actor_operator_id=OPERATOR.id
        )


async def test_set_state_accepts_investigating():
    # No ValueError raised means the guard passed; a real DB call would
    # follow, which this unit test doesn't need to reach.
    try:
        await incidents.apply_incident_action(
            INCIDENT_ID, action="SET_STATE", state="INVESTIGATING", actor_operator_id=OPERATOR.id
        )
    except ValueError:
        pytest.fail("INVESTIGATING should be a valid SET_STATE target")
    except Exception:
        pass  # DB connection errors are fine here — only the guard is under test


async def test_close_requires_a_terminal_state():
    with pytest.raises(ValueError, match="RESOLVED or FALSE_POSITIVE"):
        await incidents.apply_incident_action(
            INCIDENT_ID, action="CLOSE", state="INVESTIGATING", reason="done", actor_operator_id=OPERATOR.id
        )


async def test_close_requires_a_reason():
    with pytest.raises(ValueError, match="requires a reason"):
        await incidents.apply_incident_action(
            INCIDENT_ID, action="CLOSE", state="RESOLVED", reason=None, actor_operator_id=OPERATOR.id
        )


async def test_set_severity_requires_a_value():
    with pytest.raises(ValueError, match="requires a severity"):
        await incidents.apply_incident_action(
            INCIDENT_ID, action="SET_SEVERITY", severity=None, actor_operator_id=OPERATOR.id
        )


# --------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------


def test_create_incident_rejects_non_threat_message(monkeypatch):
    monkeypatch.setattr(
        "app.services.incidents.create_incident",
        AsyncMock(side_effect=ValueError("99999999-9999-9999-9999-999999999999 is not a HIGH/MEDIUM threat")),
    )

    response = client.post(
        "/api/v1/incidents",
        json={
            "title": "Phishing Campaign",
            "severity": "CRITICAL",
            "message_log_ids": ["99999999-9999-9999-9999-999999999999"],
        },
    )

    assert response.status_code == 400


def test_create_incident_writes_audit_log(monkeypatch):
    monkeypatch.setattr(
        "app.services.incidents.create_incident", AsyncMock(return_value=_incident_result())
    )
    audit_mock = AsyncMock()
    monkeypatch.setattr("app.api.v1.endpoints.incidents.record_audit", audit_mock)

    response = client.post(
        "/api/v1/incidents",
        json={
            "title": "Phishing Campaign",
            "severity": "CRITICAL",
            "message_log_ids": ["22222222-2222-2222-2222-222222222222"],
        },
    )

    assert response.status_code == 201
    audit_mock.assert_awaited_once()
    assert audit_mock.await_args.kwargs["action"] == "incident.created"


def test_create_incident_rejects_empty_message_list():
    response = client.post(
        "/api/v1/incidents", json={"title": "Phishing Campaign", "severity": "CRITICAL", "message_log_ids": []}
    )
    assert response.status_code == 422


def test_get_incident_404s_when_missing(monkeypatch):
    monkeypatch.setattr("app.services.incidents.get_incident", AsyncMock(return_value=None))

    response = client.get(f"/api/v1/incidents/{INCIDENT_ID}")

    assert response.status_code == 404


def test_set_severity_audit_metadata_carries_old_and_new(monkeypatch):
    result = _incident_result(severity="HIGH")
    result["previous_severity"] = "CRITICAL"
    monkeypatch.setattr("app.services.incidents.apply_incident_action", AsyncMock(return_value=result))
    audit_mock = AsyncMock()
    monkeypatch.setattr("app.api.v1.endpoints.incidents.record_audit", audit_mock)

    response = client.patch(
        f"/api/v1/incidents/{INCIDENT_ID}", json={"action": "SET_SEVERITY", "severity": "HIGH"}
    )

    assert response.status_code == 200
    assert "previous_severity" not in response.json()
    metadata = audit_mock.await_args.kwargs["metadata"]
    assert metadata["old_severity"] == "CRITICAL"
    assert metadata["new_severity"] == "HIGH"


def test_close_without_reason_400s_via_service_guard(monkeypatch):
    monkeypatch.setattr(
        "app.services.incidents.apply_incident_action",
        AsyncMock(side_effect=ValueError("closing an incident requires a reason")),
    )

    response = client.patch(f"/api/v1/incidents/{INCIDENT_ID}", json={"action": "CLOSE", "state": "RESOLVED"})

    assert response.status_code == 400


def test_escalate_raises_a_matching_alert_sourced_from_the_incident(monkeypatch):
    monkeypatch.setattr("app.services.incidents.get_incident", AsyncMock(return_value=_incident_result()))
    create_alert_mock = AsyncMock(return_value={"id": "77777777-7777-7777-7777-777777777777"})
    monkeypatch.setattr(
        "app.api.v1.endpoints.incidents.alerts.create_from_incident_escalation", create_alert_mock
    )
    audit_mock = AsyncMock()
    monkeypatch.setattr("app.api.v1.endpoints.incidents.record_audit", audit_mock)

    response = client.patch(f"/api/v1/incidents/{INCIDENT_ID}", json={"action": "ESCALATE"})

    assert response.status_code == 200
    create_alert_mock.assert_awaited_once_with(INCIDENT_ID, severity="CRITICAL", title="Phishing Campaign")
    assert audit_mock.await_args.kwargs["metadata"]["alert_id"] == "77777777-7777-7777-7777-777777777777"


def test_add_threat_404s_when_incident_missing(monkeypatch):
    monkeypatch.setattr("app.services.incidents.add_threat_to_incident", AsyncMock(return_value=None))

    response = client.post(
        f"/api/v1/incidents/{INCIDENT_ID}/threats",
        json={"message_log_id": "22222222-2222-2222-2222-222222222222"},
    )

    assert response.status_code == 404


def test_add_threat_rejects_non_threat_message(monkeypatch):
    monkeypatch.setattr(
        "app.services.incidents.add_threat_to_incident",
        AsyncMock(side_effect=ValueError("99999999-9999-9999-9999-999999999999 is not a HIGH/MEDIUM threat")),
    )

    response = client.post(
        f"/api/v1/incidents/{INCIDENT_ID}/threats",
        json={"message_log_id": "99999999-9999-9999-9999-999999999999"},
    )

    assert response.status_code == 400


def test_remove_threat_404s_when_not_linked(monkeypatch):
    monkeypatch.setattr("app.services.incidents.remove_threat_from_incident", AsyncMock(return_value=None))

    response = client.delete(
        f"/api/v1/incidents/{INCIDENT_ID}/threats/22222222-2222-2222-2222-222222222222"
    )

    assert response.status_code == 404


def test_add_note_writes_audit_log(monkeypatch):
    result = _incident_result(
        notes=[
            {
                "id": "88888888-8888-8888-8888-888888888888",
                "note": "escalating to WAHA team",
                "at": "2026-08-10T10:05:00+00:00",
                "author_operator_id": OPERATOR.id,
                "author_name": OPERATOR.full_name,
            }
        ]
    )
    monkeypatch.setattr("app.services.incidents.add_note", AsyncMock(return_value=result))
    audit_mock = AsyncMock()
    monkeypatch.setattr("app.api.v1.endpoints.incidents.record_audit", audit_mock)

    response = client.post(f"/api/v1/incidents/{INCIDENT_ID}/notes", json={"note": "escalating to WAHA team"})

    assert response.status_code == 200
    assert len(response.json()["notes"]) == 1
    audit_mock.assert_awaited_once()
    assert audit_mock.await_args.kwargs["action"] == "incident.note_added"


def test_add_note_rejects_empty_note():
    response = client.post(f"/api/v1/incidents/{INCIDENT_ID}/notes", json={"note": ""})
    assert response.status_code == 422
