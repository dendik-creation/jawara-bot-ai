# Dataset Management & Operator Feedback

> **Scope:** MVP · **Status:** Partial — §1 "change classification" button not built; §2 corpus import and §7 feedback→dataset promotion are live, see §7

Dua hal yang saling terkait: dari mana data latih berasal (operator feedback), dan bagaimana data itu dikelola sebelum dipakai (dataset management).

---

## 1. Human-in-the-Loop / Operator Feedback

Operator dapat mengoreksi klasifikasi AI langsung dari layar inspeksi pesan atau threat.

```text
AI Classification:
PHISHING
Confidence: 91%

[ CONFIRM THREAT ]
[ FALSE POSITIVE ]
[ CHANGE CLASSIFICATION ]
```

### Yang disimpan per feedback

| Field | Keterangan |
| :--- | :--- |
| Message reference | Pesan yang dikoreksi |
| Original classification | Klasifikasi asli dari model |
| Corrected classification | Klasifikasi menurut operator |
| Operator | Siapa yang mengoreksi |
| Timestamp | Kapan |
| Model version | Model mana yang menghasilkan klasifikasi asli |
| Reason / annotation | Opsional, alasan koreksi |

### Aturan keras

- Feedback operator **dapat** menjadi data latih **setelah divalidasi**.
- Feedback operator **tidak pernah** langsung melatih atau men-deploy model.
- Setiap feedback tercatat di audit log ([[05_Audit_Logs]]).

`model_version` pada setiap feedback bukan hiasan: tanpa itu, mustahil tahu apakah sebuah kesalahan sudah diperbaiki oleh model yang lebih baru atau masih hidup di produksi.

---

## 2. Dataset Management

Kapabilitas layar Datasets:

- Dataset list
- Dataset versions
- Sample count
- Labels
- Dataset source
- Dataset status
- Validation status

### Sumber dataset

| Sumber | Catatan |
| :--- | :--- |
| Curated datasets | Disusun tim, sudah ditinjau |
| Operator feedback | Hasil koreksi operator, **wajib lewat validasi** |
| Imported datasets | Dari luar; asal dan lisensinya harus jelas |
| Approved security data | Data keamanan internal yang sudah disetujui |

### Contoh

```text
Dataset: phishing-v3

Total samples: 42,381

Phishing: 18,293
Scam:      12,401
Safe:      11,687
```

---

## 3. Status Dataset

```text
DRAFT → VALIDATING → VALIDATED → (ARCHIVED)
                  ↘
                    REJECTED
```

Hanya dataset ber-status `VALIDATED` yang boleh dipakai training job.

---

## 4. Validasi Dataset

Data yang di-upload atau dikumpulkan **bukan input tepercaya**. Validasi minimal:

| Pemeriksaan | Kenapa |
| :--- | :--- |
| Skema & tipe kolom | Mencegah job gagal di tengah training |
| Distribusi label | Ketimpangan ekstrem menghasilkan model yang tampak akurat tapi tidak berguna |
| Duplikat & kebocoran | Sampel yang sama di train dan test membuat metrik evaluasi bohong |
| Label rusak/kontradiktif | Dua label berbeda untuk konten identik |
| Batas ukuran & tipe file | Lihat [[06_Platform_Security_Requirements]] §3 |
| Kepatuhan privasi | Dataset tidak boleh membawa identitas mentah; identitas selalu ter-hash ([[01_Threat_Model_and_Data_Protection]]) |

---

## 5. Versioning

Dataset bersifat berversi, dan **versi yang dipakai tercatat di training job**. Tanpa itu, hasil evaluasi tidak bisa direproduksi dan perbandingan antar model kehilangan makna ([[06_Model_Evaluation]]).

---

---

## 6. Corpus Import — `datasets/indonesia_hoax_news/`

`python -m app.scripts.import_hoax_corpus` (`backend/app/scripts/import_hoax_corpus.py`) menutup gap "real data sitting unused" dari audit (§18/§22 langkah 4). Sumber: 4 CSV scraped — 3 media legit (Antara, Detik, Kompas, label biner 0) + TurnBackHoax (label biner 1).

- Baris legit → `NOT_A_THREAT` langsung, karena statusnya fakta dari file asalnya, bukan tebakan.
- Baris TurnBackHoax hanya berlabel biner "hoax", tidak bilang termasuk kelas hoax yang mana. Script melakukan setengah dari "manual/LLM-assisted relabeling" yang diminta audit: heuristik keyword deterministik (urutan prioritas `.apk`/instal → link/verifikasi → transfer/rekening/OTP → obat/vaksin/penyakit → jatuh ke `GENERAL_NEWS` sebagai catch-all, mengikuti makna `GENERAL_NEWS` di [[threat_categories.py]]).
- Landing sebagai satu dataset `DRAFT` (`source=IMPORTED`), **tidak** auto-`VALIDATE` — dataset besar berlabel heuristik butuh operator memeriksa `label_counts` dan memvalidasi sengaja, konsisten dengan prinsip human-gated di [[08_Continuous_Improvement_Loop]].
- Idempotent by (name, version), sama seperti `seed_dataset_samples.py`.

Hasil live run terakhir: 23,957 sample (setelah dedup exact-text) — `NOT_A_THREAT` 12,141 · `GENERAL_NEWS` 9,315 · `FINANCIAL_FRAUD` 1,076 · `HEALTH_HOAX` 940 · `PHISHING_LINK` 485 · `FILE_APK` 0. `FILE_APK` nol masuk akal: korpus ini artikel berita/fact-check, bukan pesan WhatsApp asli, jadi bahasa "instal aplikasi terlampir" khas APK-disguise nyaris tidak muncul — batasan sumber data, bukan bug heuristik.

## 7. Feedback → Dataset Promotion

`POST /api/v1/datasets/{dataset_id}/promote-feedback` (body opsional `feedback_type`, `limit`) menutup langkah aktif-learning terakhir di §19 audit: operator memicu manual, tidak pernah otomatis.

- `FALSE_POSITIVE` → label `NOT_A_THREAT` (operator menyatakan ini bukan ancaman — fakta langsung, bukan tebakan).
- `CONFIRM` → label = `original_classification` feedback itu sendiri (operator setuju dengan klasifikasi asli). `CONFIRM` tanpa `original_classification` (pesan belum pernah diklasifikasi) dilewati, dilaporkan di `skipped_reasons`, tidak ditebak.
- Idempotent: feedback yang `dataset_samples.source_feedback_id`-nya sudah terisi dikecualikan dari query, jadi re-run hanya mengambil feedback baru.
- Hanya jalan ke dataset berstatus `DRAFT` — sama seperti guard `add_sample`.

Implementasi: `app/services/feedback.py::promote_to_dataset` (dipakai lewat `app/api/v1/endpoints/datasets.py`). Diverifikasi live: 2 feedback (1 `CONFIRM`, 1 `FALSE_POSITIVE`) ter-promote jadi 2 sample dengan label yang benar, re-run kedua menghasilkan 0 promoted.

---

**Related:** [[05_Training_Jobs]] · [[08_Continuous_Improvement_Loop]] · [[03_Threat_Monitoring]] · [[04_Message_Inspection]] · [[06_Platform_Security_Requirements]]
