# ML Service (Standalone)

> **Status:** Partial (2026-08-08). Direktori `ml-service/` sudah ada dan berjalan sebagai container tersendiri. Kontrak di §4 dipakai apa adanya; yang belum ada ditandai per endpoint di tabel itu. Dokumen ini ditulis **sebelum** kodenya dibuat, supaya tidak ada logika inferensi yang menyelinap ke dalam gateway — dan urutan itu terbukti berguna: gateway sampai sekarang tidak pernah menghitung satu vektor pun.

---

## 1. Kenapa Terpisah

| Alasan | Konsekuensi kalau digabung ke gateway |
| :--- | :--- |
| Skalabilitas berbeda | Gateway menskala pada jumlah koneksi, inference menskala pada CPU/GPU. Digabung berarti keduanya dipaksa menskala bersama. |
| Biaya loading model | Model OCR/embedding berat di memori. Digabung berarti setiap worker uvicorn membayar biaya itu. |
| Siklus rilis berbeda | Ganti model seharusnya tidak memaksa deploy ulang API bisnis. |
| Blocking workload | Inference bersifat CPU-bound; menjalankannya di event loop gateway menahan intake webhook. |

---

## 2. Tanggung Jawab

ML Service bertanggung jawab atas:

- ML inference
- Model loading dan eksekusi model
- Preprocessing khusus ML (termasuk OCR gambar)
- Embedding generation
- Pemrosesan dataset yang dibutuhkan ML
- Model training
- Model evaluation
- Pembuatan artefak model
- Eksperimentasi khusus ML

ML Service **bukan** pengganti API layer. Yang berikut ini bukan miliknya: autentikasi user, RBAC, manajemen incident, manajemen policy, audit logging bisnis, dan trafik apa pun yang berasal langsung dari frontend.

---

## 3. Arah Panggilan

```text
Frontend  →  FastAPI Gateway  →  ML Service        ✔
Frontend  →  ML Service                            ✘
```

Gateway memanggil ML Service **hanya** lewat satu modul client (`backend/app/clients/ml_client.py`, Planned). Modul itu satu-satunya tempat di gateway yang boleh tahu URL dan schema ML Service.

---

## 4. Kontrak API (usulan)

Versi di path (`/v1/...`). Setiap request membawa `request_id` yang sama dengan correlation ID dari webhook asal, sehingga satu pesan bisa ditelusuri dari WAHA → gateway → worker → ML Service → baris audit.

| Endpoint | Fungsi | Status |
| :--- | :--- | :--- |
| `POST /v1/classify` | Klasifikasi ancaman + confidence | Planned — menjawab `model_not_available` (belum ada model terlatih); gateway jatuh ke Detection Rules |
| `POST /v1/ocr` | Ekstraksi teks dari gambar/flyer | Planned — OCR di luar scope Sprint 1 |
| `POST /v1/embed` | Teks → vektor | Implemented |
| `POST /v1/rag-query` | Embed + similarity search Qdrant + rakit konteks, satu panggilan | Implemented |
| `POST /v1/generate` | Generasi respons LLM dari konteks yang sudah dirakit | Implemented |
| `POST /v1/kb/upsert` | Embed + simpan fact item ke Qdrant (ingestion) | Implemented — tidak ada di rancangan awal, ditambahkan agar gateway tidak perlu menghitung embedding sendiri |
| `POST /v1/train` | Mulai training job (dipanggil worker, bukan request user sinkron) | Planned — Fase 4 |
| `POST /v1/evaluate` | Evaluasi model terhadap dataset validasi tetap | Planned — Fase 4 |
| `GET /v1/health` · `GET /v1/ready` | Liveness dan readiness (lihat §6) | Implemented |

**Bentuk request/response:** `{ request_id, payload, metadata }` masuk, `{ request_id, result, confidence, model_version, latency_ms }` keluar. `model_version` wajib ada di setiap respons inference — itu yang membuat baris audit bisa menjelaskan "model mana yang memutuskan ini".

**Error:** terstruktur (`{ error_code, message, retryable }`), bukan HTTP 500 telanjang, supaya gateway bisa memilih retry vs fallback secara programatik.

**Timeout & retry:** budget per endpoint (classify lebih ketat dari generate). Retry hanya untuk endpoint idempoten (`classify`, `embed`, `rag-query`); `generate` tidak pernah di-retry buta — jatuh langsung ke fallback.

---

## 5. Qdrant Dimiliki ML Service

Embedding dan similarity search adalah pekerjaan inference-adjacent, bukan business logic. Karena itu akses Qdrant untuk retrieval berada **di belakang** ML Service; gateway tidak menghitung atau membandingkan vektor sendiri.

Yang tetap milik gateway: metadata knowledge (judul dokumen, sumber, status review, siapa yang meng-upload) di PostgreSQL, dan orkestrasi pipeline ingestion.

---

## 6. Readiness vs Liveness

Healthcheck ML Service harus membedakan keduanya:

- **Liveness** — proses hidup.
- **Readiness** — model sudah selesai dimuat ke memori.

Tanpa pembedaan ini, orchestrator mengirim trafik ke container yang sudah "up" tapi belum selesai memuat bobot model, dan request pertama gagal tanpa sebab yang jelas.

Model dimuat **sekali per proses saat startup**, bukan per request.

---

## 7. Multi-Model dari Hari Pertama

- Registry model internal (peta `nama+versi → instance yang dimuat`) sejak model pertama, supaya "model kedua" jadi entri konfigurasi, bukan penulisan ulang.
- `model_version` selalu ikut di respons.
- Versi API di path sejak endpoint pertama.

Ketiganya sudah ada: `ml-service/app/models/registry.py` memuat embedder dan provider LLM saat startup, `GET /v1/ready` melaporkan isinya, dan setiap respons inference membawa `model_version` (mis. `hash-embed-v0`, `template-composer-v1`, `anthropic-claude-haiku-4-5-20251001`).

Provider yang dikonfigurasi tapi kehilangan API key **tidak** membuat service gagal start: ia turun ke fallback offline, mencatat alasannya di `degraded_reasons`, dan tetap `ready`. Pipeline yang tidak bisa menjawab sama sekali lebih buruk daripada pipeline yang menjawab dengan template.

Detail siklus hidup model di [[07_Model_Registry_and_Deployment]].

---

## 8. Keamanan Service-to-Service

- ML Service tidak pernah terekspos ke internet; hanya reachable di jaringan Docker internal.
- Autentikasi antar-service memakai internal API key yang di-inject lewat env dan diperiksa sebagai FastAPI dependency.
- Validasi input (ukuran file, mime-type) dilakukan **sebelum** payload sampai ke kode OCR/inference, bukan sesudah.

Lihat [[06_Platform_Security_Requirements]].

---

**Related:** [[01_System_Architecture]] · [[02_Data_Pipeline]] · [[02_ML_Control_Center_Overview]] · [[05_Training_Jobs]] · [[07_Model_Registry_and_Deployment]] · [[06_Platform_Security_Requirements]]
