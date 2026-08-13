# Training Jobs

> **Scope:** MVP, sebagai **operasi asinkron yang terkontrol** · **Status:** Implemented

Training adalah operasi berat, berdurasi panjang, dan mahal. Karena itu bentuknya job, bukan request.

---

## 1. Aturan Utama

> **Training tidak boleh dieksekusi sinkron di dalam request FastAPI biasa.**

Request dari Control Panel hanya **membuat job**. Eksekusinya berjalan di luar jalur request.

---

## 2. Arsitektur

```text
Dashboard
    ↓
FastAPI
    ↓
Training Job          ← record di PostgreSQL
    ↓
Queue / Worker        ← Redis + worker
    ↓
ML Service
    ↓
Training
    ↓
Evaluation
    ↓
Model Artifact
    ↓
Model Registry
```

Pembagian tanggung jawab:

| Komponen | Peran |
| :--- | :--- |
| Control Panel | Menyusun konfigurasi, memulai, memantau, membatalkan |
| FastAPI Gateway | Validasi konfigurasi, cek RBAC, buat record job, antre pekerjaan, catat audit |
| Queue / Worker | Menjalankan job, melaporkan progres, menangani kegagalan |
| ML Service | Eksekusi training dan evaluasi, hasilkan artefak |
| Model Registry | Menyimpan artefak dan metadata versi ([[07_Model_Registry_and_Deployment]]) |

---

## 3. Konfigurasi Training

| Field | Keterangan |
| :--- | :--- |
| Dataset | Dataset yang dipakai |
| Dataset version | Versi spesifik — wajib, demi reprodusibilitas |
| Base model | Model dasar / titik awal |
| Epochs | Jumlah epoch |
| Learning rate | Laju pembelajaran |
| Batch size | Ukuran batch |
| Validation split | Porsi validasi |
| Training configuration | Parameter tambahan lain |

Konfigurasi disimpan bersama job, bukan hanya dipakai lalu dibuang — itu satu-satunya cara menjelaskan kenapa dua model dari dataset yang sama berbeda hasilnya.

---

## 4. Status Job

```text
QUEUED → RUNNING → EVALUATING → COMPLETED
              ↘         ↘
             FAILED   FAILED

CANCELLED  (dari QUEUED atau RUNNING)
```

| Status | Arti |
| :--- | :--- |
| `QUEUED` | Menunggu worker |
| `RUNNING` | Training berjalan |
| `EVALUATING` | Training selesai, evaluasi berjalan |
| `COMPLETED` | Selesai, artefak dan metrik tersedia |
| `FAILED` | Gagal, dengan informasi error |
| `CANCELLED` | Dibatalkan operator |

`COMPLETED` **tidak** berarti model masuk produksi. Hasilnya adalah kandidat.

---

## 5. Yang Ditampilkan di Control Panel

- Progress
- Status
- Dataset version
- Training configuration
- Metrics
- Result
- Error information
- Generated model version

---

## 6. Kontrol Keamanan & Resource

| Kontrol | Keterangan |
| :--- | :--- |
| RBAC | Hanya role tertentu boleh memulai/membatalkan job ([[07_Users_and_Risk]]) |
| Audit | Pembuatan, pembatalan, dan kegagalan job tercatat ([[05_Audit_Logs]]) |
| Isolasi | Job berjalan terisolasi dengan batas resource; tidak berbagi proses dengan jalur inference produksi |
| Batas konkurensi | Jumlah job paralel dibatasi supaya training tidak melaparkan inference |
| Dataset tervalidasi | Hanya dataset ber-status `VALIDATED` yang boleh dipakai ([[04_Datasets_and_Operator_Feedback]]) |

**Open question:** apakah training berbagi worker pool dengan pipeline pesan atau punya queue sendiri — belum diputuskan. Rekomendasi: queue terpisah, agar job panjang tidak menahan pemrosesan pesan.

---

**Related:** [[04_Datasets_and_Operator_Feedback]] · [[06_Model_Evaluation]] · [[07_Model_Registry_and_Deployment]] · [[04_ML_Service]] · [[08_Continuous_Improvement_Loop]]
