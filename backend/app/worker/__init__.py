from app.worker.celery_app import TASK_PROCESS_MESSAGE, celery_app

# `celery -A app.worker worker` resolves the Celery instance from this attribute.
app = celery_app

__all__ = ["TASK_PROCESS_MESSAGE", "app", "celery_app"]
