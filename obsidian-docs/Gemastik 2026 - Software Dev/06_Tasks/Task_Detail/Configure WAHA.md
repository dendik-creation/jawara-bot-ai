# Configure WAHA

## Status

Done

## Priority

Critical

## Sprint

Sprint 1

## Deadline

2026-08-06

## Description

Deploy `devlikeapro/waha`, pair a WhatsApp session, and configure it to POST `message.any` events to the gateway's webhook endpoint.

## Background

WAHA is the sole entry/exit point for all user messages — the pipeline is unreachable without a live, persisted session.

## Deliverables

- WAHA container with persisted session volume
- `WHATSAPP_HOOK_URL` and `WHATSAPP_HOOK_EVENTS=message,message.any` configured
- Session reconnect verified after container restart

## Dependencies

- [[Setup Docker Environment]]

## Acceptance Criteria

- QR pairing completes and session persists across restart
- Webhook fires on inbound message within local network
- Session-status webhook (`/api/v1/session/status`) observed on disconnect/reconnect

## Related Documentation

- [[01_System_Architecture]]
- [[02_Data_Pipeline]]

## Notes

Image verification / OCR-triggered messages are out of scope for Sprint 1 — session and webhook config here should not assume image handling downstream.
