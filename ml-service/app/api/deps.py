"""Request-scoped helpers shared by the `/v1` endpoints."""

import time
from typing import Any

from fastapi import Request

from app.rag.qdrant_repo import QdrantRepository
from app.schemas.contract import MlResponse


def get_repository(request: Request) -> QdrantRepository:
    """The process-wide Qdrant repository, created once in the lifespan hook."""
    return request.app.state.qdrant


class Timer:
    """Measures one inference so `latency_ms` is the service's own view of cost."""

    def __enter__(self) -> "Timer":
        self._start = time.perf_counter()
        return self

    def __exit__(self, *_: object) -> None:
        self.elapsed_ms = int((time.perf_counter() - self._start) * 1000)

    elapsed_ms: int = 0


def envelope(
    request_id: str,
    result: dict[str, Any],
    model_version: str,
    latency_ms: int,
    confidence: float | None = None,
) -> MlResponse:
    return MlResponse(
        request_id=request_id,
        result=result,
        model_version=model_version,
        confidence=confidence,
        latency_ms=latency_ms,
    )
