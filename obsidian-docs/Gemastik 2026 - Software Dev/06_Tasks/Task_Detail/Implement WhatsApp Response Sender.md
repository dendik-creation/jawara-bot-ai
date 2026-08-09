# Implement WhatsApp Response Sender

## Status

Done

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

## Implementation (2026-08-08)

`backend/app/clients/waha_client.py` — `POST /api/sendText`, retry pada kegagalan transien (timeout/5xx) sampai `WAHA_SEND_MAX_ATTEMPTS`, 4xx tidak di-retry. Kegagalan permanen dikembalikan sebagai data (`SendResult`), tidak dilempar sebagai exception, supaya baris audit tetap ditulis.

`response_latency_ms` diukur dari `received_at` (dicap gateway saat enqueue) sampai setelah dispatch, disimpan ke `message_logs`, dan melampaui `END_TO_END_TARGET_MS` memicu log `WARNING`.

**Belum diverifikasi terhadap sesi WhatsApp nyata** (belum ada pairing). Pengukuran latensi nyata dan implikasinya terhadap KPI 3 detik: [[Implement_WhatsApp_Response_Sender]].
