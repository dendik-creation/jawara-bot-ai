from celery import Celery
from celery.signals import setup_logging as setup_logging_signal

from app.core.config import get_settings
from app.core.logging import configure_logging

TASK_PROCESS_MESSAGE = "app.worker.tasks.process_message"


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
    )
    return celery


celery_app = create_celery()


@setup_logging_signal.connect
def _configure_worker_logging(**_: object) -> None:
    configure_logging(get_settings().log_level)
