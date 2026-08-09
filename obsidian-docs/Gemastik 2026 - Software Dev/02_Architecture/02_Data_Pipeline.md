# Data Flow & Pipeline

Dokumen ini menjelaskan empat alur data utama JAWARA: **deteksi operasional**, **inference dengan konteks AI**, **knowledge ingestion**, dan **training**. Keempatnya sengaja dipisahkan karena masing-masing punya pemicu, aktor, dan konsekuensi yang berbeda.

Status: alur operasional §1 **berjalan penuh dari tahap 1 sampai 12** per 2026-08-08 — pesan masuk lewat webhook keluar sebagai balasan WhatsApp dan baris audit. Yang masih Planned di dalamnya: klasifikasi ML berbasis model terlatih (tahap 5b), Security Policy bergradasi (tahap 8), dan penulisan entitas threat/incident/alert (bagian dari tahap 10). Lihat [[00_Sprint_1_Completion_Notes]] dan [[05_Product_Scope_and_Roadmap]].

---

## 1. Alur Operasional Utama (Message → Action)

```text
WhatsApp
    ↓
WAHA
    ↓
FastAPI
    ↓
Message Processing
    ↓
Rules + ML Analysis
    ↓
Threat Classification
    ↓
Risk Assessment
    ↓
Security Policy
    ↓
Action
    ↓
Threat / Incident / Audit Data
    ↓
Dashboard
```

```mermaid
flowchart TD
    A["1. Pesan masuk via WAHA"] -->|webhook| B["2. FastAPI: verifikasi X-Api-Key + rate limit"]
    B --> C["3. Enqueue ke Redis (ack < 200ms)"]
    C -->|Celery worker| D["4. Message Processing<br/>normalisasi teks, ekstraksi URL/indicator"]
    D --> E1["5a. Detection Rules<br/>keyword, domain, blocklist, threshold"]
    D --> E2["5b. ML Analysis<br/>via ml_client ke ML Service"]
    E1 --> F["6. Threat Classification"]
    E2 --> F
    F --> G["7. Risk Assessment<br/>skor gabungan rules + ML"]
    G --> H["8. Security Policy Evaluation"]
    H --> I["9. Action: ALLOW / WARN / BLOCK / ALERT / ESCALATE"]
    I --> J["10. Persist: threat, message metadata,<br/>incident link, audit entry"]
    I --> K["11. Respons WhatsApp via WAHA (bila policy meminta)"]
    J --> L["12. Dashboard / Live Activity"]
```

### Tahap 1–3 — Intake & Offloading (Implemented)

1. WAHA mengirim event (`message.any`, `session.status`) ke `POST /api/v1/webhook`.
2. Gateway memverifikasi header `X-Api-Key`, lalu menerapkan rate limit sliding-window Redis per `(session, chat_id)` — default 20 request / 60 detik, balas `429` + `Retry-After` bila terlampaui.
3. Gateway membalas `200 OK` cepat dan melempar payload ke Redis queue; Celery worker mengonsumsi secara asinkron. Rate limiter **fail open** bila Redis tidak reachable (kegagalan dicatat di log).

### Tahap 4 — Message Processing (Implemented)

Normalisasi teks Bahasa Indonesia (`app/pipeline/normalizer.py`), ekstraksi URL/domain termasuk deteksi shortlink dan link yang di-defang (`app/pipeline/url_extractor.py`), deteksi lampiran `.apk` dari payload WAHA.

Belum ada: ekstraksi indicator finansial (nomor rekening / e-wallet — Post-MVP) dan OCR gambar (dijalankan di ML Service, endpoint `/v1/ocr` belum dibuat).

### Tahap 5 — Rules + ML (Partial)

Dua jalur berjalan berdampingan:

- **Detection Rules** — Implemented. `app/pipeline/intent_router.py`: skoring keyword + indikator, ambang confidence dari config, dievaluasi di worker ([[03_Detection_Rules]]).
- **ML Analysis** — Planned. `POST /v1/classify` ada di kontrak tapi menjawab `model_not_available` karena belum ada model terlatih; gateway jatuh ke jalur rules-only dan menandai `ml_unavailable` ([[04_ML_Service]]).

### Tahap 6–7 — Klasifikasi & Risk Assessment (Partial)

Risk score dirakit dari sinyal rules, verdict knowledge base, dan verdict reputasi URL (`app/pipeline/orchestrator.py`, `worst_risk`). `UNKNOWN` tidak pernah diturunkan menjadi "aman".

Kategori yang dipakai masih `category_enum` generasi pertama. Kategori ancaman Control Panel (Phishing, Scam, Social Engineering, Malicious Link, Impersonation, Spam, Other — [[03_Threat_Monitoring]]) belum dipetakan; keputusan terbuka di [[01_PostgreSQL_Schema]] §0.

### Tahap 8–9 — Policy & Action (Partial)

Policy MVP saat ini tunggal dan implisit: sistem bersifat consent-based, pengguna bertanya maka pengguna dijawab. Pemetaan bergradasi (kategori, risk score, indicator, konteks user) ke `ALLOW` / `WARN` / `BLOCK` / `ALERT` / `ESCALATE` masih **Planned** ([[02_Security_Policies]]).

### Tahap 10–12 — Persist & Surface (Partial)

`message_logs` ditulis untuk setiap pesan yang selesai diproses — intent, risk score, matched fact, similarity, latensi, `user_hash` ter-hash ([[Create Audit Logging]]). Command Center dan Live Activity membaca data itu lewat endpoint agregasi gateway ([[02_Command_Center]]).

Belum ada: entitas threat, incident, alert, dan audit aksi operator — tabelnya belum dibuat.

---

## 2. Alur Inference dengan Konteks AI (RAG)

Dipakai saat klasifikasi/penjelasan membutuhkan konteks pengetahuan.

```text
Message
    ↓
FastAPI
    ↓
ML Service
    ↓
Knowledge Retrieval
    ↓
Qdrant
    ↓
Context
    ↓
ML / AI Inference
    ↓
Classification
```

Catatan penting: retrieval **tidak** mengubah parameter model. Yang berubah hanya konteks yang disuplai ke inference. Lihat [[03_Knowledge_Base]].

---

## 3. Alur Knowledge Ingestion

```text
Admin Upload
    ↓
FastAPI
    ↓
File Validation
    ↓
Document Parsing
    ↓
Chunking
    ↓
Embedding Generation
    ↓
Qdrant
    ↓
Knowledge Available for Retrieval
```

**Upload knowledge tidak me-retrain model.** Dokumen yang di-upload juga tidak otomatis dianggap tepercaya — validasi tipe file, ukuran, dan status review berlaku sebelum knowledge dipakai untuk retrieval ([[06_Platform_Security_Requirements]]).

---

## 4. Alur Training Data

```text
Message / Curated Data
        ↓
Operator Feedback
        ↓
Dataset Curation
        ↓
Dataset Validation
        ↓
Training Job
        ↓
ML Service
        ↓
Evaluation
        ↓
Candidate Model
        ↓
Model Registry
        ↓
Manual Validation
        ↓
Production Model
```

Jalur berikut **tidak** ada dan tidak boleh diimplementasikan:

```text
Operator Feedback  →  Production Model
```

Setiap anak panah di atas adalah gerbang, bukan formalitas. Rinciannya di [[05_Training_Jobs]] dan [[08_Continuous_Improvement_Loop]].

---

## 5. Knowledge vs Training — perbandingan cepat

| | Knowledge Base | Model Training |
| :--- | :--- | :--- |
| Input | Dokumen (PDF, DOCX, TXT, CSV) | Dataset berlabel |
| Proses | Parse → chunk → embed → simpan | Train → evaluate → artifact |
| Penyimpanan hasil | Qdrant (vektor) + PostgreSQL (metadata) | Model registry |
| Parameter model | **Tidak berubah** | **Berubah** |
| Efek | Langsung terasa di retrieval berikutnya | Baru terasa setelah promosi ke produksi |
| Pemicu | Upload operator | Training job eksplisit |

---

## 6. Error Handling & Degradasi

| Kegagalan | Perilaku |
| :--- | :--- |
| Sesi WAHA terputus | WAHA reconnect otomatis; event `session.status` masuk ke gateway dan memicu alert `MEDIUM` ([[04_Alert_Center]], Planned) |
| Broker Redis mati | Webhook tetap balas `200` dengan header `X-Queued: 0`; kegagalan enqueue tercatat sebagai `enqueue failed` di log gateway (event tersebut hilang) |
| Redis mati saat rate limiting | Limiter fail open — request diteruskan, kegagalan di-log |
| ML Service tidak reachable | Gateway jatuh ke jalur rules-only; pesan tetap dicatat, degradasi `ml_unavailable:<error_code>` masuk baris log. Menaikkan alert `MEDIUM` masih Planned (belum ada tabel alert) |
| Qdrant tidak reachable | `/v1/rag-query` menjawab `retrieval_unavailable` (retryable); balasan tetap dibuat tanpa konteks knowledge dan ditandai `knowledge_unverified` |
| Provider threat intel gagal / tanpa API key | Verdict URL `UNKNOWN` + `available: false`; deteksi berjalan dengan sinyal tersisa, degradasi `url_intel_unavailable` |
| LLM provider gagal atau melanggar kontrak 4 bagian | Output ditolak, diganti komposer deterministik, `fallback_used: true` masuk respons dan log |
| WAHA menolak / timeout saat kirim | Retry transien, lalu dicatat sebagai `dispatch_failed`; baris audit tetap ditulis |
| PostgreSQL mati saat menulis audit | Dicatat sebagai `audit_write_failed`; task **tidak** di-retry, karena retry akan mengirim balasan kedua ke pengguna ([[Create_Audit_Logging]]) |
| Job payload malformed | Task Celery membuang job (non-retryable) — retry tidak akan mengubah bentuk payload |

---

**Related:** [[01_System_Architecture]] · [[04_ML_Service]] · [[03_Knowledge_Base]] · [[05_Training_Jobs]] · [[02_Security_Policies]] · [[02_VectorDB_Specifications]]
