# Design PostgreSQL Schema

## Status

ToDo

## Priority

Critical

## Sprint

Sprint 1

## Deadline

2026-08-07

## Description

Apply the relational schema needed for Sprint 1 scope: `pgcrypto` extension, enums (`category_enum`, `verdict_enum`, `risk_level_enum`, `input_type_enum`), `fact_sources`, `fact_items` (with `updated_at` trigger), `user_subscriptions`, and `message_logs`, plus their indexes.

## Background

`fact_sources`/`fact_items` back RAG text verification, `user_subscriptions`/`message_logs` back WhatsApp identity and audit logging. Every table in Sprint 1's pipeline depends on this schema existing first.

## Deliverables

- Migration applying `pgcrypto` + all 4 enums
- `fact_sources`, `fact_items` DDL + `update_updated_at_column()` trigger + `idx_fact_items_category`
- `user_subscriptions` DDL (hashing convention documented: SHA-256 of phone/group ID + salt)
- `message_logs` DDL + `idx_message_logs_created_at`, `idx_message_logs_intent`, `idx_message_logs_user_hash`

## Dependencies

- [[Setup Docker Environment]]

## Acceptance Criteria

- All enums exist with exact documented values
- FKs enforced: `fact_items.source_id → fact_sources.id` (SET NULL), `message_logs.user_hash → user_subscriptions.user_hash` (CASCADE), `message_logs.matched_fact_id → fact_items.id` (SET NULL)
- `updated_at` auto-updates on `fact_items` row update, test-verified
- `waha_message_id` uniqueness prevents duplicate-webhook double-logging
- Migration is idempotent / re-runnable in CI

## Related Documentation

- [[01_PostgreSQL_Schema]]

## Notes

`fraud_blacklists` (financial fraud) is out of scope for Sprint 1 — financial fraud verification isn't part of this milestone. Do not create that table yet. Salt storage/rotation for `user_hash` isn't specified beyond "SHA-256 + Salt" in the schema doc — decide and document before first production write, an undocumented salt undermines the anonymization claim in [[02_Value_Proposition]].
