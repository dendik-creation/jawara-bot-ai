# Integrate VirusTotal

## Status

ToDo

## Priority

High

## Sprint

Sprint 1

## Deadline

2026-08-09

## Description

For `PHISHING_LINK` intent, check extracted URLs against the VirusTotal API v3 in real time, and combine the result with the Safe Browsing verdict into a single risk output.

## Background

Second URL-reputation source; the two are combined so a phishing link caught by only one provider still surfaces as high risk.

## Deliverables

- VirusTotal v3 API client
- Combined verdict logic (Safe Browsing + VirusTotal → single risk level)

## Dependencies

- [[Implement URL Extractor]]
- [[Build Intent Router]]

## Acceptance Criteria

- Known-malicious test URL flagged by at least one of the two providers surfaces as high risk
- API call has timeout + error handling — verdict degrades gracefully, doesn't hang the pipeline
- API key sourced from env, never logged

## Related Documentation

- [[02_Data_Pipeline]]
- [[01_System_Architecture]]

## Notes

Third-party dependency with rate limits/cost — document quota handling before production traffic.
