"""AI/ML Overview: aggregation route and per-block resilience."""

from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.core.security import require_operator
from app.main import app
from app.services import ai_ml_overview
from app.services.auth import Operator

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


def _overview(**overrides: object) -> dict[str, object]:
    base = {
        "knowledge_base": {
            "available": True,
            "total_facts": 5,
            "active_facts": 5,
            "synced": 5,
            "never_synced": 0,
            "sync_failed": 0,
            "total_sources": 5,
        },
        "detection_rules": {"available": True, "total": 9, "by_status": {"DRAFT": 8, "ACTIVE": 1}},
        "policies": {"available": True, "total": 4, "by_status": {"ACTIVE": 1, "DISABLED": 1, "ARCHIVED": 2}},
        "ml_service": {
            "available": True,
            "status": "ready",
            "embedder": "hash-embed-v0",
            "llm": "stub-llm-v0",
            "degraded_reasons": [],
            "vector_store": {
                "available": True,
                "collection": "fact_knowledge_base",
                "points_count": 5,
                "vector_size": 1536,
                "distance": "Cosine",
            },
        },
        "training_jobs": {"available": True, "total": 2, "by_status": {"FAILED": 2}},
        "model_registry": {"available": True, "total": 1, "by_status": {"CANDIDATE": 1}},
        "evaluation": {"available": True, "total": 1, "by_status": {"QUEUED": 1}},
    }
    base.update(overrides)
    return base


def test_ai_ml_overview_route_returns_aggregated_payload(monkeypatch):
    monkeypatch.setattr("app.services.ai_ml_overview.get_overview", AsyncMock(return_value=_overview()))

    body = client.get("/api/v1/ai-ml/overview").json()

    assert body["knowledge_base"]["total_facts"] == 5
    assert body["detection_rules"]["by_status"]["ACTIVE"] == 1
    assert body["ml_service"]["vector_store"]["points_count"] == 5
    assert body["training_jobs"] == {"available": True, "total": 2, "by_status": {"FAILED": 2}}
    assert body["evaluation"] == {"available": True, "total": 1, "by_status": {"QUEUED": 1}}
    assert body["model_registry"] == {"available": True, "total": 1, "by_status": {"CANDIDATE": 1}}


def test_ai_ml_overview_route_degrades_gracefully_on_total_failure(monkeypatch):
    monkeypatch.setattr(
        "app.services.ai_ml_overview.get_overview", AsyncMock(side_effect=ConnectionError("db down"))
    )

    body = client.get("/api/v1/ai-ml/overview").json()

    assert body["knowledge_base"]["available"] is False
    assert body["ml_service"]["available"] is False
    # training_jobs, evaluation, and model_registry are all real data now
    # (Stages 11-13) — the outer-except fallback reports every block the
    # same way. This is the last stage: no block asserts "not_yet_built"
    # anymore.
    assert body["training_jobs"]["reason"] == "database_unavailable"
    assert body["evaluation"]["reason"] == "database_unavailable"
    assert body["model_registry"]["reason"] == "database_unavailable"


# --------------------------------------------------------------------------
# Per-block resilience — one failing source does not blank the others
# --------------------------------------------------------------------------


async def test_knowledge_base_stats_degrades_independently(monkeypatch):
    async def _boom(_settings):
        raise ConnectionError("db down")

    monkeypatch.setattr(ai_ml_overview, "_connect", _boom)

    result = await ai_ml_overview._knowledge_base_stats(ai_ml_overview.get_settings())

    assert result == {"available": False, "reason": "database_unavailable"}


async def test_ml_service_status_degrades_independently(monkeypatch):
    class _Client:
        def __init__(self, _settings):
            pass

        async def ready(self):
            raise ConnectionError("ml service down")

    monkeypatch.setattr(ai_ml_overview, "MlClient", _Client)

    result = await ai_ml_overview._ml_service_status(ai_ml_overview.get_settings())

    assert result == {"available": False, "reason": "ml_service_unreachable"}


async def test_ml_service_status_reports_unreachable_vector_store(monkeypatch):
    class _Client:
        def __init__(self, _settings):
            pass

        async def ready(self):
            return False, {
                "status": "not_ready",
                "models": {"embedder": "hash-embed-v0"},
                "vector_store": {"error": "ResponseHandlingException"},
            }

    monkeypatch.setattr(ai_ml_overview, "MlClient", _Client)

    result = await ai_ml_overview._ml_service_status(ai_ml_overview.get_settings())

    assert result["available"] is True
    assert result["vector_store"] == {"available": False, "reason": "vector_store_unreachable"}
