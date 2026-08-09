# Implement URL Extractor

## Status

Done

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

## Implementation (2026-08-08)

`backend/app/pipeline/url_extractor.py` — `extract_urls()` mengembalikan `ExtractedURL` (`url`, `raw`, `domain`, `is_shortlink`, `is_ip_host`, `was_defanged`, `registrable_domain`).

Empat pola dipakai berurutan: URL berskema (`http(s)://`), `www.`, domain shortener eksak, lalu domain telanjang dengan daftar TLD terbatas. Shortener butuh pola sendiri karena TLD-nya (`ly`, `gd`, `do`) adalah kata Indonesia biasa — memasukkannya ke daftar TLD umum akan mengubah "coba.in" jadi URL, sementara `bit.ly/x` justru wajib tertangkap.

Link yang di-defang (`hxxp://`, `[.]`) dipulihkan dan ditandai. Tanda baca akhir kalimat dipangkas dengan tetap menjaga tanda kurung yang seimbang.

Test: `backend/tests/test_url_extractor.py`, termasuk uji negatif bahwa kalimat Indonesia biasa tidak menghasilkan URL palsu.
