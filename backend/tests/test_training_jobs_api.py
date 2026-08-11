"""AI/ML Training Jobs: routes and lifecycle guards.

`create_training_job`/`apply_job_action` both need a DB read before they can
decide anything (dataset status / job status), so — same reasoning Datasets'
transition guards weren't unit-tested standalone — these are route-level
tests against a mocked service, not service-level DB tests.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.core.security import require_operator
from app.main import app
from app.services.auth import Operator
from app.services.training_jobs import _row_to_item

client = TestClient(app)

OPERATOR = Operator(
    id="11111111-1111-1111-1111-111111111111",
    email="ops@example.com",
    full_name="Operator Satu",
    is_active=True,
)

JOB_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
DATASET_ID = "88888888-8888-8888-8888-888888888888"


@pytest.fixture(autouse=True)
def signed_in():
    app.dependency_overrides[require_operator] = lambda: OPERATOR
    yield
    app.dependency_overrides.pop(require_operator, None)


def _row(**overrides: object) -> dict[str, object]:
    base = {
        "id": JOB_ID,
        "dataset_id": DATASET_ID,
        "dataset_name": "health-hoax-v1",
        "dataset_version": 1,
        "base_model": "hash-embed-v0",
        "epochs": 10,
        "learning_rate": 0.001,
        "batch_size": 32,
        "validation_split": 0.2,
        "extra_config": {},
        "status": "QUEUED",
        "progress": None,
        "metrics": None,
        "error_message": None,
        "generated_model_version": None,
        "celery_task_id": "task-123",
        "started_at": None,
        "finished_at": None,
        "created_by": OPERATOR.id,
        "created_by_name": OPERATOR.full_name,
        "created_at": datetime(2026, 8, 11, 10, 0, tzinfo=UTC),
        "updated_at": datetime(2026, 8, 11, 10, 0, tzinfo=UTC),
    }
    base.update(overrides)
    return base


# --------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------


def test_list_training_jobs_route_returns_available_payload(monkeypatch):
    monkeypatch.setattr(
        "app.services.training_jobs.list_training_jobs",
        AsyncMock(return_value={"total": 1, "items": [_row_to_item(_row())]}),
    )

    body = client.get("/api/v1/training-jobs").json()

    assert body["available"] is True
    assert body["items"][0]["status"] == "QUEUED"


def test_list_training_jobs_route_reports_unavailable_on_db_outage(monkeypatch):
    monkeypatch.setattr(
        "app.services.training_jobs.list_training_jobs", AsyncMock(side_effect=ConnectionError("db down"))
    )

    body = client.get("/api/v1/training-jobs").json()

    assert body["available"] is False
    assert body["reason"] == "database_unavailable"


def test_get_training_job_404s_when_missing(monkeypatch):
    monkeypatch.setattr("app.services.training_jobs.get_training_job", AsyncMock(return_value=None))

    response = client.get(f"/api/v1/training-jobs/{JOB_ID}")

    assert response.status_code == 404


def test_create_training_job_writes_audit_log(monkeypatch):
    monkeypatch.setattr(
        "app.services.training_jobs.create_training_job", AsyncMock(return_value=_row_to_item(_row()))
    )
    audit_mock = AsyncMock()
    monkeypatch.setattr("app.api.v1.endpoints.training_jobs.record_audit", audit_mock)

    response = client.post(
        "/api/v1/training-jobs", json={"dataset_id": DATASET_ID, "base_model": "hash-embed-v0", "epochs": 10}
    )

    assert response.status_code == 201
    assert response.json()["status"] == "QUEUED"
    assert audit_mock.await_args.kwargs["action"] == "training_job.created"


def test_create_training_job_rejects_non_validated_dataset(monkeypatch):
    monkeypatch.setattr(
        "app.services.training_jobs.create_training_job",
        AsyncMock(side_effect=ValueError("dataset must be VALIDATED, not DRAFT")),
    )

    response = client.post("/api/v1/training-jobs", json={"dataset_id": DATASET_ID, "base_model": "hash-embed-v0"})

    assert response.status_code == 400


def test_create_training_job_rejects_missing_base_model():
    response = client.post("/api/v1/training-jobs", json={"dataset_id": DATASET_ID, "base_model": ""})
    assert response.status_code == 422


def test_cancel_action_writes_audit_log(monkeypatch):
    cancelled = _row_to_item(_row(status="CANCELLED", finished_at=datetime(2026, 8, 11, 10, 5, tzinfo=UTC)))
    monkeypatch.setattr("app.services.training_jobs.apply_job_action", AsyncMock(return_value=cancelled))
    audit_mock = AsyncMock()
    monkeypatch.setattr("app.api.v1.endpoints.training_jobs.record_audit", audit_mock)

    response = client.patch(f"/api/v1/training-jobs/{JOB_ID}", json={"action": "CANCEL"})

    assert response.status_code == 200
    assert response.json()["status"] == "CANCELLED"
    assert audit_mock.await_args.kwargs["action"] == "training_job.cancelled"


def test_cancel_action_404s_when_missing(monkeypatch):
    monkeypatch.setattr("app.services.training_jobs.apply_job_action", AsyncMock(return_value=None))

    response = client.patch(f"/api/v1/training-jobs/{JOB_ID}", json={"action": "CANCEL"})

    assert response.status_code == 404


def test_cancel_action_400s_on_invalid_transition(monkeypatch):
    monkeypatch.setattr(
        "app.services.training_jobs.apply_job_action",
        AsyncMock(side_effect=ValueError("cannot CANCEL a job in status COMPLETED")),
    )

    response = client.patch(f"/api/v1/training-jobs/{JOB_ID}", json={"action": "CANCEL"})

    assert response.status_code == 400


def test_action_on_training_job_rejects_unknown_action_value():
    response = client.patch(f"/api/v1/training-jobs/{JOB_ID}", json={"action": "DELETE_EVERYTHING"})
    assert response.status_code == 422
