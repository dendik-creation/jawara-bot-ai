"""Threats — read + resolve API (08_Dashboard/03_Threat_Monitoring.md).

A threat is any `message_logs` row with `risk_score IN ('HIGH','MEDIUM')`; see
`app.services.threats` for why there is no separate threats table and why
`state` is computed rather than stored.
"""

import logging
from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from app.core.security import require_operator
from app.pipeline.threat_categories import ThreatCategory
from app.schemas.threats import ThreatActionRequest
from app.services import alerts, feedback, threats
from app.services.audit import record_audit
from app.services.auth import Operator

logger = logging.getLogger("app.api.threats")

router = APIRouter(dependencies=[Depends(require_operator)])


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.get("/threats")
async def list_threats(
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    severity: Literal["HIGH", "MEDIUM"] | None = Query(default=None),
    category: ThreatCategory | None = Query(default=None),
    state: Literal["DETECTED", "ANALYZED", "ACTIONED", "RESOLVED"] | None = Query(default=None),
    action: Literal["ALLOW", "WARN", "BLOCK", "ESCALATE", "CONFIRM", "FALSE_POSITIVE"] | None = Query(default=None),
    user_hash: str | None = Query(default=None),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
) -> dict[str, object]:
    try:
        return {
            "available": True,
            **(
                await threats.list_threats(
                    limit,
                    offset,
                    severity=severity,
                    category=category,
                    state=state,
                    action=action,
                    user_hash=user_hash,
                    date_from=date_from,
                    date_to=date_to,
                )
            ),
        }
    except Exception:  # noqa: BLE001
        logger.error("threats query failed", exc_info=True)
        return {"available": False, "reason": "database_unavailable", "items": [], "total": 0}


@router.patch("/threats/{message_log_id}")
async def action_on_threat(
    message_log_id: UUID,
    payload: ThreatActionRequest,
    request: Request,
    operator: Operator = Depends(require_operator),
) -> dict[str, object]:
    result = await threats.action_on_threat(
        str(message_log_id),
        action=payload.action,
        notes=payload.notes,
        actor_operator_id=operator.id,
    )
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="threat not found")

    previous_action = result.pop("previous_action", None)

    alert_id: str | None = None
    if payload.action == "ESCALATE":
        # The one wired Alert source (see services/alerts.py) — an escalated
        # threat always raises a matching alert, no separate opt-in.
        alert = await alerts.create_from_threat_escalation(
            str(message_log_id), risk=result["risk"], threat_category=result["threat_category"]
        )
        alert_id = alert["id"]

    if payload.action in ("CONFIRM", "FALSE_POSITIVE"):
        # Human-in-the-loop signal for Datasets & Operator Feedback (Stage 10)
        # — only these two actions, matching the roadmap's own named scope.
        # Writes its own `feedback.recorded` audit entry.
        await feedback.record_feedback(
            str(message_log_id),
            payload.action,
            operator.id,
            reason=payload.notes,
        )

    await record_audit(
        actor_operator_id=operator.id,
        action="threat.action_taken",
        target_type="threat",
        target_id=str(message_log_id),
        result="SUCCESS",
        metadata={
            "action": payload.action,
            "notes": payload.notes,
            "previous_action": previous_action,
            "alert_id": alert_id,
        },
        ip_address=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    logger.info(
        "threat actioned",
        extra={"operator_id": operator.id, "message_log_id": str(message_log_id), "action": payload.action},
    )
    return result
