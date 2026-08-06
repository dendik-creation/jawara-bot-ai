# Build Intent Router

## Status

ToDo

## Priority

Critical

## Sprint

Sprint 1

## Deadline

2026-08-08

## Description

Classify preprocessed input into one of the 3 categories in Sprint 1 scope (`HEALTH_HOAX`, `GENERAL_NEWS`, `PHISHING_LINK`) and route to the corresponding verification engine.

## Background

Central dispatch point of the AI pipeline. The full documented taxonomy has 5 categories (`category_enum` in [[01_PostgreSQL_Schema]]); `FINANCIAL_FRAUD` and `FILE_APK` are deferred to a later sprint per the OCR/fraud/file exclusion, but the router should be built so those categories can be added without a redesign.

## Deliverables

- Intent classifier for `HEALTH_HOAX` / `GENERAL_NEWS` / `PHISHING_LINK`
- Routing abstraction dispatching to the correct verification engine per category
- Unit tests per category, including ambiguous/unknown input

## Dependencies

- [[Implement Text Normalizer]]
- [[Implement URL Extractor]]

## Acceptance Criteria

- Detects all 3 in-scope categories
- Unknown/ambiguous input does not crash the router and is handled explicitly
- Confidence threshold is configurable, not hardcoded
- Category output values match `category_enum` exactly (no drift between code and schema)

## Related Documentation

- [[02_Data_Pipeline]]
- [[01_PostgreSQL_Schema]]
- [[01_LLM_System_Prompt]]

## Notes

Do not hardcode assumptions that only 3 categories will ever exist — `FINANCIAL_FRAUD` and `FILE_APK` routing is future-sprint work, not out-of-scope permanently.
