import logging

import pytest

from app.core.config import Settings
from app.schemas.queue import MessageJob
from app.worker import celery_app
from app.worker import tasks as worker_tasks
from app.worker.celery_app import BEAT_INGEST_FACT_CHECKS, _beat_schedule
from app.worker.tasks import TASK_INGEST_FACT_CHECKS, TASK_PROCESS_MESSAGE, process_message

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
    # Retry is manual (see the task docstring) so its backoff comes from
    # settings, read directly in the `except` branch, rather than Celery's
    # `retry_backoff*` decorator kwargs.
    assert process_message.max_retries == 3
    from app.core.config import get_settings

    settings = get_settings()
    assert settings.celery_retry_backoff_seconds == 2
    assert settings.celery_retry_backoff_max_seconds == 60
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


# --------------------------------------------------------------------------
# No silent failure: a genuinely unexpected pipeline exception must still
# end in either a retry or a delivered, user-safe WhatsApp reply — never
# nothing (JAWARA no-silent-failure requirement).
# --------------------------------------------------------------------------


def test_unexpected_pipeline_failure_asks_celery_for_a_retry(monkeypatch):
    async def failing_pipeline(message, log_context, settings=None):
        raise RuntimeError("boom")

    monkeypatch.setattr(worker_tasks, "process_message_job", failing_pipeline)

    from celery.exceptions import Retry

    with pytest.raises(Retry):
        process_message.run(JOB)


def test_exhausted_retries_sends_a_safe_reply_instead_of_failing_silently(monkeypatch):
    async def failing_pipeline(message, log_context, settings=None):
        raise RuntimeError("boom")

    sent: list[dict] = []

    class FakeWaha:
        def __init__(self, settings=None):
            pass

        async def send_text(self, chat_id, text, session="default", reply_to=None):
            sent.append({"chat_id": chat_id, "text": text, "reply_to": reply_to})

    monkeypatch.setattr(worker_tasks, "process_message_job", failing_pipeline)
    monkeypatch.setattr(worker_tasks, "WahaClient", FakeWaha)
    # Simulate "this was the last attempt" without needing a real Celery
    # worker to actually exhaust three retries end to end.
    monkeypatch.setattr(worker_tasks.process_message, "max_retries", 0)

    result = process_message.run(JOB)

    assert result == {"status": "failed_safe_response_sent", "error": "RuntimeError"}
    assert sent == [
        {
            "chat_id": JOB["chat_id"],
            "text": worker_tasks.GENERIC_FAILURE_REPLY,
            "reply_to": JOB["waha_message_id"],
        }
    ]


def test_exhausted_retries_never_raises_even_without_a_chat_id(monkeypatch):
    """No chat to reply to is itself a degraded case, not a crash — the task
    must still end cleanly rather than raise a second, unrelated exception."""

    async def failing_pipeline(message, log_context, settings=None):
        raise RuntimeError("boom")

    monkeypatch.setattr(worker_tasks, "process_message_job", failing_pipeline)
    monkeypatch.setattr(worker_tasks.process_message, "max_retries", 0)

    result = process_message.run({**JOB, "chat_id": None})

    assert result["status"] == "failed_safe_response_sent"


def test_exhausted_retries_with_waha_also_down_still_returns_cleanly(monkeypatch):
    """The failure notice itself failing to send must not mask the original
    error or throw the task back into the retry machinery."""

    async def failing_pipeline(message, log_context, settings=None):
        raise RuntimeError("boom")

    class FailingWaha:
        def __init__(self, settings=None):
            pass

        async def send_text(self, *a, **k):
            raise ConnectionError("waha unreachable")

    monkeypatch.setattr(worker_tasks, "process_message_job", failing_pipeline)
    monkeypatch.setattr(worker_tasks, "WahaClient", FailingWaha)
    monkeypatch.setattr(worker_tasks.process_message, "max_retries", 0)

    result = process_message.run(JOB)

    assert result == {"status": "failed_safe_response_sent", "error": "RuntimeError"}


# --------------------------------------------------------------------------
# Scheduled fact-check ingestion
# --------------------------------------------------------------------------


def test_ingestion_task_is_registered():
    assert TASK_INGEST_FACT_CHECKS in celery_app.tasks


def test_beat_schedules_ingestion_on_the_configured_interval():
    schedule = _beat_schedule(Settings(fact_ingestion_enabled=True, fact_ingestion_interval_minutes=30))

    entry = schedule[BEAT_INGEST_FACT_CHECKS]
    assert entry["task"] == TASK_INGEST_FACT_CHECKS
    assert entry["schedule"].total_seconds() == 30 * 60
    # Its own queue: a crawl must never sit in front of a user's message.
    assert entry["options"]["queue"] == "jawara.ingestion"


def test_beat_schedules_nothing_when_ingestion_is_disabled():
    assert _beat_schedule(Settings(fact_ingestion_enabled=False)) == {}


def test_ingestion_task_runs_every_configured_source(monkeypatch):
    seen: list[tuple[str | None, str]] = []

    async def fake_run_all(*, triggered_by="SCHEDULE", settings=None):
        seen.append((None, triggered_by))
        return [{"source": "turnbackhoax", "status": "SUCCESS", "created": 2, "retryable": False}]

    monkeypatch.setattr("app.services.fact_ingestion.run_all_sources", fake_run_all)

    result = worker_tasks.ingest_fact_checks.run()

    assert seen == [(None, "SCHEDULE")]
    assert result[0]["created"] == 2


def test_manual_trigger_targets_one_source(monkeypatch):
    seen: list[tuple[str, str]] = []

    async def fake_run(slug, *, triggered_by="SCHEDULE", settings=None):
        seen.append((slug, triggered_by))
        return {"source": slug, "status": "SUCCESS", "retryable": False}

    monkeypatch.setattr("app.services.fact_ingestion.run_ingestion", fake_run)

    worker_tasks.ingest_fact_checks.run(source="turnbackhoax", triggered_by="MANUAL")

    assert seen == [("turnbackhoax", "MANUAL")]


def test_unreachable_source_asks_celery_for_a_retry(monkeypatch):
    """A 503 from the source is worth another attempt; a malformed article is
    not, which is why the task inspects its own result instead of using
    `autoretry_for`."""

    async def fake_run_all(*, triggered_by="SCHEDULE", settings=None):
        return [{"source": "turnbackhoax", "status": "FAILED", "retryable": True, "error": "HTTP 503"}]

    monkeypatch.setattr("app.services.fact_ingestion.run_all_sources", fake_run_all)

    from celery.exceptions import Retry

    with pytest.raises(Retry):
        worker_tasks.ingest_fact_checks.run()


def test_item_level_failure_does_not_ask_for_a_retry(monkeypatch):
    async def fake_run_all(*, triggered_by="SCHEDULE", settings=None):
        return [{"source": "turnbackhoax", "status": "PARTIAL", "retryable": False, "failed": 1}]

    monkeypatch.setattr("app.services.fact_ingestion.run_all_sources", fake_run_all)

    assert worker_tasks.ingest_fact_checks.run()[0]["status"] == "PARTIAL"
