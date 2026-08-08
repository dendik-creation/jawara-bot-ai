from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.rate_limit import RateLimitResult
from app.main import app

client = TestClient(app)
API_KEY = get_settings().waha_api_key

EVENT = {
    "event": "message.any",
    "session": "default",
    "payload": {"id": "abc", "from": "628111@c.us", "body": "hi"},
}


@pytest.fixture(autouse=True)
def stub_pipeline(monkeypatch):
    """Keep unit tests off the real Redis broker/limiter."""
    enqueue = AsyncMock()
    monkeypatch.setattr("app.api.v1.endpoints.webhook.enqueue_message", enqueue)
    monkeypatch.setattr("app.api.v1.endpoints.webhook.get_redis", lambda: object())
    monkeypatch.setattr(
        "app.api.v1.endpoints.webhook.check_rate_limit",
        AsyncMock(return_value=RateLimitResult(allowed=True, current=1, limit=20, retry_after=60)),
    )
    return enqueue


def test_webhook_rejects_missing_api_key(stub_pipeline):
    resp = client.post("/api/v1/webhook", json=EVENT)
    assert resp.status_code == 401
    stub_pipeline.assert_not_awaited()


def test_webhook_rejects_wrong_api_key(stub_pipeline):
    resp = client.post("/api/v1/webhook", json=EVENT, headers={"X-Api-Key": "wrong"})
    assert resp.status_code == 401
    stub_pipeline.assert_not_awaited()


def test_webhook_accepts_valid_payload_and_enqueues(stub_pipeline):
    resp = client.post("/api/v1/webhook", json=EVENT, headers={"X-Api-Key": API_KEY})
    assert resp.status_code == 200
    assert resp.json() == {"status": "accepted"}
    assert resp.headers["X-Queued"] == "1"
    stub_pipeline.assert_awaited_once()


def test_webhook_rejects_malformed_payload(stub_pipeline):
    resp = client.post("/api/v1/webhook", json={"session": "default"}, headers={"X-Api-Key": API_KEY})
    assert resp.status_code == 422
    stub_pipeline.assert_not_awaited()


def test_webhook_returns_429_over_rate_limit(monkeypatch, stub_pipeline):
    monkeypatch.setattr(
        "app.api.v1.endpoints.webhook.check_rate_limit",
        AsyncMock(return_value=RateLimitResult(allowed=False, current=21, limit=20, retry_after=60)),
    )
    resp = client.post("/api/v1/webhook", json=EVENT, headers={"X-Api-Key": API_KEY})
    assert resp.status_code == 429
    assert resp.headers["Retry-After"] == "60"
    stub_pipeline.assert_not_awaited()


def test_webhook_still_acks_when_enqueue_fails(monkeypatch):
    monkeypatch.setattr(
        "app.api.v1.endpoints.webhook.enqueue_message",
        AsyncMock(side_effect=ConnectionError("broker down")),
    )
    resp = client.post("/api/v1/webhook", json=EVENT, headers={"X-Api-Key": API_KEY})
    assert resp.status_code == 200
    assert resp.headers["X-Queued"] == "0"


def test_session_status_accepts_valid_payload():
    resp = client.post(
        "/api/v1/session/status",
        json={"session": "default", "payload": {"status": "WORKING"}},
        headers={"X-Api-Key": API_KEY},
    )
    assert resp.status_code == 200
