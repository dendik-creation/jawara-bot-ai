# Create Redis Queue

## Status

ToDo

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

Don't invent a rate-limit number silently — confirm with product owner or document the chosen default explicitly.
