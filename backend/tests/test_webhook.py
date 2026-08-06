from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import app

client = TestClient(app)
API_KEY = get_settings().waha_api_key


def test_webhook_rejects_missing_api_key():
    resp = client.post("/api/v1/webhook", json={"event": "message.any", "session": "default", "payload": {}})
    assert resp.status_code == 401


def test_webhook_rejects_wrong_api_key():
    resp = client.post(
        "/api/v1/webhook",
        json={"event": "message.any", "session": "default", "payload": {}},
        headers={"X-Api-Key": "wrong"},
    )
    assert resp.status_code == 401


def test_webhook_accepts_valid_payload():
    resp = client.post(
        "/api/v1/webhook",
        json={"event": "message.any", "session": "default", "payload": {"id": "abc", "body": "hi"}},
        headers={"X-Api-Key": API_KEY},
    )
    assert resp.status_code == 200
    assert resp.json() == {"status": "accepted"}


def test_webhook_rejects_malformed_payload():
    resp = client.post(
        "/api/v1/webhook",
        json={"session": "default"},
        headers={"X-Api-Key": API_KEY},
    )
    assert resp.status_code == 422


def test_session_status_accepts_valid_payload():
    resp = client.post(
        "/api/v1/session/status",
        json={"session": "default", "payload": {"status": "WORKING"}},
        headers={"X-Api-Key": API_KEY},
    )
    assert resp.status_code == 200
