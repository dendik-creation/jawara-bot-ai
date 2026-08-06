# Setup Docker Environment

## Status

Done

## Priority

Critical

## Sprint

Sprint 1

## Deadline

2026-08-06

## Description

Stand up the full local service topology in one Docker Compose file: `waha`, `api-gateway`, `celery-worker`, `postgres`, `qdrant`, `redis`, `frontend-dashboard`.

## Background

Foundation layer — every other Sprint 1 task depends on these containers existing and being network-reachable by service name.

## Deliverables

- `docker-compose.yml` with all 7 services and named volumes (`waha_sessions`, `postgres_data`, `qdrant_data`)
- `.env.example` covering every referenced variable — no hardcoded secrets

## Dependencies

None (foundation task)

## Acceptance Criteria

- `docker compose up` starts all 7 containers healthy
- Gateway reaches `postgres`, `redis`, `qdrant`, `waha` by service DNS name
- No credential hardcoded in the compose file

## Related Documentation

- [[03_Tech_Stack]]
- [[01_System_Architecture]]

## Notes

Original compose example in the vault hardcoded `WAHA_DASHBOARD_PASSWORD`, `POSTGRES_PASSWORD`, and a static API key — corrected to `${VAR}` placeholders during the documentation audit ([[01_Documentation_Audit_Report]], finding #4). Use env-injected secrets only.
