"""AI/ML Model Registry & Deployment — lifecycle API (04_AI_and_ML/07_Model_Registry_and_Deployment.md).

No `POST /model-versions`: a row is only ever system-created when a model
evaluation completes (`app.services.model_evaluations.execute_model_evaluation`)
— never by an operator request.
"""

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from app.core.security import require_operator
from app.schemas.model_versions import ModelVersionActionRequest
from app.services import model_versions
from app.services.audit import record_audit
from app.services.auth import Operator

logger = logging.getLogger("app.api.model_versions")

router = APIRouter(dependencies=[Depends(require_operator)])

_AUDIT_ACTION = {
    "VALIDATE": "model_version.validated",
    "PROMOTE": "model_version.promoted",
    "ARCHIVE": "model_version.archived",
}


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.get("/model-versions")
async def list_model_versions(
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    status_: str | None = Query(default=None, alias="status"),
) -> dict[str, object]:
    try:
        return {"available": True, **(await model_versions.list_model_versions(limit, offset, status=status_))}
    except Exception:  # noqa: BLE001
        logger.error("model versions query failed", exc_info=True)
        return {"available": False, "reason": "database_unavailable", "items": [], "total": 0}


@router.get("/model-versions/{model_version_id}")
async def get_model_version(model_version_id: UUID) -> dict[str, object]:
    result = await model_versions.get_model_version(str(model_version_id))
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="model version not found")
    return result


@router.patch("/model-versions/{model_version_id}")
async def action_on_model_version(
    model_version_id: UUID,
    payload: ModelVersionActionRequest,
    request: Request,
    operator: Operator = Depends(require_operator),
) -> dict[str, object]:
    try:
        result = await model_versions.apply_model_version_action(str(model_version_id), action=payload.action)
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from None

    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="model version not found")

    await record_audit(
        actor_operator_id=operator.id,
        action=_AUDIT_ACTION[payload.action],
        target_type="model_version",
        target_id=str(model_version_id),
        result="SUCCESS",
        metadata={"action": payload.action, "previous_status": result["previous_status"]},
        ip_address=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )

    demoted_version_id = result["demoted_version_id"]
    if demoted_version_id:
        await record_audit(
            actor_operator_id=operator.id,
            action="model_version.archived",
            target_type="model_version",
            target_id=demoted_version_id,
            result="SUCCESS",
            metadata={"reason": "auto_demoted_by_promotion", "promoted_version_id": str(model_version_id)},
            ip_address=_client_ip(request),
            user_agent=request.headers.get("user-agent"),
        )

    return result
