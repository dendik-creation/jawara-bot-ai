# Integrate Safe Browsing

## Status

ToDo

## Priority

High

## Sprint

Sprint 1

## Deadline

2026-08-09

## Description

For `PHISHING_LINK` intent, check extracted URLs against the Google Safe Browsing API in real time.

## Background

Primary URL-reputation source for the phishing/credential-harvesting threat domain (bansos, banking, promo scams).

## Deliverables

- Google Safe Browsing API client
- Risk verdict mapped to `risk_level_enum`

## Dependencies

- [[Implement URL Extractor]]
- [[Build Intent Router]]

## Acceptance Criteria

- Known-malicious test URL is flagged as high risk
- API call has timeout + error handling — verdict degrades gracefully, doesn't hang the pipeline
- API key sourced from env, never logged

## Related Documentation

- [[02_Data_Pipeline]]
- [[01_System_Architecture]]

## Notes

Third-party dependency with rate limits/cost — document quota handling before production traffic.
