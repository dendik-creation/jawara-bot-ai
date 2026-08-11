"""Incidents — grouping, lifecycle, and case-file API (08_Dashboard/05_Incident_Management.md).

Manual/operator-confirmed grouping only — automatic correlation is Post-MVP.
See `app.services.incidents` for the state-machine rules this route enforces
via `ValueError` -> 400 (SET_STATE targets, CLOSE's reason requirement).
"""

import logging
from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from app.core.security import require_operator
from app.schemas.incidents import AddNoteRequest, AddThreatRequest, CreateIncidentRequest, IncidentActionRequest
from app.services import alerts, incidents
from app.services.audit import record_audit
from app.services.auth import Operator

logger = logging.getLogger("app.api.incidents")

router = APIRouter(dependencies=[Depends(require_operator)])


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.get("/incidents")
async def list_incidents(
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    severity: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"] | None = Query(default=None),
    state: Literal["OPEN", "INVESTIGATING", "CONTAINED", "RESOLVED", "FALSE_POSITIVE"] | None = Query(default=None),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
) -> dict[str, object]:
    try:
        return {
            "available": True,
            **(
                await incidents.list_incidents(
                    limit, offset, severity=severity, state=state, date_from=date_from, date_to=date_to
                )
            ),
        }
    except Exception:  # noqa: BLE001
        logger.error("incidents query failed", exc_info=True)
        return {"available": False, "reason": "database_unavailable", "items": [], "total": 0}


@router.post("/incidents", status_code=status.HTTP_201_CREATED)
async def create_incident(
    payload: CreateIncidentRequest, request: Request, operator: Operator = Depends(require_operator)
) -> dict[str, object]:
    try:
        result = await incidents.create_incident(
            payload.title, payload.severity, payload.message_log_ids, operator.id
        )
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from None

    await record_audit(
        actor_operator_id=operator.id,
        action="incident.created",
        target_type="incident",
        target_id=result["id"],
        result="SUCCESS",
        metadata={"title": payload.title, "severity": payload.severity, "message_log_ids": payload.message_log_ids},
        ip_address=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return result


@router.get("/incidents/{incident_id}")
async def get_incident(incident_id: UUID) -> dict[str, object]:
    result = await incidents.get_incident(str(incident_id))
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="incident not found")
    return result


@router.patch("/incidents/{incident_id}")
async def action_on_incident(
    incident_id: UUID,
    payload: IncidentActionRequest,
    request: Request,
    operator: Operator = Depends(require_operator),
) -> dict[str, object]:
    if payload.action == "ESCALATE":
        incident = await incidents.get_incident(str(incident_id))
        if incident is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="incident not found")

        alert = await alerts.create_from_incident_escalation(
            str(incident_id), severity=incident["severity"], title=incident["title"]
        )
        await record_audit(
            actor_operator_id=operator.id,
            action="incident.action_taken",
            target_type="incident",
            target_id=str(incident_id),
            result="SUCCESS",
            metadata={"action": "ESCALATE", "alert_id": alert["id"]},
            ip_address=_client_ip(request),
            user_agent=request.headers.get("user-agent"),
        )
        return incident

    try:
        result = await incidents.apply_incident_action(
            str(incident_id),
            action=payload.action,
            state=payload.state,
            severity=payload.severity,
            reason=payload.reason,
            actor_operator_id=operator.id,
        )
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from None

    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="incident not found")

    previous_severity = result.pop("previous_severity", None)
    await record_audit(
        actor_operator_id=operator.id,
        action="incident.action_taken",
        target_type="incident",
        target_id=str(incident_id),
        result="SUCCESS",
        metadata={
            "action": payload.action,
            "state": payload.state,
            "old_severity": previous_severity,
            "new_severity": payload.severity if payload.action == "SET_SEVERITY" else None,
            "reason": payload.reason,
        },
        ip_address=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return result


@router.post("/incidents/{incident_id}/threats")
async def add_threat(
    incident_id: UUID,
    payload: AddThreatRequest,
    request: Request,
    operator: Operator = Depends(require_operator),
) -> dict[str, object]:
    try:
        result = await incidents.add_threat_to_incident(str(incident_id), payload.message_log_id, operator.id)
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from None

    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="incident not found")

    await record_audit(
        actor_operator_id=operator.id,
        action="incident.threat_added",
        target_type="incident",
        target_id=str(incident_id),
        result="SUCCESS",
        metadata={"message_log_id": payload.message_log_id},
        ip_address=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return result


@router.delete("/incidents/{incident_id}/threats/{message_log_id}")
async def remove_threat(
    incident_id: UUID,
    message_log_id: UUID,
    request: Request,
    operator: Operator = Depends(require_operator),
) -> dict[str, object]:
    result = await incidents.remove_threat_from_incident(str(incident_id), str(message_log_id))
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="incident or linked threat not found")

    await record_audit(
        actor_operator_id=operator.id,
        action="incident.threat_removed",
        target_type="incident",
        target_id=str(incident_id),
        result="SUCCESS",
        metadata={"message_log_id": str(message_log_id)},
        ip_address=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return result


@router.post("/incidents/{incident_id}/notes")
async def add_note(
    incident_id: UUID,
    payload: AddNoteRequest,
    request: Request,
    operator: Operator = Depends(require_operator),
) -> dict[str, object]:
    result = await incidents.add_note(str(incident_id), payload.note, operator.id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="incident not found")

    await record_audit(
        actor_operator_id=operator.id,
        action="incident.note_added",
        target_type="incident",
        target_id=str(incident_id),
        result="SUCCESS",
        metadata={"note": payload.note},
        ip_address=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return result
