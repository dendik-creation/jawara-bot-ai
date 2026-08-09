"""Control Panel read APIs: privacy rules and honest empty states.

The access gate itself lives in `test_auth.py`; here it is satisfied once, in an
autouse fixture, so these assertions are about payloads rather than about 401s.
"""

from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.core.security import require_operator
from app.main import app
from app.services.auth import Operator

client = TestClient(app)

OPERATOR = Operator(
    id="11111111-1111-1111-1111-111111111111",
    email="ops@example.com",
    full_name="Operator Satu",
    is_active=True,
)

SUMMARY = {
    "window_hours": 24,
    "messages_processed": 12,
    "threats_detected": 3,
    "critical_threats": 1,
    "active_users": 4,
    "avg_response_latency_ms": 1800,
    "severity_breakdown": {"HIGH": 1, "MEDIUM": 2, "LOW": 9},
    "intent_breakdown": {"HEALTH_HOAX": 5},
}

ACTIVITY = [
    {
        "id": "1",
        "at": "2026-08-10T10:00:00+00:00",
        "event": "THREAT_DETECTED",
        "session": "default",
        "chat_type": "GROUP",
        "input_type": "URL_LINK",
        "intent": "PHISHING_LINK",
        "risk": "HIGH",
        "similarity_score": None,
        "latency_ms": 1500,
    }
]


@pytest.fixture(autouse=True)
def signed_in():
    """Satisfy the operator gate without a database.

    Overriding the dependency, not stubbing the session lookup: these tests are
    about what the endpoints return once someone is signed in.
    """
    app.dependency_overrides[require_operator] = lambda: OPERATOR
    yield
    app.dependency_overrides.pop(require_operator, None)


@pytest.fixture
def stub_queries(monkeypatch):
    monkeypatch.setattr("app.services.dashboard.summary", AsyncMock(return_value=SUMMARY))
    monkeypatch.setattr("app.services.dashboard.recent_activity", AsyncMock(return_value=ACTIVITY))
    monkeypatch.setattr("app.services.dashboard.recent_threats", AsyncMock(return_value=[]))


def test_summary_returns_command_center_metrics(stub_queries):
    body = client.get("/api/v1/dashboard/summary").json()

    assert body["available"] is True
    assert body["messages_processed"] == 12
    assert body["critical_threats"] == 1


def test_activity_feed_never_exposes_message_content(stub_queries):
    body = client.get("/api/v1/dashboard/activity").json()

    assert body["transport"] == "polling"
    assert "extracted_text" not in str(body)
    assert body["items"][0]["event"] == "THREAT_DETECTED"


def test_incidents_and_alerts_report_unavailable_rather_than_zero(stub_queries):
    body = client.get("/api/v1/dashboard/recent").json()

    # A zero would read as "a quiet day"; there is no incidents table at all.
    assert body["incidents"]["available"] is False
    assert body["incidents"]["reason"] == "incidents_table_not_implemented"
    assert body["alerts"]["available"] is False
    assert body["threats"]["available"] is True


def test_database_outage_reports_unavailable_instead_of_failing(monkeypatch):
    monkeypatch.setattr(
        "app.services.dashboard.summary", AsyncMock(side_effect=ConnectionError("db down"))
    )
    body = client.get("/api/v1/dashboard/summary").json()

    assert body["available"] is False
    assert body["reason"] == "database_unavailable"


def test_service_health_lists_every_dependency(monkeypatch):
    monkeypatch.setattr("app.api.v1.endpoints.dashboard.service_health", AsyncMock(
        return_value={"status": "degraded", "degraded": ["ml_service"], "services": {}}
    ))
    body = client.get("/api/v1/system/services").json()

    assert body["status"] == "degraded"
    assert "ml_service" in body["degraded"]


