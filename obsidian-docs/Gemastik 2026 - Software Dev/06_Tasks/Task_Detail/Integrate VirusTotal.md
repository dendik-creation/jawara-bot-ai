# Integrate VirusTotal

## Status

Done

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

## Implementation (2026-08-08)

`backend/app/clients/virustotal.py` (lookup v3, tanpa submit) dan `backend/app/pipeline/url_safety.py` (verdict gabungan). Ambang `VIRUSTOTAL_HIGH_THRESHOLD` (default 2) memetakan jumlah deteksi ke `risk_level_enum`; HTTP 404 = `UNKNOWN`, bukan `LOW`.

Penggabungan: yang terburuk menang, `UNKNOWN` tidak pernah menurunkan risiko, shortlink/host IP yang tak terverifikasi minimal `MEDIUM`. Kedua provider dipanggil konkuren.

**Belum diverifikasi terhadap API nyata — `VIRUSTOTAL_API_KEY` kosong.** Kuota dan keputusan privasi (hanya lookup): [[Integrate_VirusTotal]].
