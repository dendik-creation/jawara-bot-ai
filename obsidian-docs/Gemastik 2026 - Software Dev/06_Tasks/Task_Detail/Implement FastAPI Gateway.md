# Implement FastAPI Gateway

## Status

Done

## Priority

Critical

## Sprint

Sprint 1

## Deadline

2026-08-07

## Description

Build `POST /api/v1/webhook` — receives WAHA's `message.any` event, verifies the `X-Api-Key` header, and responds `200 OK` within 200ms, deferring all heavy work to the queue. Include a health endpoint for basic monitoring.

## Background

Single ingress point for the entire pipeline; unauthenticated webhook acceptance would let anyone inject fake WhatsApp events, and the <200ms ack budget is a hard architectural constraint to avoid WAHA webhook retries/timeouts.

## Deliverables

- FastAPI project structure
- `/api/v1/webhook` route matching WAHA's `message.any` payload
- `X-Api-Key` auth middleware (401 on missing/invalid key)
- `/health` endpoint

## Dependencies

- [[Setup Docker Environment]]

## Acceptance Criteria

- Returns HTTP 200 within 200ms under normal load
- Rejects malformed payloads with 4xx, not a 500
- Auth failure returns 401 before any queue write
- `/health` returns 200 when dependencies (DB, Redis) are reachable
- Unit tests pass

## Related Documentation

- [[01_System_Architecture]]
- [[02_Data_Pipeline]]

## Notes

Do not perform OCR, RAG, or LLM calls synchronously in this handler — that breaks the 200ms budget. OCR/image handling itself is out of scope this sprint.
