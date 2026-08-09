import asyncio
import logging
from typing import Any

from pydantic import ValidationError

from app.core.config import get_settings
from app.pipeline.orchestrator import process_message_job
from app.schemas.queue import MessageJob
from app.worker.celery_app import TASK_PROCESS_MESSAGE, celery_app

logger = logging.getLogger("app.worker.tasks")

_settings = get_settings()


@celery_app.task(
    bind=True,
    name=TASK_PROCESS_MESSAGE,
    # Retry policy: up to 3 retries, exponential backoff (2s, 4s, 8s ... capped at
    # 60s) with jitter so a broker/API outage doesn't produce a synchronised
    # retry stampede. Malformed jobs are discarded instead (see below) — retrying
    # a job that can never parse just burns the queue.
    autoretry_for=(Exception,),
    max_retries=_settings.celery_max_retries,
    retry_backoff=_settings.celery_retry_backoff_seconds,
    retry_backoff_max=_settings.celery_retry_backoff_max_seconds,
    retry_jitter=True,
)
def process_message(self, job: dict[str, Any]) -> dict[str, Any]:
    """Run one WAHA message through the preprocessing → verification → LLM pipeline."""
    try:
        message = MessageJob.model_validate(job)
    except ValidationError as exc:
        # Non-retryable: the payload shape will not change on a redelivery.
        logger.error("job discarded, malformed envelope", extra={"errors": exc.errors()})
        return {"status": "discarded", "reason": "invalid_envelope"}

    log_context = {
        "waha_message_id": message.waha_message_id or "unknown",
        "session": message.session,
        "chat_id": message.chat_id,
        "task_id": self.request.id,
        "retries": self.request.retries,
    }
    logger.info("job consumed", extra=log_context)

    result = run_pipeline(message, log_context)

    logger.info("job completed", extra={**log_context, "result": result})
    return result


def run_pipeline(message: MessageJob, log_context: dict[str, Any]) -> dict[str, Any]:
    """Bridge from Celery's synchronous task body into the async pipeline.

    One event loop per job, created and torn down here. Celery's prefork pool
    gives each task a fresh call stack but no loop, and a module-level loop
    shared between jobs would keep connection pools bound to a loop that later
    tasks are not running on.

    The pipeline itself does not raise on downstream failures — it degrades and
    records what degraded. That is deliberate: Celery's retry would re-run
    *generation and dispatch*, so retrying a job that already replied to the user
    would send the reply twice. Only a malformed envelope (handled above) and a
    genuinely unexpected exception reach the retry policy.
    """
    return asyncio.run(process_message_job(message, log_context))
