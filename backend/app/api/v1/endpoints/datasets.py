"""AI/ML Datasets — CRUD + lifecycle + samples API (04_AI_and_ML/04_Datasets_and_Operator_Feedback.md)."""

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from app.core.security import require_operator
from app.schemas.datasets import DatasetActionRequest, DatasetCreateRequest, DatasetSampleCreateRequest
from app.services import datasets
from app.services.audit import record_audit
from app.services.auth import Operator

logger = logging.getLogger("app.api.datasets")

router = APIRouter(dependencies=[Depends(require_operator)])


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.get("/datasets")
async def list_datasets(
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    status_: str | None = Query(default=None, alias="status"),
) -> dict[str, object]:
    try:
        return {"available": True, **(await datasets.list_datasets(limit, offset, status=status_))}
    except Exception:  # noqa: BLE001
        logger.error("datasets query failed", exc_info=True)
        return {"available": False, "reason": "database_unavailable", "items": [], "total": 0}


@router.get("/datasets/{dataset_id}")
async def get_dataset(dataset_id: UUID) -> dict[str, object]:
    result = await datasets.get_dataset(str(dataset_id))
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="dataset not found")
    return result


@router.post("/datasets", status_code=status.HTTP_201_CREATED)
async def create_dataset(
    payload: DatasetCreateRequest, request: Request, operator: Operator = Depends(require_operator)
) -> dict[str, object]:
    try:
        result = await datasets.create_dataset(
            payload.name, payload.version, payload.source, payload.description, operator.id
        )
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from None

    await record_audit(
        actor_operator_id=operator.id,
        action="dataset.created",
        target_type="dataset",
        target_id=result["id"],
        result="SUCCESS",
        metadata={"name": payload.name, "version": payload.version, "source": payload.source},
        ip_address=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return result


@router.patch("/datasets/{dataset_id}")
async def action_on_dataset(
    dataset_id: UUID,
    payload: DatasetActionRequest,
    request: Request,
    operator: Operator = Depends(require_operator),
) -> dict[str, object]:
    try:
        result = await datasets.apply_dataset_action(
            str(dataset_id), action=payload.action, name=payload.name, description=payload.description
        )
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from None

    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="dataset not found")

    previous_status = result.pop("previous_status", None)
    audit_action = "dataset.updated" if payload.action == "UPDATE" else "dataset.status_changed"
    await record_audit(
        actor_operator_id=operator.id,
        action=audit_action,
        target_type="dataset",
        target_id=str(dataset_id),
        result="SUCCESS",
        metadata={
            "action": payload.action,
            "previous_status": previous_status,
            "new_status": result["status"] if payload.action != "UPDATE" else None,
            "validation_notes": result.get("validation_notes"),
        },
        ip_address=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return result


@router.post("/datasets/{dataset_id}/samples", status_code=status.HTTP_201_CREATED)
async def add_dataset_sample(
    dataset_id: UUID,
    payload: DatasetSampleCreateRequest,
    request: Request,
    operator: Operator = Depends(require_operator),
) -> dict[str, object]:
    try:
        result = await datasets.add_sample(
            str(dataset_id),
            payload.text,
            payload.label,
            operator.id,
            source_message_log_id=payload.source_message_log_id,
            source_feedback_id=payload.source_feedback_id,
        )
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from None

    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="dataset not found")

    await record_audit(
        actor_operator_id=operator.id,
        action="dataset.sample_added",
        target_type="dataset",
        target_id=str(dataset_id),
        result="SUCCESS",
        metadata={"sample_id": result["id"], "label": payload.label},
        ip_address=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return result


@router.delete("/datasets/{dataset_id}/samples/{sample_id}")
async def remove_dataset_sample(
    dataset_id: UUID,
    sample_id: UUID,
    request: Request,
    operator: Operator = Depends(require_operator),
) -> dict[str, object]:
    try:
        outcome = await datasets.remove_sample(str(dataset_id), str(sample_id))
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from None

    if outcome is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="dataset not found")
    if outcome is False:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="sample not found")

    await record_audit(
        actor_operator_id=operator.id,
        action="dataset.sample_removed",
        target_type="dataset",
        target_id=str(dataset_id),
        result="SUCCESS",
        metadata={"sample_id": str(sample_id)},
        ip_address=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return {"removed": True}
