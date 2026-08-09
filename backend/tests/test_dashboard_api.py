"""Control Panel read APIs: privacy rules, honest empty states, access gate."""

from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

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


def test_dashboard_key_is_enforced_when_configured(monkeypatch, stub_queries):
    from app.core.config import Settings, get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("DASHBOARD_API_KEY", "panel-secret")
    assert Settings().dashboard_api_key == "panel-secret"

    try:
        assert client.get("/api/v1/dashboard/summary").status_code == 401
        assert (
            client.get("/api/v1/dashboard/summary", headers={"X-Dashboard-Key": "panel-secret"}).status_code
            == 200
        )
    finally:
        get_settings.cache_clear()
