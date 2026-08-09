# Product Scope & Roadmap (MVP / Post-MVP / Optional / Deferred)

> **Dokumen ini adalah sumber tunggal (single source of truth) untuk klasifikasi scope fitur JAWARA.** Dokumen lain di vault ini menandai fitur dengan label yang sama dan merujuk ke sini, bukan mendefinisikan ulang scope-nya sendiri.

---

## 1. Kosakata Scope

| Label | Arti |
| :--- | :--- |
| **MVP** | Wajib ada pada rilis pertama. Direncanakan, dispesifikasikan, dan masuk urutan build. |
| **Post-MVP** | Diinginkan, tapi tidak menghalangi rilis pertama. Dispesifikasikan seperlunya, tidak dibangun sekarang. |
| **Opsional / Future** | Modul yang bisa berdiri sendiri. Tidak boleh menjadi dependensi MVP. |
| **Deferred** | Sengaja dikeluarkan dari scope. Tidak boleh muncul sebagai komponen inti atau navigasi MVP. |

## 2. Kosakata Status Implementasi

Scope ≠ status. Sebuah fitur bisa berlabel **MVP** dan sekaligus **belum diimplementasikan**.

| Label | Arti |
| :--- | :--- |
| **Implemented** | Ada kodenya di repo dan bisa dijalankan. |
| **Partial** | Sebagian jalur sudah ada, sisanya masih seam kosong. |
| **Planned** | Baru dokumentasi/desain. Belum ada kode. |

---

## 3. MVP

Semua item di bawah berstatus **Planned** kecuali disebutkan lain.

| Fitur | Dokumentasi | Status implementasi |
| :--- | :--- | :--- |
| Command Center | [[02_Command_Center]] | Implemented |
| Live Activity | [[02_Command_Center]] | Implemented — transport polling, ditandai sementara |
| Threat Monitoring | [[03_Threat_Monitoring]] | Planned |
| Message Inspection | [[04_Message_Inspection]] | Planned |
| Incident Management | [[05_Incident_Management]] | Planned |
| WhatsApp Management | [[06_WhatsApp_Management]] | Partial — sesi WAHA hidup lewat compose; event `session.status` sudah diterima gateway, UI belum ada |
| User & Risk Management | [[07_Users_and_Risk]] | Planned |
| Security Policies | [[02_Security_Policies]] | Planned |
| Detection Rules | [[03_Detection_Rules]] | Planned |
| Alert Center | [[04_Alert_Center]] | Planned |
| Audit Logs | [[05_Audit_Logs]] | Partial — `message_logs` sudah terisi tiap pesan; tabel audit aksi operator belum ada. Login sekarang tercatat (`operators.last_login_at` + baris `operator_sessions` berisi user agent dan IP), tapi itu jejak sesi, bukan jejak aksi |
| Knowledge Base | [[03_Knowledge_Base]] | Partial — collection Qdrant terisi lewat ingestion `fact_items`; upload dokumen operator (parsing, chunking) belum ada |
| Operator Feedback (Human-in-the-Loop) | [[04_Datasets_and_Operator_Feedback]] | Planned |
| Dataset Management | [[04_Datasets_and_Operator_Feedback]] | Planned |
| AI / ML Control Center | [[02_ML_Control_Center_Overview]] | Planned |
| Training Jobs | [[05_Training_Jobs]] | Planned |
| Model Evaluation | [[06_Model_Evaluation]] | Planned |
| Model Registry | [[07_Model_Registry_and_Deployment]] | Planned |
| Basic Service Health | [[08_Service_Health]] | Implemented — enam service diprobe gateway, layar Service Health ada |
| Operator Authentication | [[06_Platform_Security_Requirements]] | Implemented — login email + password, sesi server-side 8 jam ([[Implement_Operator_Auth]]) |
| Authorization / RBAC | [[07_Users_and_Risk]] | Planned — tidak ada role; setiap operator melihat seluruh panel |

Fondasi MVP yang sudah **Implemented** di repo (bukan fitur produk, tapi prasyaratnya):

- WAHA webhook intake + verifikasi `X-Api-Key` (`backend/app/api/v1/endpoints/webhook.py`)
- Rate limiter sliding-window Redis per `(session, chat_id)` (`backend/app/core/rate_limit.py`)
- Redis queue + Celery worker dengan retry/backoff (`backend/app/worker/`)
- Migrasi schema PostgreSQL idempotent (`backend/app/db/`)
- Bootstrap collection Qdrant + payload index (`backend/app/vector/qdrant_setup.py`)
- Anonimisasi `user_hash` SHA-256 bersalt (`backend/app/core/hashing.py`)

Ditambahkan 2026-08-09 ([[00_Sprint_2_Completion_Notes]]):

- Autentikasi operator: tabel `operators` + `operator_sessions`, endpoint `/auth/login|logout|me`, gate `require_operator` di seluruh router Control Panel, halaman `/login` dan shell sidebar shadcn/ui
- Toolchain Python disatukan ke `uv` (`pyproject.toml` + `uv.lock`, tanpa `requirements.txt`)
- Dispatch balasan WhatsApp **terverifikasi live** ke sesi WAHA nyata

Ditambahkan 2026-08-08 ([[00_Sprint_1_Completion_Notes]]):

- Pipeline deteksi lengkap: normalisasi, ekstraksi URL, Detection Rules + intent routing, verifikasi RAG, reputasi URL, risk assessment, generasi balasan, dispatch WAHA, baris audit (`backend/app/pipeline/`, `backend/app/clients/`)
- ML Service standalone dengan registry model, readiness terpisah dari liveness, dan kontrak error terstruktur (`ml-service/`)
- Ingestion knowledge `fact_items` → Qdrant lewat ML Service (`backend/app/scripts/ingest_knowledge.py`)
- API agregasi Control Panel + shell navigasi + Command Center + Service Health

---

## 4. Post-MVP

| Fitur | Alasan ditunda |
| :--- | :--- |
| Advanced Incident Correlation | Korelasi otomatis lintas pesan/user butuh volume data produksi dulu. MVP cukup grouping manual oleh operator. |
| Advanced Threat Intelligence | Feed eksternal & enrichment terstruktur di luar VirusTotal/Safe Browsing. |
| Advanced Reporting | Laporan periodik, export terjadwal, ringkasan eksekutif. |
| Automated Dataset Pipelines | Kurasi dataset otomatis dari trafik produksi. MVP: kurasi manual + validasi operator. |
| Advanced RAG Workflows | Multi-hop retrieval, re-ranking, query rewriting. MVP: single-shot retrieval + threshold. |
| Advanced Security Automation | Playbook respons otomatis berantai. MVP: policy action tunggal per deteksi. |
| Automated Retraining Workflows | Retraining terjadwal/terpicu otomatis. MVP: training job selalu dimulai eksplisit oleh operator. |
| Advanced Model Experimentation | A/B model, shadow deployment, hyperparameter sweep. |
| B2G Spatial Heatmap Dashboard | Butuh field wilayah pada data model, dan keputusan privasi yang belum diambil. Lihat [[03_Pitching_Narrative]]. |

---

## 5. Opsional / Future

| Fitur | Catatan |
| :--- | :--- |
| APK Inspector | Modul independen. **Bukan** dependensi arsitektur MVP dan tidak boleh dicampur ke pipeline deteksi WhatsApp. Lihat [[06_Optional_APK_Inspector]]. |
| APK Malware Analysis | Bagian dari modul yang sama. |
| Advanced Android Security Analysis | Bagian dari modul yang sama. |

Konsekuensi: kategori ancaman `FILE_APK` tetap **dikenali dan dicatat** oleh pipeline MVP (klasifikasi + peringatan generik "jangan pasang file APK dari WhatsApp"), tapi **analisis statik APK tidak dilakukan** di MVP.

---

## 6. Deferred (sengaja dikeluarkan)

| Item | Alasan |
| :--- | :--- |
| Dedicated Analytics Service | Bukan service inti. Kebutuhan agregasi MVP dilayani oleh FastAPI Gateway langsung dari PostgreSQL. |
| Infrastructure Analytics | Dashboard tren CPU/RAM/disk jangka panjang, BI performa infrastruktur. |
| Advanced Infrastructure BI | Analisis tren operasional lanjutan. |

**Yang tetap boleh ada:** basic service health (up/down per service). Itu operational health monitoring, bukan Infrastructure Analytics. Lihat [[08_Service_Health]].

---

## 7. Roadmap Urutan Build

Urutan mengikuti dependensi teknis, bukan prioritas bisnis semata.

```text
Fase 0 — Fondasi ✅ selesai
  Webhook intake, auth, rate limit, queue, worker, schema, Qdrant bootstrap

Fase 1 — Pipeline deteksi ✅ sebagian besar selesai (2026-08-08)
  ✅ Preprocessing, Detection Rules, Risk Assessment, Action, Audit trail
  ⬜ ML Service klasifikasi berbasis model terlatih
  ⬜ Security Policy evaluation bergradasi

Fase 2 — Control Panel MVP  (sebagian selesai)
  ✅ Command Center, Service Health
  ✅ Autentikasi operator (email + password, sesi server-side)
  ⬜ RBAC, Threat Monitoring, Message Inspection, WhatsApp Management

Fase 3 — Operasi keamanan
  Incident Management, Alert Center, Audit Logs, Users & Risk, Policies UI

Fase 4 — AI/ML Control Center
  Knowledge Base ingestion, Operator Feedback, Dataset Management,
  Training Jobs, Evaluation, Model Registry

Fase 5 — Post-MVP
  Item pada §4, sesuai prioritas saat itu
```

---

**Related:** [[01_Problem_Statement]] · [[02_Value_Proposition]] · [[01_System_Architecture]] · [[01_Control_Panel_Overview]] · [[02_ML_Control_Center_Overview]]
