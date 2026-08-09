# Implement Text Normalizer

## Status

Done

## Priority

High

## Sprint

Sprint 1

## Deadline

2026-08-08

## Description

Clean and normalize incoming text input (strip noise characters, normalize informal/slang Indonesian) before intent classification and embedding.

## Background

First preprocessing stage for the text path; feeds directly into the Intent Router. Sprint 1 scope is text and URL only — no OCR-sourced text this milestone.

## Deliverables

- Text normalization function/module
- Test corpus of representative WhatsApp-style Indonesian text (informal, typos, emoji noise)

## Dependencies

- [[Implement Celery Workers]]

## Acceptance Criteria

- Handles mixed-case, punctuation noise, repeated characters
- Output is deterministic for identical input
- Unit tests cover at least 10 representative message samples

## Related Documentation

- [[02_Data_Pipeline]]
- [[01_System_Architecture]]

## Notes

None

## Implementation (2026-08-08)

`backend/app/pipeline/normalizer.py` — `normalize_text()` mengembalikan `NormalizedText` (`raw`, `text`, `urls_masked`, `emoji_count`, `was_truncated`, `slang_replaced`).

Urutan transform: NFKC → buang karakter tak terlihat → mask URL → buang emoji (dihitung) → buang markdown WhatsApp → casefold → runtuhkan huruf berulang 3+ → runtuhkan tanda baca berulang → ekspansi slang → pulihkan URL → rapikan spasi. URL di-mask lebih dulu karena path dan query bersifat case-sensitive.

Singkatan ambigu (`dr`, `no`, `sm`, `jg`, `dl`) sengaja **tidak** diekspansi — tebakan yang salah mengubah makna pesan yang akan diklasifikasi.

Test: `backend/tests/test_normalizer.py`, korpus 12 sampel WhatsApp Indonesia + uji determinisme per sampel.
