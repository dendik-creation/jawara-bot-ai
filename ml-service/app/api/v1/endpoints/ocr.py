"""`POST /v1/ocr` — image in, text out.

The only endpoint on this service that takes multipart/binary instead of the
`{request_id, payload, metadata}` JSON envelope every other `/v1` route uses
(05_Audit/02_Architecture_Audit_ML_Decoupling.md: base64-in-JSON would inflate
a photo upload by roughly a third and add JSON parse cost for what is
otherwise a binary transfer). The response still comes back as the documented
`MlResponse` shape — only the request differs.

OCR is inference-time only. It never touches the locked production
classifier, never retrains anything, never decides FACT/HOAX/UNKNOWN. It hands
text back; the gateway folds that text into the same message-processing path
a typed WhatsApp message already takes, injection guard included.
"""

import asyncio
import logging
import time

from fastapi import APIRouter, Depends, File, Form, UploadFile

from app.api.deps import envelope
from app.core.config import get_settings
from app.core.errors import MlError
from app.core.security import verify_internal_key
from app.models.ocr import OCRValidationError, validate_image
from app.models.registry import registry
from app.schemas.contract import MlResponse

logger = logging.getLogger("app.api.ocr")

router = APIRouter(dependencies=[Depends(verify_internal_key)])


@router.post("/ocr", response_model=MlResponse)
async def ocr(
    request_id: str = Form(...),
    language: str | None = Form(default=None),
    image: UploadFile = File(...),
) -> MlResponse:
    settings = get_settings()
    started = time.perf_counter()
    raw = await image.read()

    try:
        validate_image(
            raw,
            max_size_mb=settings.ocr_max_image_size_mb,
            max_width=settings.ocr_max_width,
            max_height=settings.ocr_max_height,
        )
    except OCRValidationError as exc:
        # Rejected before OCR ever ran — logged without the image bytes or
        # any extracted text, since there is none yet (19_Observability: no
        # sensitive content in logs/metrics).
        logger.info("ocr validation rejected image", extra={"request_id": request_id, "reason": exc.reason})
        raise MlError("ocr_invalid_image", exc.reason, status_code=422, retryable=False) from exc

    provider = registry.ocr()
    try:
        result = await asyncio.wait_for(
            provider.extract_text(raw, language=language), timeout=settings.ocr_timeout_seconds
        )
    except asyncio.TimeoutError as exc:
        logger.warning("ocr timed out", extra={"request_id": request_id})
        raise MlError(
            "ocr_timeout", "OCR exceeded the configured timeout", status_code=504, retryable=False
        ) from exc

    logger.info(
        "ocr complete",
        extra={
            "request_id": request_id,
            "success": result.success,
            "language": result.language,
            "processing_time_ms": result.processing_time_ms,
            # Length, not content — the extracted text itself is never logged.
            "text_length": len(result.text),
        },
    )

    latency_ms = int((time.perf_counter() - started) * 1000)
    return envelope(
        request_id,
        {
            "text": result.text,
            "success": result.success,
            "language": result.language,
            "error": result.error,
        },
        provider.model_version,
        latency_ms,
        confidence=result.confidence,
    )
