"""Security Policies — CRUD + lifecycle API (09_Security/02_Security_Policies.md).

Visible/manageable only this stage — see `app.services.policies` module
docstring for why matching policies against live messages is a separate,
later follow-up.
"""

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from app.core.security import require_operator
from app.schemas.policies import PolicyActionRequest, PolicyCreateRequest
from app.services import policies
from app.services.audit import record_audit
from app.services.auth import Operator

logger = logging.getLogger("app.api.policies")

router = APIRouter(dependencies=[Depends(require_operator)])


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.get("/policies")
async def list_policies(
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    scope: str | None = Query(default=None),
    status_: str | None = Query(default=None, alias="status"),
    action: str | None = Query(default=None),
) -> dict[str, object]:
    try:
        return {
            "available": True,
            **(await policies.list_policies(limit, offset, scope=scope, status=status_, action=action)),
        }
    except Exception:  # noqa: BLE001
        logger.error("policies query failed", exc_info=True)
        return {"available": False, "reason": "database_unavailable", "items": [], "total": 0}


@router.post("/policies", status_code=status.HTTP_201_CREATED)
async def create_policy(
    payload: PolicyCreateRequest, request: Request, operator: Operator = Depends(require_operator)
) -> dict[str, object]:
    try:
        result = await policies.create_policy(
            payload.name, payload.scope, payload.condition, payload.action, payload.priority, operator.id
        )
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from None

    await record_audit(
        actor_operator_id=operator.id,
        action="policy.created",
        target_type="policy",
        target_id=result["id"],
        result="SUCCESS",
        metadata={"name": payload.name, "scope": payload.scope, "action": payload.action},
        ip_address=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return result


@router.patch("/policies/{policy_id}")
async def action_on_policy(
    policy_id: UUID,
    payload: PolicyActionRequest,
    request: Request,
    operator: Operator = Depends(require_operator),
) -> dict[str, object]:
    try:
        result = await policies.apply_policy_action(
            str(policy_id),
            operation=payload.operation,
            name=payload.name,
            condition=payload.condition,
            action=payload.action,
            priority=payload.priority,
        )
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from None

    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="policy not found")

    previous_status = result.pop("previous_status", None)
    audit_action = "policy.updated" if payload.operation == "UPDATE" else "policy.status_changed"
    await record_audit(
        actor_operator_id=operator.id,
        action=audit_action,
        target_type="policy",
        target_id=str(policy_id),
        result="SUCCESS",
        metadata={
            "operation": payload.operation,
            "name": payload.name,
            "action": payload.action,
            "previous_status": previous_status,
            "new_status": result["status"] if payload.operation != "UPDATE" else None,
        },
        ip_address=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return result
