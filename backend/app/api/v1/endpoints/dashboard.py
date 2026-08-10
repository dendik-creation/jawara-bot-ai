"""Control Panel read APIs.

The browser talks to this gateway and to nothing else — never to WAHA, Qdrant,
Redis, PostgreSQL or the ML Service (08_Dashboard/01_Control_Panel_Overview.md
§4). Everything here is read-only, aggregate, and free of message content.

Auth: every endpoint here requires a signed-in operator (`app/core/security.py`,
`require_operator`). The old `DASHBOARD_API_KEY` shared secret is gone — it
authenticated a deployment rather than a person, and its "empty means open"
default meant the gate was off exactly where it was easiest to forget. RBAC is
still Planned: any operator who can sign in sees everything on this router.
"""

import asyncio
import logging
from collections.abc import AsyncIterator
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse

from app.core.config import get_settings
from app.core.redis_client import get_redis
from app.core.security import require_operator
from app.services import dashboard
from app.services.auth import Operator
from app.services.health import service_health
from app.services.message_log import ACTIVITY_CHANNEL

logger = logging.getLogger("app.api.dashboard")

# How long a subscriber waits for a Redis message before sending an SSE
# comment line to keep the connection alive through proxies/load balancers
# that time out an idle response.
STREAM_KEEPALIVE_SECONDS = 15.0

# One gate for the whole router: a new endpoint is protected by existing, not by
# the author remembering to add a dependency.
router = APIRouter(dependencies=[Depends(require_operator)])


@router.get("/dashboard/summary")
async def dashboard_summary() -> dict[str, object]:
    settings = get_settings()
    try:
        return {"available": True, **(await dashboard.summary(settings))}
    except Exception:  # noqa: BLE001
        logger.error("dashboard summary query failed", exc_info=True)
        return {
            "available": False,
            "reason": "database_unavailable",
            "window_hours": settings.dashboard_window_hours,
        }


@router.get("/dashboard/activity")
async def dashboard_activity(limit: int = Query(default=25, ge=1, le=100)) -> dict[str, object]:
    """Backfill for the Live Activity feed — the page's initial paint.

    `/dashboard/activity/stream` carries new events from the moment a client
    connects onward; it cannot hand over anything that happened before that,
    since Redis Pub/Sub has no history. This endpoint is what seeds the list
    on load. Transport decision closed 2026-08-10:
    (08_Dashboard/02_Command_Center.md §4, [[Open_Decisions_Carried_Forward]] §2.2).
    """
    settings = get_settings()
    try:
        return {"available": True, "transport": "sse", "items": await dashboard.recent_activity(limit, settings)}
    except Exception:  # noqa: BLE001
        logger.error("dashboard activity query failed", exc_info=True)
        return {"available": False, "reason": "database_unavailable", "items": []}


@router.get("/dashboard/activity/stream")
async def dashboard_activity_stream(request: Request) -> StreamingResponse:
    """Live Activity push over SSE, fed by the Redis Pub/Sub channel every
    successful `record_message()` publishes to.

    Not a native `EventSource` on the frontend: `EventSource` cannot send an
    `Authorization` header, and this gateway has no cookie-based session to
    fall back on (05_Product_Scope_and_Roadmap's auth is bearer-token only).
    Putting the token in the URL instead would leak it into access logs and
    any proxy in front of this gateway — worse than the extra fetch-based
    reader the frontend uses instead. See `frontend/hooks/use-activity-stream.ts`.

    Pub/Sub, not a queue or Redis Stream: a client that disconnects loses
    nothing it was owed, because nothing is queued for absent subscribers —
    matching "Live Activity" being a firehose an operator watches, not a feed
    they must not miss an item of.
    """
    redis = get_redis()
    pubsub = redis.pubsub()
    await pubsub.subscribe(ACTIVITY_CHANNEL)

    async def event_stream() -> AsyncIterator[str]:
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    message = await pubsub.get_message(
                        ignore_subscribe_messages=True, timeout=STREAM_KEEPALIVE_SECONDS
                    )
                except asyncio.CancelledError:
                    break
                if message is None:
                    yield ": keep-alive\n\n"
                    continue
                yield f"data: {message['data']}\n\n"
        finally:
            await pubsub.unsubscribe(ACTIVITY_CHANNEL)
            await pubsub.aclose()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            # Nginx/most reverse proxies buffer a streaming response by
            # default, which turns "live" into "arrives in one burst when the
            # buffer fills" — this header is the opt-out.
            "X-Accel-Buffering": "no",
            "Cache-Control": "no-cache",
        },
    )


@router.get("/dashboard/recent")
async def dashboard_recent(limit: int = Query(default=10, ge=1, le=50)) -> dict[str, object]:
    """Recent threats / incidents / alerts.

    Only threats have a data source today. Incidents and alerts report
    `available: false` rather than an empty list that would read as "none
    happened" (08_Dashboard, 05_Incident_Management and 04_Alert_Center are
    Planned).
    """
    settings = get_settings()
    try:
        threats = {"available": True, "items": await dashboard.recent_threats(limit, settings)}
    except Exception:  # noqa: BLE001
        logger.error("recent threats query failed", exc_info=True)
        threats = {"available": False, "reason": "database_unavailable", "items": []}

    return {
        "threats": threats,
        "incidents": dashboard.unavailable("incidents_table_not_implemented"),
        "alerts": dashboard.unavailable("alerts_table_not_implemented"),
    }


@router.get("/dashboard/messages")
async def dashboard_messages(
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> dict[str, object]:
    """Message Inspection list, `extracted_text` included.

    The only endpoint on this router that returns message content — see
    `services/dashboard.list_messages` for why that is deliberate here and
    nowhere else.
    """
    settings = get_settings()
    try:
        return {"available": True, **(await dashboard.list_messages(limit, offset, settings))}
    except Exception:  # noqa: BLE001
        logger.error("message log query failed", exc_info=True)
        return {"available": False, "reason": "database_unavailable", "items": [], "total": 0}


@router.delete("/dashboard/messages/{message_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_dashboard_message(
    message_id: UUID,
    operator: Operator = Depends(require_operator),
) -> None:
    """Permanently remove one message log row. No undo — there is no trash."""
    deleted = await dashboard.delete_message(str(message_id), get_settings())
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="message log not found")
    logger.info(
        "message log deleted",
        extra={"operator_id": operator.id, "message_log_id": str(message_id)},
    )


@router.get("/system/services")
async def system_services() -> dict[str, object]:
    return await service_health(get_settings())


@router.get("/whatsapp/sessions")
async def whatsapp_sessions() -> dict[str, object]:
    """Normalised WAHA session list — the frontend never calls WAHA itself."""
    from app.clients.waha_client import WahaClient

    sessions = await WahaClient(get_settings()).list_sessions()
    return {
        "available": bool(sessions),
        "active": sum(1 for session in sessions if session.get("status") == "WORKING"),
        "sessions": sessions,
    }
