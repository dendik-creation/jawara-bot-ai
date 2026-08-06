# Implement WhatsApp Response Sender

## Status

ToDo

## Priority

Critical

## Sprint

Sprint 1

## Deadline

2026-08-10

## Description

Send the formatted response back to the originating chat via WAHA's `POST /api/sendText`.

## Background

Final step of the pipeline — closes the loop from inbound webhook to outbound reply, the milestone's "system can reply through WhatsApp" criterion.

## Deliverables

- WAHA REST client (`POST /api/sendText` with `chatId`/`text` payload)
- Retry-on-transient-failure logic

## Dependencies

- [[Generate LLM Responses]]
- [[Configure WAHA]]

## Acceptance Criteria

- Response delivered to the correct `chatId`
- Delivery failure is retried at least once and logged if still failing
- End-to-end webhook-to-dispatch latency measured and logged against the <3.0s target

## Related Documentation

- [[04_How_it_Works]]
- [[02_Data_Pipeline]]

## Notes

<3.0s end-to-end is a stated KPI in [[03_Pitching_Narrative]] — this is the last point where that budget can be measured and enforced.
