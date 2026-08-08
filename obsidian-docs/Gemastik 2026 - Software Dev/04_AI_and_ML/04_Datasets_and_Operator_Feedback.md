# Dataset Management & Operator Feedback

> **Scope:** MVP · **Status:** Planned

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

**Related:** [[05_Training_Jobs]] · [[08_Continuous_Improvement_Loop]] · [[03_Threat_Monitoring]] · [[04_Message_Inspection]] · [[06_Platform_Security_Requirements]]
