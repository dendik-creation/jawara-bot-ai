import asyncio
import logging
from typing import Any

from pydantic import ValidationError

from app.core.config import get_settings
from app.pipeline.orchestrator import process_message_job
from app.schemas.queue import MessageJob
from app.worker.celery_app import (
    TASK_PROCESS_MESSAGE,
    TASK_RUN_MODEL_EVALUATION,
    TASK_RUN_TRAINING_JOB,
    celery_app,
)

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


@celery_app.task(
    bind=True,
    name=TASK_RUN_TRAINING_JOB,
    # No autoretry: training must never be retried blindly (05_Training_Jobs
    # — the same reasoning `generate` isn't retried in MlClient). A real
    # failure (today: /v1/train doesn't exist) is a real FAILED job, not
    # something to silently resubmit.
)
def run_training_job(self, job_id: str) -> None:
    """Run one training job through the (currently unimplemented) ML Service
    training call. See `app.services.training_jobs.execute_training_job`.
    """
    logger.info("training job consumed", extra={"job_id": job_id, "task_id": self.request.id})
    asyncio.run(_run_training_job(job_id))
    logger.info("training job task finished", extra={"job_id": job_id})


async def _run_training_job(job_id: str) -> None:
    """Same one-event-loop-per-job bridge as `run_pipeline` — see its docstring."""
    from app.services.training_jobs import execute_training_job

    await execute_training_job(job_id)


@celery_app.task(
    bind=True,
    name=TASK_RUN_MODEL_EVALUATION,
    # No autoretry: same reasoning as run_training_job — a real failure
    # (today: /v1/evaluate doesn't exist) is a real FAILED evaluation, not
    # something to silently resubmit.
)
def run_model_evaluation(self, evaluation_id: str) -> None:
    """Run one model evaluation through the (currently unimplemented) ML
    Service evaluate call. See `app.services.model_evaluations.execute_model_evaluation`.
    """
    logger.info("model evaluation consumed", extra={"evaluation_id": evaluation_id, "task_id": self.request.id})
    asyncio.run(_run_model_evaluation(evaluation_id))
    logger.info("model evaluation task finished", extra={"evaluation_id": evaluation_id})


async def _run_model_evaluation(evaluation_id: str) -> None:
    """Same one-event-loop-per-job bridge as `run_pipeline` — see its docstring."""
    from app.services.model_evaluations import execute_model_evaluation

    await execute_model_evaluation(evaluation_id)


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
