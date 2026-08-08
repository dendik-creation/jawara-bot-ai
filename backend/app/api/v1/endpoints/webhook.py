import logging

from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.core.config import get_settings
from app.core.rate_limit import check_rate_limit
from app.core.redis_client import get_redis
from app.core.security import verify_api_key
from app.schemas.webhook import SessionStatusEvent, WahaWebhookEvent
from app.services.queue import enqueue_message

logger = logging.getLogger("app.webhook")

router = APIRouter()


@router.post("/webhook", status_code=200, dependencies=[Depends(verify_api_key)])
async def receive_webhook(event: WahaWebhookEvent, response: Response) -> dict[str, str]:
    settings = get_settings()
    payload = event.payload or {}
    waha_message_id = payload.get("id")
    scope = f"{event.session}:{payload.get('from') or 'unknown'}"

    if settings.rate_limit_enabled:
        verdict = await check_rate_limit(get_redis(), settings, scope)
        if not verdict.allowed:
            logger.warning(
                "webhook rate limited",
                extra={"scope": scope, "count": verdict.current, "limit": verdict.limit},
            )
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Rate limit exceeded",
                headers={"Retry-After": str(verdict.retry_after)},
            )

    try:
        await enqueue_message(event)
        queued = True
    except Exception:
        # Broker down: log and still ack. A non-200 makes WAHA retry the same
        # event repeatedly, which does not help when Redis is the thing that is
        # broken — and a 500 here would surface as a crashed webhook handler.
        logger.error(
            "enqueue failed, event dropped",
            extra={"waha_message_id": waha_message_id, "session": event.session},
            exc_info=True,
        )
        queued = False

    logger.info(
        "waha event received",
        extra={
            "event": event.event,
            "session": event.session,
            "waha_message_id": waha_message_id,
            "queued": queued,
        },
    )
    response.headers["X-Queued"] = "1" if queued else "0"
    return {"status": "accepted"}


@router.post("/session/status", status_code=200, dependencies=[Depends(verify_api_key)])
async def receive_session_status(event: SessionStatusEvent) -> dict[str, str]:
    logger.info("waha session status", extra={"session": event.session, "payload": event.payload})
    return {"status": "accepted"}
