from app.worker.celery_app import (
    BEAT_INGEST_FACT_CHECKS,
    TASK_INGEST_FACT_CHECKS,
    TASK_PROCESS_MESSAGE,
    TASK_RUN_MODEL_EVALUATION,
    TASK_RUN_TRAINING_JOB,
    celery_app,
)

# `celery -A app.worker worker` resolves the Celery instance from this attribute.
app = celery_app

__all__ = [
    "BEAT_INGEST_FACT_CHECKS",
    "TASK_INGEST_FACT_CHECKS",
    "TASK_PROCESS_MESSAGE",
    "TASK_RUN_MODEL_EVALUATION",
    "TASK_RUN_TRAINING_JOB",
    "app",
    "celery_app",
]
