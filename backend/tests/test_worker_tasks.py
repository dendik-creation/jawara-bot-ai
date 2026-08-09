import logging

import pytest

from app.schemas.queue import MessageJob
from app.worker import celery_app
from app.worker import tasks as worker_tasks
from app.worker.tasks import TASK_PROCESS_MESSAGE, process_message

JOB = {
    "waha_message_id": "false_628111@c.us_ABCDEF",
    "session": "default",
    "event_name": "message.any",
    "chat_id": "628111@c.us",
    "event": {"payload": {"body": "hoaks?"}},
}


def test_task_registered_under_documented_name():
    assert TASK_PROCESS_MESSAGE in celery_app.tasks


def test_worker_config_matches_retry_policy():
    settings_max = process_message.max_retries
    assert settings_max == 3
    assert process_message.retry_backoff == 2
    assert process_message.retry_backoff_max == 60
    assert process_message.retry_jitter is True
    assert celery_app.conf.task_acks_late is True
    assert celery_app.conf.task_default_queue == "jawara.messages"


@pytest.fixture(autouse=True)
def stub_pipeline(monkeypatch):
    """Keep the task-level tests off the real pipeline.

    What is under test here is Celery wiring — registration, retry policy,
    envelope validation, log correlation. The pipeline itself has its own suite
    in `test_orchestrator.py`.
    """
    seen: list[MessageJob] = []

    async def fake_pipeline(message, log_context, settings=None):
        seen.append(message)
        return {"status": "processed", "intent": "HEALTH_HOAX"}

    monkeypatch.setattr(worker_tasks, "process_message_job", fake_pipeline)
    return seen


def test_valid_job_is_processed(stub_pipeline):
    result = process_message.run(JOB)
    assert result["status"] == "processed"
    assert stub_pipeline[0].waha_message_id == JOB["waha_message_id"]


def test_malformed_job_is_discarded_without_retry():
    result = process_message.run({"event_name": "message.any"})
    assert result == {"status": "discarded", "reason": "invalid_envelope"}


def test_logs_are_correlated_to_waha_message_id(caplog):
    with caplog.at_level(logging.INFO, logger="app.worker.tasks"):
        process_message.run(JOB)

    correlated = [r for r in caplog.records if getattr(r, "waha_message_id", None) == JOB["waha_message_id"]]
    assert len(correlated) >= 2  # consumed + completed


def test_job_envelope_round_trips():
    job = MessageJob.model_validate(JOB)
    assert job.model_dump(mode="json")["event"] == JOB["event"]
