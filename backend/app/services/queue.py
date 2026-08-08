import logging

from fastapi.concurrency import run_in_threadpool

from app.core.config import get_settings
from app.schemas.queue import MessageJob
from app.schemas.webhook import WahaWebhookEvent
from app.worker import TASK_PROCESS_MESSAGE, celery_app

logger = logging.getLogger("app.queue")


def build_job(event: WahaWebhookEvent) -> MessageJob:
    payload = event.payload or {}
    return MessageJob(
        waha_message_id=payload.get("id"),
        session=event.session,
        event_name=event.event,
        chat_id=payload.get("from"),
        # Full event, extras included — the worker re-reads the raw WAHA fields the
        # gateway has no reason to understand.
        event=event.model_dump(),
    )


async def enqueue_message(event: WahaWebhookEvent) -> MessageJob:
    """Push one webhook event onto the Redis queue.

    Sent by task name, never by importing the task function: the gateway must not
    pull worker/ML dependencies into the request path.
    """
    settings = get_settings()
    job = build_job(event)

    # kombu's producer is blocking; off the event loop so a slow broker cannot
    # eat into the <200ms webhook ack budget.
    await run_in_threadpool(
        celery_app.send_task,
        TASK_PROCESS_MESSAGE,
        args=[job.model_dump(mode="json")],
        queue=settings.celery_queue_name,
    )
    return job
