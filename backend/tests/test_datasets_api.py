"""AI/ML Datasets: validation checks, lifecycle guards, and routes."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.core.security import require_operator
from app.main import app
from app.services import datasets
from app.services.auth import Operator
from app.services.datasets import _row_to_item, _run_validation_checks

client = TestClient(app)

OPERATOR = Operator(
    id="11111111-1111-1111-1111-111111111111",
    email="ops@example.com",
    full_name="Operator Satu",
    is_active=True,
)

DATASET_ID = "88888888-8888-8888-8888-888888888888"


@pytest.fixture(autouse=True)
def signed_in():
    app.dependency_overrides[require_operator] = lambda: OPERATOR
    yield
    app.dependency_overrides.pop(require_operator, None)


def _row(**overrides: object) -> dict[str, object]:
    base = {
        "id": DATASET_ID,
        "name": "phishing-v1",
        "version": 1,
        "source": "OPERATOR_FEEDBACK",
        "status": "DRAFT",
        "description": "Dataset dari feedback operator",
        "validation_notes": None,
        "created_by": OPERATOR.id,
        "created_by_name": OPERATOR.full_name,
        "created_at": datetime(2026, 8, 11, 10, 0, tzinfo=UTC),
        "updated_at": datetime(2026, 8, 11, 10, 0, tzinfo=UTC),
        "sample_count": 0,
    }
    base.update(overrides)
    return base


# --------------------------------------------------------------------------
# `_run_validation_checks` — pure function, no DB
# --------------------------------------------------------------------------


def test_empty_dataset_fails_validation():
    failures = _run_validation_checks([])
    assert any("tidak punya sample" in f for f in failures)


def test_duplicate_text_fails_validation():
    samples = [{"text": "sama"}, {"text": "sama"}, {"text": "beda"}]
    failures = _run_validation_checks(samples)
    assert any("duplikat" in f for f in failures)


def test_raw_phone_number_fails_validation():
    samples = [{"text": "hubungi saya di 081234567890 untuk info lebih lanjut"}]
    failures = _run_validation_checks(samples)
    assert any("nomor telepon" in f for f in failures)


def test_clean_dataset_passes_validation():
    samples = [{"text": "klaim vaksin mengandung chip"}, {"text": "investasi robot trading bodong"}]
    assert _run_validation_checks(samples) == []


# --------------------------------------------------------------------------
# Guards — raise before touching the database
# --------------------------------------------------------------------------


async def test_update_with_no_fields_is_rejected_before_touching_the_database():
    with pytest.raises(ValueError, match="requires at least one"):
        await datasets.apply_dataset_action(DATASET_ID, action="UPDATE")


async def test_add_sample_rejects_invalid_label_before_touching_the_database():
    with pytest.raises(ValueError, match="label"):
        await datasets.add_sample(DATASET_ID, "some text", "NOT_A_REAL_LABEL", OPERATOR.id)


# --------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------


def test_list_datasets_route_returns_available_payload(monkeypatch):
    monkeypatch.setattr(
        "app.services.datasets.list_datasets",
        AsyncMock(return_value={"total": 1, "items": [_row_to_item(_row())]}),
    )

    body = client.get("/api/v1/datasets").json()

    assert body["available"] is True
    assert body["items"][0]["status"] == "DRAFT"


def test_list_datasets_route_reports_unavailable_on_db_outage(monkeypatch):
    monkeypatch.setattr("app.services.datasets.list_datasets", AsyncMock(side_effect=ConnectionError("db down")))

    body = client.get("/api/v1/datasets").json()

    assert body["available"] is False
    assert body["reason"] == "database_unavailable"


def test_get_dataset_404s_when_missing(monkeypatch):
    monkeypatch.setattr("app.services.datasets.get_dataset", AsyncMock(return_value=None))

    response = client.get(f"/api/v1/datasets/{DATASET_ID}")

    assert response.status_code == 404


def test_create_dataset_writes_audit_log(monkeypatch):
    monkeypatch.setattr("app.services.datasets.create_dataset", AsyncMock(return_value=_row_to_item(_row())))
    audit_mock = AsyncMock()
    monkeypatch.setattr("app.api.v1.endpoints.datasets.record_audit", audit_mock)

    response = client.post(
        "/api/v1/datasets",
        json={"name": "phishing-v1", "version": 1, "source": "OPERATOR_FEEDBACK", "description": "x"},
    )

    assert response.status_code == 201
    assert audit_mock.await_args.kwargs["action"] == "dataset.created"


def test_create_dataset_rejects_duplicate_name_version(monkeypatch):
    monkeypatch.setattr(
        "app.services.datasets.create_dataset",
        AsyncMock(side_effect=ValueError("dataset 'phishing-v1' v1 already exists")),
    )

    response = client.post(
        "/api/v1/datasets", json={"name": "phishing-v1", "version": 1, "source": "OPERATOR_FEEDBACK"}
    )

    assert response.status_code == 400


def test_validate_action_writes_audit_with_validation_notes(monkeypatch):
    rejected = _row_to_item(_row(status="REJECTED", validation_notes="dataset tidak punya sample"))
    rejected["previous_status"] = "DRAFT"
    monkeypatch.setattr("app.services.datasets.apply_dataset_action", AsyncMock(return_value=rejected))
    audit_mock = AsyncMock()
    monkeypatch.setattr("app.api.v1.endpoints.datasets.record_audit", audit_mock)

    response = client.patch(f"/api/v1/datasets/{DATASET_ID}", json={"action": "VALIDATE"})

    assert response.status_code == 200
    assert response.json()["status"] == "REJECTED"
    assert audit_mock.await_args.kwargs["metadata"]["validation_notes"] == "dataset tidak punya sample"
    assert audit_mock.await_args.kwargs["action"] == "dataset.status_changed"


def test_action_on_dataset_404s_when_missing(monkeypatch):
    monkeypatch.setattr("app.services.datasets.apply_dataset_action", AsyncMock(return_value=None))

    response = client.patch(f"/api/v1/datasets/{DATASET_ID}", json={"action": "VALIDATE"})

    assert response.status_code == 404


def test_action_on_dataset_400s_on_invalid_transition(monkeypatch):
    monkeypatch.setattr(
        "app.services.datasets.apply_dataset_action",
        AsyncMock(side_effect=ValueError("cannot VALIDATE a dataset in status ARCHIVED")),
    )

    response = client.patch(f"/api/v1/datasets/{DATASET_ID}", json={"action": "VALIDATE"})

    assert response.status_code == 400


def test_add_sample_writes_audit_log(monkeypatch):
    sample = {
        "id": "99999999-9999-9999-9999-999999999999",
        "dataset_id": DATASET_ID,
        "text": "klaim vaksin mengandung chip",
        "label": "HEALTH_HOAX",
        "source_message_log_id": None,
        "source_feedback_id": None,
        "added_by": OPERATOR.id,
        "added_at": "2026-08-11T10:00:00+00:00",
    }
    monkeypatch.setattr("app.services.datasets.add_sample", AsyncMock(return_value=sample))
    audit_mock = AsyncMock()
    monkeypatch.setattr("app.api.v1.endpoints.datasets.record_audit", audit_mock)

    response = client.post(
        f"/api/v1/datasets/{DATASET_ID}/samples",
        json={"text": "klaim vaksin mengandung chip", "label": "HEALTH_HOAX"},
    )

    assert response.status_code == 201
    assert audit_mock.await_args.kwargs["action"] == "dataset.sample_added"


def test_add_sample_rejects_dataset_not_draft(monkeypatch):
    monkeypatch.setattr(
        "app.services.datasets.add_sample",
        AsyncMock(side_effect=ValueError("cannot add a sample to a dataset in status VALIDATED")),
    )

    response = client.post(f"/api/v1/datasets/{DATASET_ID}/samples", json={"text": "x", "label": "HEALTH_HOAX"})

    assert response.status_code == 400


def test_promote_feedback_writes_audit_log(monkeypatch):
    result = {
        "dataset_id": DATASET_ID,
        "considered": 3,
        "promoted": 2,
        "skipped": 1,
        "skipped_reasons": {"empty_message_text": 1},
    }
    monkeypatch.setattr("app.services.feedback.promote_to_dataset", AsyncMock(return_value=result))
    audit_mock = AsyncMock()
    monkeypatch.setattr("app.api.v1.endpoints.datasets.record_audit", audit_mock)

    response = client.post(f"/api/v1/datasets/{DATASET_ID}/promote-feedback", json={})

    assert response.status_code == 200
    assert response.json()["promoted"] == 2
    assert audit_mock.await_args.kwargs["action"] == "dataset.feedback_promoted"
    assert audit_mock.await_args.kwargs["metadata"]["promoted"] == 2


def test_promote_feedback_404s_when_dataset_missing(monkeypatch):
    monkeypatch.setattr("app.services.feedback.promote_to_dataset", AsyncMock(return_value=None))

    response = client.post(f"/api/v1/datasets/{DATASET_ID}/promote-feedback", json={})

    assert response.status_code == 404


def test_promote_feedback_400s_on_non_draft_dataset(monkeypatch):
    monkeypatch.setattr(
        "app.services.feedback.promote_to_dataset",
        AsyncMock(side_effect=ValueError("cannot promote feedback into a dataset in status VALIDATED")),
    )

    response = client.post(f"/api/v1/datasets/{DATASET_ID}/promote-feedback", json={})

    assert response.status_code == 400


def test_promote_feedback_passes_filter_and_limit_through(monkeypatch):
    mock = AsyncMock(
        return_value={"dataset_id": DATASET_ID, "considered": 0, "promoted": 0, "skipped": 0, "skipped_reasons": {}}
    )
    monkeypatch.setattr("app.services.feedback.promote_to_dataset", mock)
    monkeypatch.setattr("app.api.v1.endpoints.datasets.record_audit", AsyncMock())

    response = client.post(
        f"/api/v1/datasets/{DATASET_ID}/promote-feedback", json={"feedback_type": "CONFIRM", "limit": 50}
    )

    assert response.status_code == 200
    assert mock.await_args.kwargs["feedback_type"] == "CONFIRM"
    assert mock.await_args.kwargs["limit"] == 50


def test_remove_sample_404s_when_sample_missing(monkeypatch):
    monkeypatch.setattr("app.services.datasets.remove_sample", AsyncMock(return_value=False))

    response = client.delete(f"/api/v1/datasets/{DATASET_ID}/samples/99999999-9999-9999-9999-999999999999")

    assert response.status_code == 404


def test_remove_sample_writes_audit_log(monkeypatch):
    monkeypatch.setattr("app.services.datasets.remove_sample", AsyncMock(return_value=True))
    audit_mock = AsyncMock()
    monkeypatch.setattr("app.api.v1.endpoints.datasets.record_audit", audit_mock)

    response = client.delete(f"/api/v1/datasets/{DATASET_ID}/samples/99999999-9999-9999-9999-999999999999")

    assert response.status_code == 200
    assert audit_mock.await_args.kwargs["action"] == "dataset.sample_removed"
