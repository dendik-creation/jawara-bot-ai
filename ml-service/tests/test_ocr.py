"""OCR: image validation, the Tesseract provider's retry/confidence logic, and
`/v1/ocr` endpoint behaviour (success, empty result, invalid image, timeout, auth).

No live `tesseract` binary is assumed here — `TesseractOCRProvider` tests
monkeypatch `pytesseract.image_to_data` directly (same reasoning as
`test_ml_client.py` stubbing `httpx`: the unit under test is judged on how it
reacts to what the dependency returns, not on the dependency itself), and the
endpoint tests monkeypatch `registry.ocr()` so they exercise routing,
validation and error mapping without needing the OS package installed in CI.
"""

import asyncio
import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.core.config import get_settings
from app.core.errors import MlError
from app.main import app
from app.models.ocr import (
    OCRResult,
    OCRValidationError,
    TesseractOCRProvider,
    sniff_mimetype,
    validate_image,
)
from app.models.registry import registry

API_KEY = get_settings().ml_service_api_key
HEADERS = {"X-Internal-Api-Key": API_KEY}


def png_bytes(width: int = 40, height: int = 20, color: str = "white") -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), color=color).save(buffer, format="PNG")
    return buffer.getvalue()


def jpeg_bytes(width: int = 40, height: int = 20) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), color="white").save(buffer, format="JPEG")
    return buffer.getvalue()


# --------------------------------------------------------------------------
# sniff_mimetype / validate_image
# --------------------------------------------------------------------------


def test_sniff_mimetype_recognises_jpeg_png_webp():
    assert sniff_mimetype(jpeg_bytes()) == "image/jpeg"
    assert sniff_mimetype(png_bytes()) == "image/png"
    riff_webp = b"RIFF\x00\x00\x00\x00WEBPVP8 "
    assert sniff_mimetype(riff_webp) == "image/webp"


def test_sniff_mimetype_rejects_unknown_signature():
    assert sniff_mimetype(b"not an image at all") is None
    assert sniff_mimetype(b"") is None


def test_validate_image_accepts_a_clean_png():
    decoded = validate_image(png_bytes(), max_size_mb=10, max_width=4096, max_height=4096)
    assert decoded.size == (40, 20)


def test_validate_image_rejects_empty_input():
    with pytest.raises(OCRValidationError) as exc:
        validate_image(b"", max_size_mb=10, max_width=4096, max_height=4096)
    assert exc.value.reason == "empty_image"


def test_validate_image_rejects_oversized_bytes_before_decoding():
    # 1 byte over a 0MB budget — never gets far enough to look at content.
    with pytest.raises(OCRValidationError) as exc:
        validate_image(png_bytes(), max_size_mb=0.00001, max_width=4096, max_height=4096)
    assert exc.value.reason == "image_too_large"


def test_validate_image_rejects_unsupported_format():
    # Valid GIF signature, not one of JPEG/PNG/WEBP — WhatsApp doesn't send
    # GIFs as image attachments, and this pipeline only claims those three.
    gif = b"GIF89a" + b"\x00" * 20
    with pytest.raises(OCRValidationError) as exc:
        validate_image(gif, max_size_mb=10, max_width=4096, max_height=4096)
    assert exc.value.reason == "unsupported_format"


def test_validate_image_rejects_malformed_bytes_with_a_valid_signature():
    # Real PNG magic bytes, garbage after them — a truncated/corrupted upload.
    truncated = b"\x89PNG\r\n\x1a\n" + b"\x00" * 10
    with pytest.raises(OCRValidationError) as exc:
        validate_image(truncated, max_size_mb=10, max_width=4096, max_height=4096)
    assert exc.value.reason == "malformed_image"


def test_validate_image_rejects_dimensions_over_the_configured_cap():
    with pytest.raises(OCRValidationError) as exc:
        validate_image(png_bytes(width=100, height=100), max_size_mb=10, max_width=50, max_height=50)
    assert exc.value.reason == "dimensions_too_large"


# --------------------------------------------------------------------------
# TesseractOCRProvider: retry/confidence logic, no real tesseract binary
# --------------------------------------------------------------------------


def _tesseract_data(words: list[tuple[str, int]]) -> dict:
    """Shape pytesseract.image_to_data(..., output_type=Output.DICT) returns."""
    n = len(words)
    return {
        "text": [w for w, _ in words],
        "conf": [c for _, c in words],
        "block_num": [1] * n,
        "par_num": [1] * n,
        "line_num": [1] * n,
    }


async def test_extract_text_returns_joined_words_and_average_confidence(monkeypatch):
    import pytesseract

    monkeypatch.setattr(
        pytesseract, "image_to_data", lambda *a, **k: _tesseract_data([("BREAKING", 90), ("NEWS", 80)])
    )
    provider = TesseractOCRProvider(languages="ind+eng", retry_confidence_threshold=0.35, max_text_length=10000)

    result = await provider.extract_text(png_bytes())

    assert result.success is True
    assert result.text == "BREAKING NEWS"
    assert result.confidence == pytest.approx(0.85)
    assert result.error is None


async def test_extract_text_retries_once_on_low_confidence_and_keeps_the_better_pass(monkeypatch):
    import pytesseract

    calls: list[bool] = []

    def fake(image, lang, output_type):
        # First (non-aggressive) pass reads badly; the aggressive retry reads
        # better — the provider must keep the retry's result.
        calls.append(True)
        if len(calls) == 1:
            return _tesseract_data([("garbled", 10)])
        return _tesseract_data([("SELAMAT", 95)])

    monkeypatch.setattr(pytesseract, "image_to_data", fake)
    provider = TesseractOCRProvider(languages="ind+eng", retry_confidence_threshold=0.35, max_text_length=10000)

    result = await provider.extract_text(png_bytes())

    assert len(calls) == 2  # bounded: exactly one retry, never more
    assert result.text == "SELAMAT"
    assert result.confidence == pytest.approx(0.95)


async def test_extract_text_does_not_retry_above_the_threshold(monkeypatch):
    import pytesseract

    calls: list[bool] = []

    def fake(image, lang, output_type):
        calls.append(True)
        return _tesseract_data([("fine", 60)])

    monkeypatch.setattr(pytesseract, "image_to_data", fake)
    provider = TesseractOCRProvider(languages="ind+eng", retry_confidence_threshold=0.35, max_text_length=10000)

    await provider.extract_text(png_bytes())

    assert len(calls) == 1


async def test_extract_text_with_no_words_is_a_controlled_empty_result(monkeypatch):
    import pytesseract

    monkeypatch.setattr(pytesseract, "image_to_data", lambda *a, **k: _tesseract_data([]))
    provider = TesseractOCRProvider(languages="ind+eng", retry_confidence_threshold=0.35, max_text_length=10000)

    result = await provider.extract_text(png_bytes())

    assert result.success is False
    assert result.text == ""
    assert result.error == "no_text_detected"


async def test_extract_text_engine_failure_degrades_instead_of_raising(monkeypatch):
    import pytesseract

    def boom(*a, **k):
        raise RuntimeError("tesseract not found")

    monkeypatch.setattr(pytesseract, "image_to_data", boom)
    provider = TesseractOCRProvider(languages="ind+eng", retry_confidence_threshold=0.35, max_text_length=10000)

    result = await provider.extract_text(png_bytes())

    assert result.success is False
    assert result.error == "ocr_engine_failed"


async def test_extract_text_truncates_to_max_text_length(monkeypatch):
    import pytesseract

    monkeypatch.setattr(pytesseract, "image_to_data", lambda *a, **k: _tesseract_data([("x" * 50, 90)]))
    provider = TesseractOCRProvider(languages="ind+eng", retry_confidence_threshold=0.35, max_text_length=10)

    result = await provider.extract_text(png_bytes())

    assert len(result.text) == 10


# --------------------------------------------------------------------------
# POST /v1/ocr endpoint
# --------------------------------------------------------------------------


class FakeRepository:
    async def health(self):
        return {"collection": "fact_knowledge_base"}

    async def close(self):
        return None


class StubOCRProvider:
    """Swapped into the registry so endpoint tests never touch a real engine."""

    model_version = "stub-ocr-v0"

    def __init__(self, result: OCRResult | None = None, raise_after: float | None = None):
        self._result = result or OCRResult(
            text="BREAKING NEWS", confidence=0.9, language="ind+eng", processing_time_ms=5, success=True
        )
        self._raise_after = raise_after

    async def extract_text(self, image: bytes, *, language: str | None = None) -> OCRResult:
        if self._raise_after is not None:
            await asyncio.sleep(self._raise_after)
        return self._result


@pytest.fixture
def client(monkeypatch):
    with TestClient(app) as test_client:
        test_client.app.state.qdrant = FakeRepository()
        yield test_client


def test_ocr_endpoint_returns_extracted_text(client, monkeypatch):
    monkeypatch.setattr(registry, "ocr", lambda: StubOCRProvider())

    response = client.post(
        "/v1/ocr",
        headers=HEADERS,
        data={"request_id": "req-1"},
        files={"image": ("screenshot.png", png_bytes(), "image/png")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["result"]["text"] == "BREAKING NEWS"
    assert body["result"]["success"] is True
    assert body["confidence"] == 0.9
    assert body["model_version"] == "stub-ocr-v0"


def test_ocr_endpoint_empty_result_is_reported_not_fabricated(client, monkeypatch):
    empty = OCRResult(text="", confidence=None, language="ind+eng", processing_time_ms=3, success=False, error="no_text_detected")
    monkeypatch.setattr(registry, "ocr", lambda: StubOCRProvider(result=empty))

    response = client.post(
        "/v1/ocr",
        headers=HEADERS,
        data={"request_id": "req-2"},
        files={"image": ("blank.png", png_bytes(), "image/png")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["result"]["success"] is False
    assert body["result"]["text"] == ""
    assert body["result"]["error"] == "no_text_detected"


def test_ocr_endpoint_rejects_malformed_image_without_running_ocr(client, monkeypatch):
    calls: list[bytes] = []

    class RecordingProvider(StubOCRProvider):
        async def extract_text(self, image, *, language=None):
            calls.append(image)
            return await super().extract_text(image, language=language)

    monkeypatch.setattr(registry, "ocr", lambda: RecordingProvider())

    response = client.post(
        "/v1/ocr",
        headers=HEADERS,
        data={"request_id": "req-3"},
        files={"image": ("bad.png", b"not a real image", "image/png")},
    )

    assert response.status_code == 422
    assert response.json()["error_code"] == "ocr_invalid_image"
    assert calls == []  # never reached the OCR engine


def test_ocr_endpoint_times_out_in_a_controlled_way(client, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "ocr_timeout_seconds", 0.05)
    monkeypatch.setattr(registry, "ocr", lambda: StubOCRProvider(raise_after=1.0))

    response = client.post(
        "/v1/ocr",
        headers=HEADERS,
        data={"request_id": "req-4"},
        files={"image": ("slow.png", png_bytes(), "image/png")},
    )

    assert response.status_code == 504
    assert response.json()["error_code"] == "ocr_timeout"


def test_ocr_endpoint_requires_the_internal_api_key(client):
    response = client.post(
        "/v1/ocr",
        data={"request_id": "req-5"},
        files={"image": ("x.png", png_bytes(), "image/png")},
    )

    assert response.status_code == 401
