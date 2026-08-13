from datetime import timedelta

from celery import Celery
from celery.signals import setup_logging as setup_logging_signal

from app.core.config import get_settings
from app.core.logging import configure_logging

TASK_PROCESS_MESSAGE = "app.worker.tasks.process_message"
TASK_RUN_TRAINING_JOB = "app.worker.tasks.run_training_job"
TASK_RUN_MODEL_EVALUATION = "app.worker.tasks.run_model_evaluation"
TASK_INGEST_FACT_CHECKS = "app.worker.tasks.ingest_fact_checks"

BEAT_INGEST_FACT_CHECKS = "ingest-fact-checks"


def create_celery() -> Celery:
    settings = get_settings()
    celery = Celery(
        "jawara",
        broker=settings.celery_broker_url,
        backend=settings.celery_result_backend,
        include=["app.worker.tasks"],
    )
    celery.conf.update(
        task_default_queue=settings.celery_queue_name,
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        timezone="UTC",
        enable_utc=True,
        # Ack after the task body finishes, not on delivery: a worker killed
        # mid-pipeline returns the job to the queue instead of dropping a user's
        # message silently.
        task_acks_late=True,
        task_reject_on_worker_lost=True,
        # Pipeline steps are slow (OCR/RAG/LLM) — prefetching would park jobs in a
        # busy worker while another sits idle.
        worker_prefetch_multiplier=1,
        task_track_started=True,
        result_expires=3600,
        broker_connection_retry_on_startup=True,
        worker_hijack_root_logger=False,
        beat_schedule=_beat_schedule(settings),
    )
    return celery


def _beat_schedule(settings) -> dict[str, dict]:
    """Periodic work. Empty when ingestion is disabled — Beat then schedules
    nothing at all rather than firing a task that immediately returns.

    Interval comes from configuration, never a literal here: how often a
    fact-check source may politely be polled is a deployment decision, and
    the source's publishing rate can change without this code doing so.
    """
    if not settings.fact_ingestion_enabled:
        return {}
    return {
        BEAT_INGEST_FACT_CHECKS: {
            "task": TASK_INGEST_FACT_CHECKS,
            "schedule": timedelta(minutes=settings.fact_ingestion_interval_minutes),
            "options": {
                "queue": settings.celery_ingestion_queue_name,
                # A crawl that outlives its own interval must not stack up
                # behind the next one: Beat drops a tick that is late by more
                # than the interval instead of queueing both.
                "expires": settings.fact_ingestion_interval_minutes * 60,
            },
        }
    }


celery_app = create_celery()


@setup_logging_signal.connect
def _configure_worker_logging(**_: object) -> None:
    configure_logging(get_settings().log_level)
