import logging

from fastapi import APIRouter, Depends

from app.core.security import verify_api_key
from app.schemas.webhook import SessionStatusEvent, WahaWebhookEvent

logger = logging.getLogger("app.webhook")

router = APIRouter()


@router.post("/webhook", status_code=200, dependencies=[Depends(verify_api_key)])
async def receive_webhook(event: WahaWebhookEvent) -> dict[str, str]:
    # Enqueueing to Redis is Create Redis Queue's job — ack-only here to hold the 200ms budget.
    logger.info("waha event received", extra={"event": event.event, "session": event.session})
    return {"status": "accepted"}


@router.post("/session/status", status_code=200, dependencies=[Depends(verify_api_key)])
async def receive_session_status(event: SessionStatusEvent) -> dict[str, str]:
    logger.info("waha session status", extra={"session": event.session, "payload": event.payload})
    return {"status": "accepted"}
