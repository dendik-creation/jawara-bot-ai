# Implement URL Extractor

## Status

ToDo

## Priority

High

## Sprint

Sprint 1

## Deadline

2026-08-08

## Description

Parse URLs out of raw message content, including shortlink detection (bit.ly, tinyurl, etc.), for routing into the URL safety verification path.

## Background

Feeds the Intent Router's `PHISHING_LINK` classification and the URL Safety verification engines (Safe Browsing, VirusTotal).

## Deliverables

- URL extraction from free-text message content
- Shortlink flagging

## Dependencies

- [[Implement Celery Workers]]

## Acceptance Criteria

- Correctly extracts URL from message text containing a shortener link
- Handles messages with multiple URLs
- Unit tests pass

## Related Documentation

- [[02_Data_Pipeline]]

## Notes

File (`.apk`) and bank-account/e-wallet extraction are out of scope for Sprint 1 — financial fraud and malicious-file verification are deferred to a later sprint. This task extracts URLs only.
