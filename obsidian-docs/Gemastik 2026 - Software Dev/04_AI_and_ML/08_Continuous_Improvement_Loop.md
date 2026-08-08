# Continuous Improvement Loop

> **Scope:** MVP (sebagai siklus terkontrol) · **Status:** Planned
> Automated retraining workflows adalah **Post-MVP** dan tetap harus terkontrol saat dibangun.

---

## 1. Siklus

```text
Production Detection
        ↓
Operator Review
        ↓
Human Feedback
        ↓
Dataset Curation
        ↓
Dataset Validation
        ↓
Training
        ↓
Evaluation
        ↓
Candidate Model
        ↓
Validation
        ↓
Production Deployment
        ↓
Production Detection
```

---

## 2. Setiap Anak Panah Adalah Gerbang

| Transisi | Gerbang |
| :--- | :--- |
| Production Detection → Operator Review | Operator melihat hasil klasifikasi di Control Panel |
| Operator Review → Human Feedback | Aksi eksplisit: confirm / false positive / change classification |
| Human Feedback → Dataset Curation | Feedback masuk antrean kurasi, bukan langsung dataset |
| Dataset Curation → Dataset Validation | Pemeriksaan skema, label, duplikat, kebocoran, privasi |
| Dataset Validation → Training | Hanya dataset `VALIDATED` |
| Training → Evaluation | Otomatis setelah training selesai |
| Evaluation → Candidate Model | Artefak masuk registry sebagai `CANDIDATE` |
| Candidate → Validation | Tinjauan metrik terhadap ambang dan terhadap model produksi |
| Validation → Production Deployment | **Tindakan manual** oleh role berwenang, tercatat audit |

---

## 3. Yang Tidak Boleh Terjadi

Jalur pintas berikut dilarang secara desain:

```text
Operator Feedback  →  Production Model        ✘
Training selesai   →  Production otomatis     ✘
Upload knowledge   →  Retraining otomatis     ✘
```

Retraining otomatis tanpa kendali adalah cara tercepat mengubah satu kesalahan operator menjadi perilaku produksi.

---

## 4. Kenapa Loop Ini Berharga

Modus penipuan berubah lebih cepat daripada siklus rilis software. Loop ini adalah mekanisme agar sistem ikut berubah — tapi dengan manusia sebagai gerbang, bukan sebagai penonton.

Dua jalur perbaikan berjalan pada kecepatan berbeda:

| Jalur | Kecepatan | Mekanisme |
| :--- | :--- | :--- |
| Detection Rules | Menit | Ubah rule/blocklist, langsung berlaku ([[03_Detection_Rules]]) |
| Knowledge Base | Jam | Upload dokumen, langsung tersedia untuk retrieval ([[03_Knowledge_Base]]) |
| Model | Hari–minggu | Kurasi → validasi → training → evaluasi → promosi |

Ketiganya dipakai bersama. Rule dan knowledge menangani yang mendesak; model menangani yang struktural.

---

**Related:** [[04_Datasets_and_Operator_Feedback]] · [[05_Training_Jobs]] · [[06_Model_Evaluation]] · [[07_Model_Registry_and_Deployment]] · [[03_Knowledge_Base]] · [[03_Detection_Rules]]
