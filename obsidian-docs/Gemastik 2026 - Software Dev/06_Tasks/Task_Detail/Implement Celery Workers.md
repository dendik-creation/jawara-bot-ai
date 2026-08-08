# Implement Celery Workers

## Status

Done

## Priority

Critical

## Sprint

Sprint 1

## Deadline

2026-08-07

## Description

Stand up the `celery-worker` service consuming from Redis and executing the preprocessing → verification → LLM pipeline per job.

## Background

All downstream AI/verification work for Sprint 1 (text normalization, URL extraction, intent routing, RAG, LLM response) executes here, off the request path.

## Deliverables

- Celery app config (`app.worker`)
- Worker container wired to Redis broker and Postgres/Qdrant connections

## Dependencies

- [[Create Redis Queue]]

## Acceptance Criteria

- Worker consumes and acks jobs from the queue
- Failed tasks retry per a documented policy (retry count/backoff — decide during implementation)
- Worker logs are correlated to the originating `waha_message_id`

## Related Documentation

- [[01_System_Architecture]]
- [[03_Tech_Stack]]

## Notes

**Retry policy (decided here):** max 3 retries, exponential backoff base 2s capped at 60s, with jitter so a broker/API outage doesn't produce a synchronised retry stampede. `task_acks_late=True` + `task_reject_on_worker_lost=True` — a worker killed mid-pipeline returns the job to the queue instead of dropping a user's message. `worker_prefetch_multiplier=1`, because OCR/RAG/LLM steps are slow and prefetching would park jobs in a busy worker while another idles. Malformed job envelopes are **discarded, not retried** (`{"status": "discarded"}`) — a payload that fails schema validation will fail identically on redelivery.

**Log correlation:** structured JSON logging (`backend/app/core/logging.py`) so `extra=` fields survive into output — the stdlib formatter silently drops them. Every worker line carries `waha_message_id`, `session`, `chat_id`, `task_id`, `retries`.

Queue name is explicit (`jawara.messages`, not Celery's default `celery`) so queue depth is inspectable: `redis-cli LLEN jawara.messages`. Broker is Redis DB 0, result backend DB 1 — a `FLUSHDB` on either does not take out the other.

The gateway sends by **task name** (`celery_app.send_task`), never by importing the task function, so worker/ML dependencies stay out of the request path.

Pipeline stages are seams, not stubs-forever: `run_pipeline()` in `app/worker/tasks.py` lists the five pending stages and the task that fills each one ([[Implement Text Normalizer]], [[Build Intent Router]], [[Build Text Verification Pipeline]], [[Generate LLM Responses]], [[Create Audit Logging]]). Until those land, jobs are consumed and acked with `pending_stages` recorded in the log line.

Verified end to end: `POST /api/v1/webhook` → Redis → worker consumed and acked the job, `waha_message_id` matching across gateway and worker logs.

**Windows dev caveat:** Celery's prefork pool doesn't work on Windows — use `--pool=solo` locally. The container (Linux) uses the default prefork pool, unchanged.

**Implementation:** `backend/app/worker/{__init__,celery_app,tasks}.py`. Tests: `backend/tests/test_worker_tasks.py`.

Also fixed while wiring the worker: `celery-worker` waits on `qdrant: service_healthy`, and that healthcheck could never pass — the `qdrant/qdrant` image ships no `wget`/`curl`. Replaced with a bash `/dev/tcp` HTTP probe. Same class of bug on `waha` (`/` returns 401 once dashboard credentials are set, so `wget` exited 6 forever) — now probes `/ping`.
