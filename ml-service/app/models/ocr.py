"""OCR: image bytes to text, behind one abstraction the rest of the service never bypasses.

Self-hosted, CPU-only, no external API — matches the offline-by-default posture
this service already takes elsewhere (`HashingEmbedder`, `TemplateProvider`).
Tesseract is the only provider implemented today; `OCRProvider` exists so a
second one (PaddleOCR, a cloud API for a future paid tier) is a new class
registered in `app/models/registry.py`, never a rewrite of `/v1/ocr` or of
anything upstream of it.

OCR output is untrusted, attacker-influenceable input — the same threat model
`app/rag/claim.py` already documents for typed WhatsApp messages, arguably
sharper here: a crafted image can embed adversarial text a user never typed
("IGNORE PREVIOUS INSTRUCTIONS" rendered as a screenshot). This module's job
stops at "pixels in, string plus a confidence number out" — nothing here
interprets the text, and the gateway folds it into `body` before claim
extraction's own injection guard runs, exactly as it would a typed message.

OCR is inference-time only. It never touches the locked production classifier,
never retrains anything, and never decides FACT/HOAX/UNKNOWN.
"""

from __future__ import annotations

import asyncio
import io
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass

from PIL import Image, ImageOps, UnidentifiedImageError

logger = logging.getLogger("app.models.ocr")


class OCRValidationError(Exception):
    """Image failed validation before OCR ever ran — always a controlled 4xx, never a crash."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class OCRResult:
    text: str
    confidence: float | None
    language: str | None
    processing_time_ms: int
    success: bool
    error: str | None = None


class OCRProvider(ABC):
    model_version: str

    @abstractmethod
    async def extract_text(self, image: bytes, *, language: str | None = None) -> OCRResult: ...


def sniff_mimetype(image: bytes) -> str | None:
    """The image's real file signature, not whatever Content-Type the sender claimed.

    A client-supplied MIME type is trivially spoofed (09_Security: MIME
    spoofing); the magic bytes are what Pillow is actually about to decode.
    """
    if image.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if image.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if image[:4] == b"RIFF" and image[8:12] == b"WEBP":
        return "image/webp"
    return None


def validate_image(image: bytes, *, max_size_mb: float, max_width: int, max_height: int) -> Image.Image:
    """Decode and bound one untrusted image.

    Raises `OCRValidationError` for every rejection path; never lets Pillow's
    own exceptions, or a decompression bomb, propagate as an unhandled error.
    Size is checked before any decoding happens — the cheapest possible
    rejection for an oversized upload.
    """
    if not image:
        raise OCRValidationError("empty_image")
    if len(image) > int(max_size_mb * 1024 * 1024):
        raise OCRValidationError("image_too_large")

    if sniff_mimetype(image) is None:
        raise OCRValidationError("unsupported_format")

    try:
        decoded = Image.open(io.BytesIO(image))
        # Force the full decode now, inside this try — Pillow is lazy by
        # default, and a truncated/malformed body otherwise only fails later,
        # off this function's error handling.
        decoded.load()
    except Image.DecompressionBombError as exc:
        # Pillow's own guard (Image.MAX_IMAGE_PIXELS, ~178 megapixels default)
        # already fired before the image was fully materialised in memory.
        raise OCRValidationError("decompression_bomb") from exc
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise OCRValidationError("malformed_image") from exc

    width, height = decoded.size
    if width <= 0 or height <= 0:
        raise OCRValidationError("malformed_image")
    if width > max_width or height > max_height:
        raise OCRValidationError("dimensions_too_large")

    return decoded


def _preprocess(image: Image.Image, *, aggressive: bool) -> Image.Image:
    """Bounded preprocessing. `aggressive` marks the retry pass only.

    A clean screenshot run through grayscale/contrast/denoise unconditionally
    often reads *worse*, not better (07_OCR_Preprocessing) — so the first pass
    gets the original pixels (just orientation-corrected), and only a
    low-confidence result earns the heavier treatment.
    """
    working = ImageOps.exif_transpose(image) or image
    if working.mode not in ("L", "RGB"):
        working = working.convert("RGB")
    if not aggressive:
        return working
    working = working.convert("L")
    return ImageOps.autocontrast(working, cutoff=1)


class TesseractOCRProvider(OCRProvider):
    """pytesseract wrapper.

    Every call is offloaded via `asyncio.to_thread` — same reasoning as
    `classifier.train`/`evaluate`: this is a single-uvicorn-worker process
    (Dockerfile), and Tesseract is a blocking, CPU-bound subprocess call that
    would otherwise stall every other in-flight request.
    """

    model_version = "tesseract-ocr"

    def __init__(self, *, languages: str, retry_confidence_threshold: float, max_text_length: int) -> None:
        self._languages = languages
        self._retry_confidence_threshold = retry_confidence_threshold
        self._max_text_length = max_text_length

    async def extract_text(self, image: bytes, *, language: str | None = None) -> OCRResult:
        started = time.perf_counter()
        lang = language or self._languages

        try:
            text, confidence = await asyncio.to_thread(self._run, image, lang, False)
            if confidence < self._retry_confidence_threshold:
                # One bounded retry, heavier preprocessing only — never a
                # second attempt at the same preprocessing, never a third
                # attempt at all (07_OCR_Preprocessing: "keep retry count
                # bounded").
                retry_text, retry_confidence = await asyncio.to_thread(self._run, image, lang, True)
                if retry_confidence > confidence:
                    text, confidence = retry_text, retry_confidence
        except Exception as exc:  # noqa: BLE001 — a Tesseract failure must degrade, never 500 the worker
            logger.warning("tesseract extraction failed", extra={"error": type(exc).__name__})
            return OCRResult(
                text="",
                confidence=None,
                language=lang,
                processing_time_ms=_elapsed_ms(started),
                success=False,
                error="ocr_engine_failed",
            )

        text = text[: self._max_text_length]
        return OCRResult(
            text=text,
            confidence=round(confidence, 4),
            language=lang,
            processing_time_ms=_elapsed_ms(started),
            success=bool(text.strip()),
            error=None if text.strip() else "no_text_detected",
        )

    def _run(self, image: bytes, lang: str, aggressive: bool) -> tuple[str, float]:
        """Blocking. Decoding happens again here (not reused from `validate_image`)
        because this runs in a worker thread and must not share a PIL image
        object across threads with the request coroutine.
        """
        import pytesseract

        decoded = Image.open(io.BytesIO(image)).convert("RGB")
        processed = _preprocess(decoded, aggressive=aggressive)
        data = pytesseract.image_to_data(processed, lang=lang, output_type=pytesseract.Output.DICT)

        lines: dict[tuple[int, int, int], list[str]] = {}
        confidences: list[float] = []
        tokens = data.get("text", [])
        for index, word in enumerate(tokens):
            word = word.strip()
            if not word:
                continue
            key = (
                data["block_num"][index],
                data["par_num"][index],
                data["line_num"][index],
            )
            lines.setdefault(key, []).append(word)
            try:
                conf_value = float(data["conf"][index])
            except (TypeError, ValueError, KeyError, IndexError):
                continue
            if conf_value >= 0:
                confidences.append(conf_value)

        # Line breaks preserved (dict insertion order == reading order from
        # Tesseract's own output) — collapsing everything to one space-joined
        # line would flatten a poster's headline into its body text.
        text = "\n".join(" ".join(words) for words in lines.values())
        avg_confidence = (sum(confidences) / len(confidences) / 100.0) if confidences else 0.0
        return text, avg_confidence


def _elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)
