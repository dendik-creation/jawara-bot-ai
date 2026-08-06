# Implement Basic Analytics Dashboard

## Status

ToDo

## Priority

Medium

## Sprint

Sprint 1

## Deadline

2026-08-10

## Description

Stand up a minimal Next.js 14 (App Router) + TailwindCSS dashboard shell showing aggregate message volume, intent breakdown, and latency — the initial dashboard required for this milestone.

## Background

Presentation layer for aggregate system activity, separate from the WhatsApp-facing product. Sprint 1 scope is the dashboard shell and basic metrics only — the B2G spatial heatmap is a later-sprint feature.

## Deliverables

- Next.js 14 App Router project scaffold
- API integration reading aggregate (non-PII) data from `message_logs`
- Basic views: message volume, intent breakdown, latency

## Dependencies

- [[Create Audit Logging]]

## Acceptance Criteria

- Dashboard queries only aggregated/anonymized data, never raw `extracted_text`
- Renders message volume, intent breakdown, and latency views
- Responsive layout on desktop and tablet

## Related Documentation

- [[01_System_Architecture]]
- [[03_Tech_Stack]]

## Notes

B2G spatial heatmap dashboard is out of scope for Sprint 1 — the schema has no region/location field yet, and that feature is deferred to a later sprint.
