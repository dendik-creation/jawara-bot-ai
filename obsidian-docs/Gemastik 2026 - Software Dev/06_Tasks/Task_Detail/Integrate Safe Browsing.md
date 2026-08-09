# Integrate Safe Browsing

## Status

Done

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

## Implementation (2026-08-08)

`backend/app/clients/safe_browsing.py` — `threatMatches:find` v4, batch satu request, cache Redis, batas URL per pesan, HTTP 429 tidak di-retry. Verdict → `risk_level_enum`: cocok = `HIGH`, `matches` kosong = `LOW`, gagal/tanpa key = `UNKNOWN` + `available: false`.

**Belum diverifikasi terhadap API nyata — `GOOGLE_SAFE_BROWSING_API_KEY` kosong.** Penanganan kuota dan cara menyelesaikan verifikasi: [[Integrate_Safe_Browsing]].
