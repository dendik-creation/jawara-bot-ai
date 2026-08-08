import logging
from typing import Any

from pydantic import ValidationError

from app.core.config import get_settings
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
    """Pipeline orchestration seam.

    Each stage lands here as its own task completes — the worker owns the
    ordering, the stages own the logic:
      1. preprocessing — [[Implement Text Normalizer]], [[Implement URL Extractor]]
      2. intent routing — [[Build Intent Router]]
      3. verification — [[Build Text Verification Pipeline]], [[Integrate Safe Browsing]],
         [[Integrate VirusTotal]]
      4. response — [[Generate LLM Responses]], [[Implement WhatsApp Response Sender]]
      5. audit log — [[Create Audit Logging]]
    """
    pending = [
        "preprocessing",
        "intent_routing",
        "verification",
        "response_generation",
        "audit_log",
    ]
    logger.info(
        "pipeline stages not yet implemented, job acked without downstream work",
        extra={**log_context, "pending_stages": pending},
    )
    return {"status": "accepted", "pending_stages": pending}
