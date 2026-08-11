"""Users & Risk — end-user population read + block/unblock API
(08_Dashboard/07_Users_and_Risk.md). Not `operators` — see `app.services.users`
module docstring for the distinction.
"""

import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from app.core.security import require_operator
from app.schemas.users import UserActionRequest
from app.services import users
from app.services.audit import record_audit
from app.services.auth import Operator

logger = logging.getLogger("app.api.users")

router = APIRouter(dependencies=[Depends(require_operator)])


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.get("/users")
async def list_users(
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    tier: Literal["HIGH", "MEDIUM", "NONE"] | None = Query(default=None),
    chat_type: Literal["PERSONAL", "GROUP"] | None = Query(default=None),
    is_active: bool | None = Query(default=None),
    blocked: bool | None = Query(default=None),
) -> dict[str, object]:
    try:
        return {
            "available": True,
            **(
                await users.list_users(
                    limit, offset, tier=tier, chat_type=chat_type, is_active=is_active, blocked=blocked
                )
            ),
        }
    except Exception:  # noqa: BLE001
        logger.error("users query failed", exc_info=True)
        return {"available": False, "reason": "database_unavailable", "items": [], "total": 0}


@router.get("/users/{user_hash}")
async def get_user(user_hash: str) -> dict[str, object]:
    result = await users.get_user(user_hash)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user not found")
    return result


@router.patch("/users/{user_hash}")
async def action_on_user(
    user_hash: str,
    payload: UserActionRequest,
    request: Request,
    operator: Operator = Depends(require_operator),
) -> dict[str, object]:
    result = await users.apply_user_action(
        user_hash, action=payload.action, reason=payload.reason, actor_operator_id=operator.id
    )
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user not found")

    previous_blocked = result.pop("previous_blocked", None)
    await record_audit(
        actor_operator_id=operator.id,
        action="user.block_changed",
        target_type="user",
        target_id=user_hash,
        result="SUCCESS",
        metadata={"action": payload.action, "reason": payload.reason, "previous_blocked": previous_blocked},
        ip_address=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    logger.info("user block state changed", extra={"operator_id": operator.id, "user_hash": user_hash})
    return result
