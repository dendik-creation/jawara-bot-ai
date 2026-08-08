# Create Redis Queue

## Status

Done

## Priority

Critical

## Sprint

Sprint 1

## Deadline

2026-08-07

## Description

Push the validated webhook payload onto a Redis-backed queue immediately after the gateway's 200 OK response, and rate-limit inbound webhook requests per WhatsApp number/session in front of it.

## Background

Decouples the fast webhook ack from slow downstream processing, and prevents spam/DoS against the gateway. Rate-limit window/threshold aren't specified anywhere in the vault — a product decision, not just an implementation detail.

## Deliverables

- Redis broker configuration
- Enqueue call wired into the webhook handler
- Redis-backed rate limiter (sliding window or token bucket)
- Documented threshold/window values

## Dependencies

- [[Setup Docker Environment]]
- [[Implement FastAPI Gateway]]

## Acceptance Criteria

- Job appears in the Redis queue immediately after webhook ack
- Enqueue failure is logged and does not crash the webhook handler
- Payload round-trips intact (no data loss)
- Requests over rate-limit threshold return HTTP 429
- Legitimate burst (one user forwarding several messages) not falsely blocked

## Related Documentation

- [[02_Data_Pipeline]]
- [[01_System_Architecture]]

## Notes

Rate-limit default chosen and documented, not silent: **20 requests / 60s sliding window, keyed per `(session, chat_id)`** (`RATE_LIMIT_MAX_REQUESTS` / `RATE_LIMIT_WINDOW_SECONDS` in `.env`). Rationale: a user forwarding a batch of ~10 messages passes untouched, sustained flooding is cut at 20. Verified by flood test — 20 × `200`, then `429` with `Retry-After: 60`, while a second chat ID on the same session stayed unaffected. Revisit once real traffic exists; the value is config, not code.

Sliding window (Redis sorted set, `ZREMRANGEBYSCORE` + `ZADD` + `ZCARD`) rather than a fixed bucket — a fixed window lets a caller push 2× the limit across the reset boundary.

Two deliberate failure-mode decisions:
- **Rate limiter fails open.** Redis unreachable means requests are allowed and the failure logged. Dropping real user messages is worse than briefly not throttling.
- **Enqueue failure still acks 200** (`X-Queued: 0` header + error log). A non-200 makes WAHA retry the same event repeatedly, which does not help when Redis is the broken component.

Measured webhook ack: ~6ms, well inside the 200ms budget — the blocking kombu producer runs in a threadpool so a slow broker cannot stall the event loop.

**Implementation:** `backend/app/core/rate_limit.py`, `backend/app/core/redis_client.py`, `backend/app/services/queue.py`, `backend/app/schemas/queue.py`, wired in `backend/app/api/v1/endpoints/webhook.py`. Tests: `backend/tests/test_rate_limit.py`, `backend/tests/test_queue.py`, `backend/tests/test_webhook.py`.
