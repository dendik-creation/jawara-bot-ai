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
