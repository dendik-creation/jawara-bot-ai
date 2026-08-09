# Build Intent Router

## Status

Done

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

Scope update: routing `FILE_APK` (mendeteksi lampiran `.apk` dan memperingatkan) tetap masuk MVP, tapi **analisis statik isi APK adalah Opsional / Future** ([[06_Optional_APK_Inspector]]). `FINANCIAL_FRAUD` / CekRekening.id adalah **Post-MVP** ([[05_Product_Scope_and_Roadmap]]). Router juga harus mengakomodasi kategori ancaman Control Panel yang lebih luas (Phishing, Scam, Social Engineering, Malicious Link, Impersonation, Spam, Other) — pemetaannya ke `category_enum` masih keputusan terbuka ([[01_PostgreSQL_Schema]] §0).

## Implementation (2026-08-08)

`backend/app/pipeline/intent_router.py` + `categories.py`. Skoring keyword dan indikator (URL, shortlink, host IP, defang, lampiran `.apk`, bentuk pertanyaan); confidence = pangsa skor pemenang; dua ambang config (`INTENT_MIN_SCORE`, `INTENT_CONFIDENCE_THRESHOLD`).

Routing: `HEALTH_HOAX`/`GENERAL_NEWS` → `text_verification`, `PHISHING_LINK` → `url_safety`, `FILE_APK` → `apk_warning`, `FINANCIAL_FRAUD` → `unsupported` (Post-MVP), tanpa kategori → `none`.

Anti-drift: test mem-parse `001_init_schema.sql` dan membandingkan `category_enum`/`risk_level_enum` dengan enum Python.

Catatan lengkap termasuk keputusan yang masih terbuka: [[Build_Intent_Router]].
