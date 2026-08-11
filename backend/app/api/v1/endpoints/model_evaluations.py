"""AI/ML Model Evaluation — CRUD + lifecycle API (04_AI_and_ML/06_Model_Evaluation.md)."""

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from app.core.security import require_operator
from app.schemas.model_evaluations import ModelEvaluationActionRequest, ModelEvaluationCreateRequest
from app.services import model_evaluations
from app.services.audit import record_audit
from app.services.auth import Operator

logger = logging.getLogger("app.api.model_evaluations")

router = APIRouter(dependencies=[Depends(require_operator)])


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.get("/model-evaluations")
async def list_model_evaluations(
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    status_: str | None = Query(default=None, alias="status"),
) -> dict[str, object]:
    try:
        return {
            "available": True,
            **(await model_evaluations.list_model_evaluations(limit, offset, status=status_)),
        }
    except Exception:  # noqa: BLE001
        logger.error("model evaluations query failed", exc_info=True)
        return {"available": False, "reason": "database_unavailable", "items": [], "total": 0}


@router.get("/model-evaluations/{evaluation_id}")
async def get_model_evaluation(evaluation_id: UUID) -> dict[str, object]:
    result = await model_evaluations.get_model_evaluation(str(evaluation_id))
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="model evaluation not found")
    return result


@router.post("/model-evaluations", status_code=status.HTTP_201_CREATED)
async def create_model_evaluation(
    payload: ModelEvaluationCreateRequest, request: Request, operator: Operator = Depends(require_operator)
) -> dict[str, object]:
    try:
        result = await model_evaluations.create_model_evaluation(
            payload.training_job_id,
            payload.dataset_id,
            operator.id,
        )
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from None

    await record_audit(
        actor_operator_id=operator.id,
        action="model_evaluation.created",
        target_type="model_evaluation",
        target_id=result["id"],
        result="SUCCESS",
        metadata={"training_job_id": payload.training_job_id, "dataset_id": payload.dataset_id},
        ip_address=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return result


@router.patch("/model-evaluations/{evaluation_id}")
async def action_on_model_evaluation(
    evaluation_id: UUID,
    payload: ModelEvaluationActionRequest,
    request: Request,
    operator: Operator = Depends(require_operator),
) -> dict[str, object]:
    try:
        result = await model_evaluations.apply_evaluation_action(str(evaluation_id), action=payload.action)
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from None

    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="model evaluation not found")

    await record_audit(
        actor_operator_id=operator.id,
        action="model_evaluation.cancelled",
        target_type="model_evaluation",
        target_id=str(evaluation_id),
        result="SUCCESS",
        metadata={"action": payload.action},
        ip_address=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return result
