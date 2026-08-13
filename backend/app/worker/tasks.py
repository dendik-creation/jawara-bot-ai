import asyncio
import logging
from typing import Any

from pydantic import ValidationError

from app.clients.waha_client import WahaClient
from app.core.config import get_settings
from app.pipeline.orchestrator import process_message_job
from app.schemas.queue import MessageJob
from app.worker.celery_app import (
    TASK_INGEST_FACT_CHECKS,
    TASK_PROCESS_MESSAGE,
    TASK_RUN_MODEL_EVALUATION,
    TASK_RUN_TRAINING_JOB,
    celery_app,
)

logger = logging.getLogger("app.worker.tasks")

_settings = get_settings()

# Last-resort reply when a `!cek`/`!link` job fails for a reason the pipeline
# itself never degrades around (JAWARA no-silent-failure requirement: every
# explicit command must end in SUCCESS or a USER_SAFE_FAILURE, never
# nothing). No internals — no exception name, no task id, no HTTP status.
GENERIC_FAILURE_REPLY = (
    "Maaf, JAWARA sedang mengalami kendala saat memproses permintaan Anda.\n\n"
    "Silakan coba lagi beberapa saat lagi."
)


@celery_app.task(
    bind=True,
    name=TASK_PROCESS_MESSAGE,
    max_retries=_settings.celery_max_retries,
)
def process_message(self, job: dict[str, Any]) -> dict[str, Any]:
    """Run one WAHA message through the preprocessing → verification → LLM pipeline.

    Retry is manual here (mirrors `ingest_fact_checks` below), not
    `autoretry_for`: a decorator-driven retry has no hook for "retries are
    now exhausted", and letting a job that backs an explicit `!cek`/`!link`
    command go quiet after N silent attempts is exactly the failure mode
    JAWARA's command system must not have. The pipeline itself already
    degrades around every failure it knows how to name (missing ML Service,
    missing threat-intel key, undeliverable WAHA send — see
    `02_Data_Pipeline.md §6`); what reaches this `except` is, by
    construction, something unexpected. Exponential backoff (2s, 4s, 8s...,
    capped) up to `max_retries`, then one best-effort, generic WhatsApp reply
    so the command still ends in a response the user can see, not a task
    that quietly stops.
    """
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

    try:
        result = run_pipeline(message, log_context)
    except Exception as exc:  # noqa: BLE001 — must never fall through silently, see docstring
        logger.error(
            "jawara.command.failed",
            extra={**log_context, "error": type(exc).__name__},
            exc_info=True,
        )
        if self.request.retries < self.max_retries:
            delay = _settings.celery_retry_backoff_seconds * (2**self.request.retries)
            raise self.retry(countdown=min(delay, _settings.celery_retry_backoff_max_seconds))

        _send_failure_reply(message, log_context)
        return {"status": "failed_safe_response_sent", "error": type(exc).__name__}

    logger.info("job completed", extra={**log_context, "result": result})
    return result


def _send_failure_reply(message: MessageJob, log_context: dict[str, Any]) -> None:
    """Best-effort final notice once retries are exhausted.

    Never raises: the real failure is already logged above with full
    context (`exc_info=True`), so a second failure here (WAHA also down)
    must not mask it or re-enter the retry machinery — it is only logged.
    """
    if not message.chat_id:
        logger.error("cannot send failure reply, no chat_id", extra=log_context)
        return
    try:
        asyncio.run(
            WahaClient(_settings).send_text(
                message.chat_id,
                GENERIC_FAILURE_REPLY,
                session=message.session,
                reply_to=message.waha_message_id,
            )
        )
    except Exception:  # noqa: BLE001 — best-effort notice, not a retry trigger
        logger.error("failed to deliver safe failure reply", extra=log_context, exc_info=True)


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


@celery_app.task(
    bind=True,
    name=TASK_INGEST_FACT_CHECKS,
    # No autoretry_for: a crawl fails for many reasons and only some are worth
    # repeating. The task inspects its own result and retries explicitly when
    # the *source* was unreachable — a malformed article or a rejected item
    # would fail identically on a redelivery, and the next scheduled tick is
    # already the retry for anything else.
    max_retries=_settings.celery_max_retries,
)
def ingest_fact_checks(self, source: str | None = None, triggered_by: str = "SCHEDULE") -> list[dict[str, Any]]:
    """Pull new fact-checks from the configured external sources.

    Runs on Celery Beat (`fact_ingestion_interval_minutes`) and on the
    operator's manual trigger — never as part of message processing: a user
    waiting on a WhatsApp reply must not be behind a crawl.
    """
    logger.info(
        "fact-check ingestion consumed",
        extra={"source": source or "all", "trigger": triggered_by, "task_id": self.request.id},
    )
    summaries = asyncio.run(_ingest_fact_checks(source, triggered_by))

    retryable = [s for s in summaries if s.get("status") == "FAILED" and s.get("retryable")]
    if retryable and self.request.retries < self.max_retries:
        delay = _settings.celery_retry_backoff_seconds * (2**self.request.retries)
        logger.warning(
            "fact-check ingestion retrying",
            extra={"sources": [s["source"] for s in retryable], "countdown": delay},
        )
        raise self.retry(countdown=delay)

    logger.info("fact-check ingestion finished", extra={"results": summaries})
    return summaries


async def _ingest_fact_checks(source: str | None, triggered_by: str) -> list[dict[str, Any]]:
    """Same one-event-loop-per-job bridge as `run_pipeline` — see its docstring."""
    from app.services.fact_ingestion import run_all_sources, run_ingestion

    if source:
        return [await run_ingestion(source, triggered_by=triggered_by)]
    return await run_all_sources(triggered_by=triggered_by)


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
