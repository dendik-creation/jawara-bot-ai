# Implement Celery Workers

## Status

ToDo

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

None
