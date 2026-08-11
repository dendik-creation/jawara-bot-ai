"""The gateway's only door to the standalone ML Service.

Contract (02_Architecture/04_ML_Service.md §4):

    request   { request_id, payload, metadata }
    response  { request_id, result, confidence, model_version, latency_ms }
    error     { error_code, message, retryable }

`request_id` is the correlation ID carried from the WAHA webhook, so one message
can be traced WAHA → gateway → worker → ML Service → audit row.

Timeouts are per endpoint, carved out of the 3-second end-to-end budget. Retries
happen only on idempotent endpoints; `generate` is never retried blindly — a
duplicated generation costs real money and the caller has a fallback.
"""

import logging
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import Settings, get_settings

logger = logging.getLogger("app.clients.ml")

IDEMPOTENT_ENDPOINTS = frozenset({"classify", "embed", "rag-query"})


class MlServiceError(Exception):
    """Structured failure from (or on the way to) the ML Service."""

    def __init__(self, error_code: str, message: str, retryable: bool = False) -> None:
        super().__init__(f"{error_code}: {message}")
        self.error_code = error_code
        self.message = message
        self.retryable = retryable


@dataclass(frozen=True)
class MlResponse:
    """One inference result.

    `model_version` is mandatory: an audit row that cannot name the model which
    decided something is not an audit row.
    """

    request_id: str
    result: dict[str, Any]
    model_version: str
    confidence: float | None = None
    latency_ms: int | None = None


class MlClient:
    """Async client. One instance per pipeline run; cheap to construct."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    @property
    def enabled(self) -> bool:
        return self._settings.ml_enabled

    def _timeout(self, endpoint: str) -> float:
        return {
            "classify": self._settings.ml_timeout_classify_seconds,
            "embed": self._settings.ml_timeout_embed_seconds,
            "rag-query": self._settings.ml_timeout_rag_seconds,
            "generate": self._settings.ml_timeout_generate_seconds,
            "train": self._settings.ml_timeout_train_seconds,
            "evaluate": self._settings.ml_timeout_evaluate_seconds,
        }.get(endpoint, self._settings.ml_timeout_classify_seconds)

    async def _post(
        self,
        endpoint: str,
        request_id: str,
        payload: dict[str, Any],
        metadata: dict[str, Any] | None = None,
    ) -> MlResponse:
        if not self.enabled:
            raise MlServiceError("ml_disabled", "ML Service calls are disabled by config", retryable=False)

        url = f"{self._settings.ml_service_url.rstrip('/')}/v1/{endpoint}"
        body = {"request_id": request_id, "payload": payload, "metadata": metadata or {}}
        attempts = 2 if endpoint in IDEMPOTENT_ENDPOINTS else 1
        last_error: MlServiceError | None = None

        for attempt in range(attempts):
            try:
                async with httpx.AsyncClient(timeout=self._timeout(endpoint)) as client:
                    response = await client.post(
                        url,
                        json=body,
                        headers={"X-Internal-Api-Key": self._settings.ml_service_api_key},
                    )
            except httpx.TimeoutException as exc:
                last_error = MlServiceError("ml_timeout", str(exc), retryable=True)
            except httpx.HTTPError as exc:
                last_error = MlServiceError("ml_unreachable", str(exc), retryable=True)
            else:
                if response.status_code < 400:
                    data = response.json()
                    return MlResponse(
                        request_id=data.get("request_id", request_id),
                        result=data.get("result") or {},
                        model_version=data.get("model_version", "unknown"),
                        confidence=data.get("confidence"),
                        latency_ms=data.get("latency_ms"),
                    )
                last_error = _error_from_response(response)
                if not last_error.retryable:
                    break

            if attempt + 1 < attempts and last_error and last_error.retryable:
                logger.warning(
                    "ml service call failed, retrying",
                    extra={"endpoint": endpoint, "request_id": request_id, "error": last_error.error_code},
                )

        assert last_error is not None
        logger.warning(
            "ml service call failed",
            extra={"endpoint": endpoint, "request_id": request_id, "error": last_error.error_code},
        )
        raise last_error

    async def classify(self, request_id: str, text: str) -> MlResponse:
        return await self._post("classify", request_id, {"text": text})

    async def embed(self, request_id: str, texts: list[str]) -> MlResponse:
        return await self._post("embed", request_id, {"texts": texts})

    async def rag_query(
        self,
        request_id: str,
        query: str,
        category: str | None = None,
        top_k: int | None = None,
        score_threshold: float | None = None,
    ) -> MlResponse:
        return await self._post(
            "rag-query",
            request_id,
            {
                "query": query,
                "category": category,
                "top_k": top_k or self._settings.rag_top_k,
                "score_threshold": (
                    self._settings.rag_score_threshold if score_threshold is None else score_threshold
                ),
            },
        )

    async def generate(
        self,
        request_id: str,
        user_text: str,
        category: str | None,
        risk_level: str,
        context: list[dict[str, Any]] | None = None,
        url_verdicts: list[dict[str, Any]] | None = None,
    ) -> MlResponse:
        return await self._post(
            "generate",
            request_id,
            {
                "user_text": user_text,
                "category": category,
                "risk_level": risk_level,
                "context": context or [],
                "url_verdicts": url_verdicts or [],
            },
        )

    async def upsert_knowledge(self, request_id: str, items: list[dict[str, Any]]) -> MlResponse:
        """Embed and store fact items in Qdrant.

        Ingestion is orchestrated by the gateway, but the embedding and the
        Qdrant write belong to the ML Service (04_ML_Service.md §5).
        """
        return await self._post("kb/upsert", request_id, {"items": items})

    async def train(
        self,
        request_id: str,
        dataset_ref: dict[str, Any],
        base_model: str,
        config: dict[str, Any],
    ) -> MlResponse:
        """Kick off a training run (05_Training_Jobs.md).

        `/v1/train` doesn't exist in ml-service yet — this call is expected
        to raise `MlServiceError` today, and the caller (a Celery task) is
        expected to record that as a real, honest job failure rather than
        pretend training happened. Not idempotent — training must never be
        retried blindly (same reasoning as `generate`).
        """
        return await self._post(
            "train", request_id, {"dataset": dataset_ref, "base_model": base_model, "config": config}
        )

    async def evaluate(
        self,
        request_id: str,
        model_version: str,
        dataset_ref: dict[str, Any],
    ) -> MlResponse:
        """Score a trained model against a fixed eval dataset (06_Model_Evaluation.md).

        `/v1/evaluate` doesn't exist in ml-service yet — this call is expected
        to raise `MlServiceError` today, and the caller (a Celery task) is
        expected to record that as a real, honest evaluation failure rather
        than fabricate metrics. Not idempotent — same reasoning as `train`.
        """
        return await self._post(
            "evaluate", request_id, {"model_version": model_version, "dataset": dataset_ref}
        )

    async def ready(self) -> tuple[bool, dict[str, Any]]:
        """Readiness (models loaded), not liveness. Never raises."""
        url = f"{self._settings.ml_service_url.rstrip('/')}/v1/ready"
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                response = await client.get(
                    url, headers={"X-Internal-Api-Key": self._settings.ml_service_api_key}
                )
            return response.status_code < 400, response.json()
        except Exception as exc:  # noqa: BLE001 — health probes never propagate
            return False, {"error": str(exc)}


def _error_from_response(response: httpx.Response) -> MlServiceError:
    try:
        body = response.json()
    except ValueError:
        body = {}
    if isinstance(body, dict) and "error_code" in body:
        return MlServiceError(
            body.get("error_code", "ml_error"),
            body.get("message", response.text[:200]),
            bool(body.get("retryable", False)),
        )
    # A bare 5xx from a proxy or an unhandled exception: retryable, since it says
    # nothing about the request itself.
    return MlServiceError(
        "ml_http_error",
        f"HTTP {response.status_code}",
        retryable=response.status_code >= 500,
    )
