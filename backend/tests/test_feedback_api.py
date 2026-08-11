"""Operator Feedback: list route only — creation is a side effect of Threats' PATCH route."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.core.security import require_operator
from app.main import app
from app.services.auth import Operator
from app.services.feedback import _row_to_item

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
        "id": "77777777-7777-7777-7777-777777777777",
        "message_log_id": "22222222-2222-2222-2222-222222222222",
        "original_classification": "PHISHING_LINK",
        "feedback_type": "CONFIRM",
        "model_version": "hash-embed-v0",
        "reason": "memang phishing",
        "actor_operator_id": OPERATOR.id,
        "actor_name": OPERATOR.full_name,
        "created_at": datetime(2026, 8, 11, 10, 0, tzinfo=UTC),
        "extracted_text": "klik link ini untuk verifikasi akun anda",
        "current_intent": "PHISHING_LINK",
        "risk_score": "HIGH",
        "used_in_dataset_id": None,
        "used_in_dataset_name": None,
    }
    base.update(overrides)
    return base


def test_list_feedback_route_returns_available_payload(monkeypatch):
    monkeypatch.setattr(
        "app.services.feedback.list_feedback",
        AsyncMock(return_value={"total": 1, "items": [_row_to_item(_row())]}),
    )

    body = client.get("/api/v1/feedback").json()

    assert body["available"] is True
    assert body["total"] == 1
    assert body["items"][0]["feedback_type"] == "CONFIRM"


def test_list_feedback_route_reports_unavailable_on_db_outage(monkeypatch):
    monkeypatch.setattr("app.services.feedback.list_feedback", AsyncMock(side_effect=ConnectionError("db down")))

    body = client.get("/api/v1/feedback").json()

    assert body["available"] is False
    assert body["reason"] == "database_unavailable"


def test_list_feedback_route_filters_by_type(monkeypatch):
    list_mock = AsyncMock(return_value={"total": 0, "items": []})
    monkeypatch.setattr("app.services.feedback.list_feedback", list_mock)

    client.get("/api/v1/feedback?feedback_type=FALSE_POSITIVE")

    assert list_mock.await_args.kwargs["feedback_type"] == "FALSE_POSITIVE"
