"""AI/ML Model Registry & Deployment: routes and lifecycle guards.

No `POST /model-versions` exists — a row is only ever system-created from
`model_evaluations.execute_model_evaluation`'s success path, never by an
operator request, so there is no create-route test here. `apply_model_
version_action` needs a DB read before it can decide anything (current
status), so — same reasoning as Training Jobs/Evaluation — these are
route-level tests against a mocked service, not service-level DB tests.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.core.security import require_operator
from app.main import app
from app.services.auth import Operator
from app.services.model_versions import _row_to_item

client = TestClient(app)

OPERATOR = Operator(
    id="11111111-1111-1111-1111-111111111111",
    email="ops@example.com",
    full_name="Operator Satu",
    is_active=True,
)

MODEL_VERSION_ID = "cccccccc-cccc-cccc-cccc-cccccccccccc"
DEMOTED_ID = "dddddddd-dddd-dddd-dddd-dddddddddddd"
JOB_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
EVALUATION_ID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"


@pytest.fixture(autouse=True)
def signed_in():
    app.dependency_overrides[require_operator] = lambda: OPERATOR
    yield
    app.dependency_overrides.pop(require_operator, None)


def _row(**overrides: object) -> dict[str, object]:
    base = {
        "id": MODEL_VERSION_ID,
        "training_job_id": JOB_ID,
        "training_job_base_model": "hash-embed-v0",
        "generated_model_version": "hash-embed-v0-20260811",
        "training_dataset_name": "health-hoax-v1",
        "training_dataset_version": 1,
        "model_evaluation_id": EVALUATION_ID,
        "evaluation_metrics": {},
        "evaluation_dataset_name": "health-hoax-v1",
        "evaluation_dataset_version": 1,
        "status": "CANDIDATE",
        "created_at": datetime(2026, 8, 11, 10, 0, tzinfo=UTC),
        "updated_at": datetime(2026, 8, 11, 10, 0, tzinfo=UTC),
    }
    base.update(overrides)
    return base


def _action_result(**overrides: object) -> dict[str, object]:
    result = _row_to_item(_row())
    result["previous_status"] = "CANDIDATE"
    result["demoted_version_id"] = None
    result.update(overrides)
    return result


# --------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------


def test_list_model_versions_route_returns_available_payload(monkeypatch):
    monkeypatch.setattr(
        "app.services.model_versions.list_model_versions",
        AsyncMock(return_value={"total": 1, "items": [_row_to_item(_row())]}),
    )

    body = client.get("/api/v1/model-versions").json()

    assert body["available"] is True
    assert body["items"][0]["status"] == "CANDIDATE"


def test_list_model_versions_route_reports_unavailable_on_db_outage(monkeypatch):
    monkeypatch.setattr(
        "app.services.model_versions.list_model_versions", AsyncMock(side_effect=ConnectionError("db down"))
    )

    body = client.get("/api/v1/model-versions").json()

    assert body["available"] is False
    assert body["reason"] == "database_unavailable"


def test_get_model_version_404s_when_missing(monkeypatch):
    monkeypatch.setattr("app.services.model_versions.get_model_version", AsyncMock(return_value=None))

    response = client.get(f"/api/v1/model-versions/{MODEL_VERSION_ID}")

    assert response.status_code == 404


def test_validate_action_writes_audit_log(monkeypatch):
    validated = _action_result(status="VALIDATED", previous_status="CANDIDATE")
    monkeypatch.setattr("app.services.model_versions.apply_model_version_action", AsyncMock(return_value=validated))
    audit_mock = AsyncMock()
    monkeypatch.setattr("app.api.v1.endpoints.model_versions.record_audit", audit_mock)

    response = client.patch(f"/api/v1/model-versions/{MODEL_VERSION_ID}", json={"action": "VALIDATE"})

    assert response.status_code == 200
    assert response.json()["status"] == "VALIDATED"
    assert audit_mock.await_count == 1
    assert audit_mock.await_args.kwargs["action"] == "model_version.validated"


def test_promote_action_with_demotion_writes_two_audit_logs(monkeypatch):
    promoted = _action_result(status="PRODUCTION", previous_status="VALIDATED", demoted_version_id=DEMOTED_ID)
    monkeypatch.setattr("app.services.model_versions.apply_model_version_action", AsyncMock(return_value=promoted))
    audit_mock = AsyncMock()
    monkeypatch.setattr("app.api.v1.endpoints.model_versions.record_audit", audit_mock)

    response = client.patch(f"/api/v1/model-versions/{MODEL_VERSION_ID}", json={"action": "PROMOTE"})

    assert response.status_code == 200
    assert audit_mock.await_count == 2
    first_call, second_call = audit_mock.await_args_list
    assert first_call.kwargs["action"] == "model_version.promoted"
    assert first_call.kwargs["target_id"] == MODEL_VERSION_ID
    assert second_call.kwargs["action"] == "model_version.archived"
    assert second_call.kwargs["target_id"] == DEMOTED_ID


def test_promote_action_without_prior_production_writes_one_audit_log(monkeypatch):
    promoted = _action_result(status="PRODUCTION", previous_status="VALIDATED", demoted_version_id=None)
    monkeypatch.setattr("app.services.model_versions.apply_model_version_action", AsyncMock(return_value=promoted))
    audit_mock = AsyncMock()
    monkeypatch.setattr("app.api.v1.endpoints.model_versions.record_audit", audit_mock)

    response = client.patch(f"/api/v1/model-versions/{MODEL_VERSION_ID}", json={"action": "PROMOTE"})

    assert response.status_code == 200
    assert audit_mock.await_count == 1
    assert audit_mock.await_args.kwargs["action"] == "model_version.promoted"


def test_archive_action_writes_audit_log(monkeypatch):
    archived = _action_result(status="ARCHIVED", previous_status="PRODUCTION")
    monkeypatch.setattr("app.services.model_versions.apply_model_version_action", AsyncMock(return_value=archived))
    audit_mock = AsyncMock()
    monkeypatch.setattr("app.api.v1.endpoints.model_versions.record_audit", audit_mock)

    response = client.patch(f"/api/v1/model-versions/{MODEL_VERSION_ID}", json={"action": "ARCHIVE"})

    assert response.status_code == 200
    assert response.json()["status"] == "ARCHIVED"
    assert audit_mock.await_args.kwargs["action"] == "model_version.archived"


def test_action_404s_when_missing(monkeypatch):
    monkeypatch.setattr("app.services.model_versions.apply_model_version_action", AsyncMock(return_value=None))

    response = client.patch(f"/api/v1/model-versions/{MODEL_VERSION_ID}", json={"action": "VALIDATE"})

    assert response.status_code == 404


def test_action_400s_on_invalid_transition(monkeypatch):
    monkeypatch.setattr(
        "app.services.model_versions.apply_model_version_action",
        AsyncMock(side_effect=ValueError("cannot VALIDATE a model version in status PRODUCTION")),
    )

    response = client.patch(f"/api/v1/model-versions/{MODEL_VERSION_ID}", json={"action": "VALIDATE"})

    assert response.status_code == 400


def test_action_on_model_version_rejects_unknown_action_value():
    response = client.patch(f"/api/v1/model-versions/{MODEL_VERSION_ID}", json={"action": "DELETE_EVERYTHING"})
    assert response.status_code == 422
