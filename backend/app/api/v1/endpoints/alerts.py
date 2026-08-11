"""Alerts — read + action API (09_Security/04_Alert_Center.md).

Only one source is wired today (Threat `ESCALATE`, see `endpoints/threats.py`)
— see `app.services.alerts` module docstring for why `source` stays a plain
string rather than an enum locked to that one source.
"""

import logging
from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from app.core.security import require_operator
from app.schemas.alerts import AlertActionRequest
from app.services import alerts
from app.services.audit import record_audit
from app.services.auth import Operator

logger = logging.getLogger("app.api.alerts")

router = APIRouter(dependencies=[Depends(require_operator)])


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.get("/alerts")
async def list_alerts(
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    severity: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"] | None = Query(default=None),
    state: Literal["NEW", "ACKNOWLEDGED", "RESOLVED", "ESCALATED"] | None = Query(default=None),
    source: str | None = Query(default=None),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
) -> dict[str, object]:
    try:
        return {
            "available": True,
            **(
                await alerts.list_alerts(
                    limit,
                    offset,
                    severity=severity,
                    state=state,
                    source=source,
                    date_from=date_from,
                    date_to=date_to,
                )
            ),
        }
    except Exception:  # noqa: BLE001
        logger.error("alerts query failed", exc_info=True)
        return {"available": False, "reason": "database_unavailable", "items": [], "total": 0}


@router.patch("/alerts/{alert_id}")
async def action_on_alert(
    alert_id: UUID,
    payload: AlertActionRequest,
    request: Request,
    operator: Operator = Depends(require_operator),
) -> dict[str, object]:
    try:
        result = await alerts.apply_alert_action(
            str(alert_id),
            action=payload.action,
            reason=payload.reason,
            actor_operator_id=operator.id,
        )
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from None

    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="alert not found")

    await record_audit(
        actor_operator_id=operator.id,
        action="alert.action_taken",
        target_type="alert",
        target_id=str(alert_id),
        result="SUCCESS",
        metadata={"action": payload.action, "reason": payload.reason},
        ip_address=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    logger.info(
        "alert actioned", extra={"operator_id": operator.id, "alert_id": str(alert_id), "action": payload.action}
    )
    return result
