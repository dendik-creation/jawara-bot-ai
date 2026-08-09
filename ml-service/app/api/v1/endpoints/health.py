"""Liveness and readiness — deliberately different questions.

`/v1/health` answers "is the process alive". `/v1/ready` answers "are the models
loaded and is the vector store reachable". Without the distinction an
orchestrator routes traffic to a container that is up but still loading weights,
and the first requests fail for no visible reason
(02_Architecture/04_ML_Service.md §6).
"""

from fastapi import APIRouter, Depends, Response, status

from app.api.deps import get_repository
from app.core.security import verify_internal_key
from app.models.registry import registry
from app.rag.qdrant_repo import QdrantRepository

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, str]:
    """Liveness. Unauthenticated: Docker's healthcheck has no API key."""
    return {"status": "ok"}


@router.get("/ready", dependencies=[Depends(verify_internal_key)])
async def ready(
    response: Response,
    repository: QdrantRepository = Depends(get_repository),
) -> dict[str, object]:
    models = registry.describe()

    try:
        vector_store = await repository.health()
        vector_ok = True
    except Exception as exc:  # noqa: BLE001 — probe reports, never raises
        vector_store = {"error": type(exc).__name__}
        vector_ok = False

    ready_now = bool(models["loaded"]) and vector_ok
    if not ready_now:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return {
        "status": "ready" if ready_now else "not_ready",
        "models": models,
        "vector_store": vector_store,
        "vector_store_reachable": vector_ok,
    }
