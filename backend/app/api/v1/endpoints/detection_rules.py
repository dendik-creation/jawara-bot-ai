"""Detection Rules — CRUD + lifecycle API (09_Security/03_Detection_Rules.md).

Visible/manageable only this stage — see `app.services.detection_rules`
module docstring for why matching rules against live messages is a separate,
later follow-up.
"""

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from app.core.security import require_operator
from app.schemas.detection_rules import DetectionRuleActionRequest, DetectionRuleCreateRequest
from app.services import detection_rules
from app.services.audit import record_audit
from app.services.auth import Operator

logger = logging.getLogger("app.api.detection_rules")

router = APIRouter(dependencies=[Depends(require_operator)])


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.get("/detection-rules")
async def list_detection_rules(
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    rule_type: str | None = Query(default=None),
    status_: str | None = Query(default=None, alias="status"),
    severity: str | None = Query(default=None),
) -> dict[str, object]:
    try:
        return {
            "available": True,
            **(
                await detection_rules.list_detection_rules(
                    limit, offset, rule_type=rule_type, status=status_, severity=severity
                )
            ),
        }
    except Exception:  # noqa: BLE001
        logger.error("detection rules query failed", exc_info=True)
        return {"available": False, "reason": "database_unavailable", "items": [], "total": 0}


@router.post("/detection-rules", status_code=status.HTTP_201_CREATED)
async def create_detection_rule(
    payload: DetectionRuleCreateRequest, request: Request, operator: Operator = Depends(require_operator)
) -> dict[str, object]:
    try:
        result = await detection_rules.create_detection_rule(
            payload.name, payload.rule_type, payload.condition, payload.severity, operator.id
        )
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from None

    await record_audit(
        actor_operator_id=operator.id,
        action="detection_rule.created",
        target_type="detection_rule",
        target_id=result["id"],
        result="SUCCESS",
        metadata={"name": payload.name, "rule_type": payload.rule_type, "severity": payload.severity},
        ip_address=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return result


@router.patch("/detection-rules/{rule_id}")
async def action_on_detection_rule(
    rule_id: UUID,
    payload: DetectionRuleActionRequest,
    request: Request,
    operator: Operator = Depends(require_operator),
) -> dict[str, object]:
    try:
        result = await detection_rules.apply_rule_action(
            str(rule_id),
            action=payload.action,
            name=payload.name,
            condition=payload.condition,
            severity=payload.severity,
        )
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from None

    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="detection rule not found")

    previous_status = result.pop("previous_status", None)
    audit_action = "detection_rule.updated" if payload.action == "UPDATE" else "detection_rule.status_changed"
    await record_audit(
        actor_operator_id=operator.id,
        action=audit_action,
        target_type="detection_rule",
        target_id=str(rule_id),
        result="SUCCESS",
        metadata={
            "action": payload.action,
            "name": payload.name,
            "severity": payload.severity,
            "previous_status": previous_status,
            "new_status": result["status"] if payload.action != "UPDATE" else None,
        },
        ip_address=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return result
