# Create Audit Logging

## Status

ToDo

## Priority

High

## Sprint

Sprint 1

## Deadline

2026-08-10

## Description

Write each processed transaction to `message_logs` after response generation: intent, risk score, matched fact ID, similarity score, response latency — keyed by hashed `user_hash`.

## Background

System-of-record for the milestone's "logging works correctly" completion criterion, and the anonymized audit trail underpinning the privacy value proposition.

## Deliverables

- Write path from worker to `message_logs` after every completed response
- `response_latency_ms` captured end-to-end from webhook receipt to WAHA dispatch

## Dependencies

- [[Design PostgreSQL Schema]]
- [[Implement WhatsApp Response Sender]]

## Acceptance Criteria

- Every dispatched response has a corresponding `message_logs` row
- `waha_message_id` uniqueness prevents duplicate logging on webhook retry
- Logged fields match the schema exactly (intent, risk score, matched fact, similarity score, latency)

## Related Documentation

- [[01_PostgreSQL_Schema]]
- [[04_How_it_Works]]

## Notes

`message_logs.extracted_text` is stored in plaintext with no documented retention window — flagged as a High-priority gap in [[01_Documentation_Audit_Report]] (finding #1). Retention policy is out of scope for this task/sprint but should not be forgotten before production traffic.
