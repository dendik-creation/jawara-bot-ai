"""AI/ML Training Jobs — CRUD + lifecycle API (04_AI_and_ML/05_Training_Jobs.md)."""

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from app.core.security import require_operator
from app.schemas.training_jobs import TrainingJobActionRequest, TrainingJobCreateRequest
from app.services import training_jobs
from app.services.audit import record_audit
from app.services.auth import Operator

logger = logging.getLogger("app.api.training_jobs")

router = APIRouter(dependencies=[Depends(require_operator)])


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.get("/training-jobs")
async def list_training_jobs(
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    status_: str | None = Query(default=None, alias="status"),
) -> dict[str, object]:
    try:
        return {"available": True, **(await training_jobs.list_training_jobs(limit, offset, status=status_))}
    except Exception:  # noqa: BLE001
        logger.error("training jobs query failed", exc_info=True)
        return {"available": False, "reason": "database_unavailable", "items": [], "total": 0}


@router.get("/training-jobs/{job_id}")
async def get_training_job(job_id: UUID) -> dict[str, object]:
    result = await training_jobs.get_training_job(str(job_id))
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="training job not found")
    return result


@router.post("/training-jobs", status_code=status.HTTP_201_CREATED)
async def create_training_job(
    payload: TrainingJobCreateRequest, request: Request, operator: Operator = Depends(require_operator)
) -> dict[str, object]:
    try:
        result = await training_jobs.create_training_job(
            payload.dataset_id,
            payload.base_model,
            operator.id,
            epochs=payload.epochs,
            learning_rate=payload.learning_rate,
            batch_size=payload.batch_size,
            validation_split=payload.validation_split,
            extra_config=payload.extra_config,
        )
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from None

    await record_audit(
        actor_operator_id=operator.id,
        action="training_job.created",
        target_type="training_job",
        target_id=result["id"],
        result="SUCCESS",
        metadata={"dataset_id": payload.dataset_id, "base_model": payload.base_model},
        ip_address=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return result


@router.patch("/training-jobs/{job_id}")
async def action_on_training_job(
    job_id: UUID,
    payload: TrainingJobActionRequest,
    request: Request,
    operator: Operator = Depends(require_operator),
) -> dict[str, object]:
    try:
        result = await training_jobs.apply_job_action(str(job_id), action=payload.action)
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from None

    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="training job not found")

    await record_audit(
        actor_operator_id=operator.id,
        action="training_job.cancelled",
        target_type="training_job",
        target_id=str(job_id),
        result="SUCCESS",
        metadata={"action": payload.action},
        ip_address=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return result
