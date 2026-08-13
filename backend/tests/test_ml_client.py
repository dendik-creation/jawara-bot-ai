"""Gateway → ML Service client: contract, timeouts, retry policy."""

import pytest

from app.clients.ml_client import MlClient, MlServiceError
from app.core.config import Settings
from tests.http_stub import FakeResponse, patch_httpx, raise_connect_error, raise_timeout

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
        await MlClient(ml_settings()).classify(REQUEST_ID, "halo", "clf-test", "deadbeef")

    assert excinfo.value.error_code == "model_not_available"
    assert excinfo.value.retryable is False


async def test_non_structured_5xx_is_treated_as_retryable(monkeypatch):
    patch_httpx(monkeypatch, "app.clients.ml_client", lambda **_: FakeResponse(502, text="bad gateway"))

    with pytest.raises(MlServiceError) as excinfo:
        await MlClient(ml_settings()).classify(REQUEST_ID, "halo", "clf-test", "deadbeef")

    assert excinfo.value.retryable is True


async def test_disabled_ml_service_fails_fast_without_a_request(monkeypatch):
    calls = patch_httpx(monkeypatch, "app.clients.ml_client", lambda **_: ok({}))

    with pytest.raises(MlServiceError) as excinfo:
        await MlClient(ml_settings(ml_enabled=False)).classify(REQUEST_ID, "halo", "clf-test", "deadbeef")

    assert excinfo.value.error_code == "ml_disabled"
    assert calls == []


async def test_ready_probe_never_raises(monkeypatch):
    patch_httpx(monkeypatch, "app.clients.ml_client", raise_connect_error)
    ready, detail = await MlClient(ml_settings()).ready()

    assert ready is False
    assert "error" in detail


async def test_extract_claim_sends_the_documented_envelope(monkeypatch):
    calls = patch_httpx(
        monkeypatch, "app.clients.ml_client", lambda **_: ok({"claim": "klaim", "method": "llm"})
    )
    response = await MlClient(ml_settings()).extract_claim(
        REQUEST_ID, "pesan panjang yang diteruskan", category="HEALTH_HOAX"
    )

    assert calls[0]["url"] == "http://ml-service:9000/v1/extract-claim"
    assert calls[0]["json"]["payload"] == {
        "text": "pesan panjang yang diteruskan",
        "category": "HEALTH_HOAX",
    }
    assert response.result["claim"] == "klaim"


async def test_extract_claim_is_retried_like_the_other_idempotent_calls(monkeypatch):
    """Extraction has no side effect — unlike `generate`, a second attempt
    costs a little latency and nothing else."""
    attempts: list[int] = []

    def flaky(**_):
        attempts.append(1)
        if len(attempts) == 1:
            return FakeResponse(503, {"error_code": "busy", "message": "later", "retryable": True})
        return ok({"claim": "klaim", "method": "heuristic"})

    patch_httpx(monkeypatch, "app.clients.ml_client", flaky)
    response = await MlClient(ml_settings()).extract_claim(REQUEST_ID, "teks")

    assert len(attempts) == 2
    assert response.result["method"] == "heuristic"


async def test_ocr_sends_multipart_not_json(monkeypatch):
    """The one endpoint that breaks the JSON envelope every other call uses —
    images go as multipart/binary (05_Audit/02_Architecture_Audit_ML_Decoupling.md)."""
    calls = patch_httpx(
        monkeypatch,
        "app.clients.ml_client",
        lambda **_: ok({"text": "BREAKING NEWS", "success": True, "language": "ind+eng", "error": None}),
    )

    response = await MlClient(ml_settings()).ocr(REQUEST_ID, b"\xff\xd8\xff...", "screenshot.jpg", "image/jpeg")

    assert calls[0]["url"] == "http://ml-service:9000/v1/ocr"
    assert "json" not in calls[0]
    assert calls[0]["data"] == {"request_id": REQUEST_ID}
    assert calls[0]["files"] == {"image": ("screenshot.jpg", b"\xff\xd8\xff...", "image/jpeg")}
    assert response.result["text"] == "BREAKING NEWS"


async def test_ocr_is_never_retried(monkeypatch):
    """Unlike `extract_claim`/`embed`, a retry re-uploads the image and re-runs
    a CPU-bound OCR pass — the cost the client must not spend blindly."""
    calls = patch_httpx(monkeypatch, "app.clients.ml_client", raise_connect_error)

    with pytest.raises(MlServiceError) as excinfo:
        await MlClient(ml_settings()).ocr(REQUEST_ID, b"bytes", "x.png", "image/png")

    assert len(calls) == 1
    assert excinfo.value.error_code == "ocr_unreachable"


async def test_ocr_timeout_is_reported_as_a_structured_error(monkeypatch):
    patch_httpx(monkeypatch, "app.clients.ml_client", raise_timeout)

    with pytest.raises(MlServiceError) as excinfo:
        await MlClient(ml_settings()).ocr(REQUEST_ID, b"bytes", "x.png", "image/png")

    assert excinfo.value.error_code == "ocr_timeout"
    assert excinfo.value.retryable is False


async def test_ocr_structured_rejection_is_parsed(monkeypatch):
    patch_httpx(
        monkeypatch,
        "app.clients.ml_client",
        lambda **_: FakeResponse(422, {"error_code": "ocr_invalid_image", "message": "unsupported_format", "retryable": False}),
    )

    with pytest.raises(MlServiceError) as excinfo:
        await MlClient(ml_settings()).ocr(REQUEST_ID, b"not an image", "x.gif", "image/gif")

    assert excinfo.value.error_code == "ocr_invalid_image"


async def test_ocr_disabled_ml_service_fails_fast(monkeypatch):
    calls = patch_httpx(monkeypatch, "app.clients.ml_client", lambda **_: ok({}))

    with pytest.raises(MlServiceError) as excinfo:
        await MlClient(ml_settings(ml_enabled=False)).ocr(REQUEST_ID, b"bytes", "x.png", "image/png")

    assert excinfo.value.error_code == "ml_disabled"
    assert calls == []
