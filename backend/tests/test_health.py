from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_ok_when_dependencies_reachable():
    with (
        patch("app.api.v1.endpoints.health.check_database", new=AsyncMock(return_value=True)),
        patch("app.api.v1.endpoints.health.check_redis", new=AsyncMock(return_value=True)),
    ):
        resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "dependencies": {"database": True, "redis": True}}


def test_health_degraded_when_dependency_down():
    with (
        patch("app.api.v1.endpoints.health.check_database", new=AsyncMock(return_value=False)),
        patch("app.api.v1.endpoints.health.check_redis", new=AsyncMock(return_value=True)),
    ):
        resp = client.get("/health")
    assert resp.status_code == 503
    assert resp.json()["status"] == "degraded"
