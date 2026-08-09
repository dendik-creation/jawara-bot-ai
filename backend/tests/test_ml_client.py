"""Gateway → ML Service client: contract, timeouts, retry policy."""

import pytest

from app.clients.ml_client import MlClient, MlServiceError
from app.core.config import Settings
from tests.http_stub import FakeResponse, patch_httpx, raise_connect_error

REQUEST_ID = "false_628111@c.us_ABCDEF"


def ml_settings(**overrides) -> Settings:
    base = {"ml_service_url": "http://ml-service:9000", "ml_service_api_key": "internal-key"}
    base.update(overrides)
    return Settings(**base)


def ok(result: dict, model_version: str = "hash-embed-v0") -> FakeResponse:
    return FakeResponse(200, {"request_id": REQUEST_ID, "result": result, "model_version": model_version})


async def test_rag_query_sends_the_documented_envelope(monkeypatch):
    calls = patch_httpx(monkeypatch, "app.clients.ml_client", lambda **_: ok({"matches": []}))
    await MlClient(ml_settings()).rag_query(REQUEST_ID, "air rebusan daun kitolod", category="HEALTH_HOAX")

    body = calls[0]["json"]
    assert calls[0]["url"] == "http://ml-service:9000/v1/rag-query"
    assert set(body) == {"request_id", "payload", "metadata"}
    assert body["request_id"] == REQUEST_ID
    assert body["payload"]["category"] == "HEALTH_HOAX"
    # Documented retrieval contract, not ad-hoc values at the call site.
    assert body["payload"]["top_k"] == 3
    assert body["payload"]["score_threshold"] == 0.80


async def test_internal_api_key_is_sent_on_every_call(monkeypatch):
    calls = patch_httpx(monkeypatch, "app.clients.ml_client", lambda **_: ok({"vectors": []}))
    await MlClient(ml_settings()).embed(REQUEST_ID, ["halo"])

    assert calls[0]["headers"]["X-Internal-Api-Key"] == "internal-key"


async def test_model_version_is_surfaced_to_the_caller(monkeypatch):
    patch_httpx(monkeypatch, "app.clients.ml_client", lambda **_: ok({"message": "x"}, "anthropic-haiku"))
    response = await MlClient(ml_settings()).generate(REQUEST_ID, "halo", "GENERAL_NEWS", "LOW")

    assert response.model_version == "anthropic-haiku"


async def test_idempotent_endpoint_is_retried_once(monkeypatch):
    attempts: list[int] = []

    def handler(**_):
        attempts.append(1)
        if len(attempts) == 1:
            raise_connect_error()
        return ok({"vectors": [[0.0]]})

    patch_httpx(monkeypatch, "app.clients.ml_client", handler)
    await MlClient(ml_settings()).embed(REQUEST_ID, ["halo"])

    assert len(attempts) == 2


async def test_generate_is_never_retried(monkeypatch):
    # Generation costs money and has a fallback; a blind retry is the wrong
    # answer to a slow provider.
    calls = patch_httpx(monkeypatch, "app.clients.ml_client", raise_connect_error)

    with pytest.raises(MlServiceError):
        await MlClient(ml_settings()).generate(REQUEST_ID, "halo", "GENERAL_NEWS", "LOW")

    assert len(calls) == 1


async def test_structured_error_is_parsed_including_retryable(monkeypatch):
    patch_httpx(
        monkeypatch,
        "app.clients.ml_client",
        lambda **_: FakeResponse(
            503, {"error_code": "model_not_available", "message": "no model", "retryable": False}
        ),
    )

    with pytest.raises(MlServiceError) as excinfo:
        await MlClient(ml_settings()).classify(REQUEST_ID, "halo")

    assert excinfo.value.error_code == "model_not_available"
    assert excinfo.value.retryable is False


async def test_non_structured_5xx_is_treated_as_retryable(monkeypatch):
    patch_httpx(monkeypatch, "app.clients.ml_client", lambda **_: FakeResponse(502, text="bad gateway"))

    with pytest.raises(MlServiceError) as excinfo:
        await MlClient(ml_settings()).classify(REQUEST_ID, "halo")

    assert excinfo.value.retryable is True


async def test_disabled_ml_service_fails_fast_without_a_request(monkeypatch):
    calls = patch_httpx(monkeypatch, "app.clients.ml_client", lambda **_: ok({}))

    with pytest.raises(MlServiceError) as excinfo:
        await MlClient(ml_settings(ml_enabled=False)).classify(REQUEST_ID, "halo")

    assert excinfo.value.error_code == "ml_disabled"
    assert calls == []


async def test_ready_probe_never_raises(monkeypatch):
    patch_httpx(monkeypatch, "app.clients.ml_client", raise_connect_error)
    ready, detail = await MlClient(ml_settings()).ready()

    assert ready is False
    assert "error" in detail
