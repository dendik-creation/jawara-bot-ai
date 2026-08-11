"""Audit Log — read API for the operator action trail (09_Security/05_Audit_Logs.md).

Write access is not exposed here on purpose: entries are created only by
`app.services.audit.record_audit`, called from wherever a mutation happens
(today: `auth.py`). There is no POST/PATCH/DELETE route on this router,
matching the spec's append-only requirement.
"""

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, Query

from app.core.security import require_operator
from app.services import audit

logger = logging.getLogger("app.api.audit")

router = APIRouter(dependencies=[Depends(require_operator)])


@router.get("/audit-log")
async def list_audit_log(
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    action: str | None = Query(default=None),
    actor_operator_id: str | None = Query(default=None),
    target_type: str | None = Query(default=None),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
) -> dict[str, object]:
    try:
        return {
            "available": True,
            **(
                await audit.list_audit_log(
                    limit,
                    offset,
                    action=action,
                    actor_operator_id=actor_operator_id,
                    target_type=target_type,
                    date_from=date_from,
                    date_to=date_to,
                )
            ),
        }
    except Exception:  # noqa: BLE001
        logger.error("audit log query failed", exc_info=True)
        return {"available": False, "reason": "database_unavailable", "items": [], "total": 0}
