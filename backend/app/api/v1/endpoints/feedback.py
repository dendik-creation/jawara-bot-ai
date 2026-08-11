"""Operator Feedback — read API (04_AI_and_ML/04_Datasets_and_Operator_Feedback.md).

Feedback rows are only ever created as a side effect of
`PATCH /threats/{id}` — see `app.api.v1.endpoints.threats` — so this router
is list-only.
"""

import logging

from fastapi import APIRouter, Depends, Query

from app.core.security import require_operator
from app.services import feedback

logger = logging.getLogger("app.api.feedback")

router = APIRouter(dependencies=[Depends(require_operator)])


@router.get("/feedback")
async def list_feedback(
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    feedback_type: str | None = Query(default=None),
) -> dict[str, object]:
    try:
        return {"available": True, **(await feedback.list_feedback(limit, offset, feedback_type=feedback_type))}
    except Exception:  # noqa: BLE001
        logger.error("feedback query failed", exc_info=True)
        return {"available": False, "reason": "database_unavailable", "items": [], "total": 0}
