# Sprint 1 — Catatan Penyelesaian

Catatan penyelesaian 10 task ToDo di [[TASKS]]. Dokumen ini adalah **indeks**: setiap task yang punya batasan, keputusan, atau bagian yang tidak bisa diverifikasi punya catatan sendiri di folder ini.

Tanggal eksekusi: **2026-08-08**.

---

## 1. Ringkasan Status

| Task | Kode | Verifikasi live | Catatan |
| :--- | :--- | :--- | :--- |
| [[Implement Text Normalizer]] | Selesai | ✅ unit test | — |
| [[Implement URL Extractor]] | Selesai | ✅ unit test | — |
| [[Build Intent Router]] | Selesai | ✅ live pipeline | [[Build_Intent_Router]] |
| [[Integrate Safe Browsing]] | Selesai (kode) | ⚠️ tanpa API key | [[Integrate_Safe_Browsing]] |
| [[Integrate VirusTotal]] | Selesai (kode) | ⚠️ tanpa API key | [[Integrate_VirusTotal]] |
| [[Build Text Verification Pipeline]] | Selesai | ✅ live RAG, skor 0.87 | [[Build_Text_Verification_Pipeline]] |
| [[Generate LLM Responses]] | Selesai (kode) | ⚠️ provider offline | [[Generate_LLM_Responses]] |
| [[Implement WhatsApp Response Sender]] | Selesai (kode) | ⚠️ sesi WA belum pairing | [[Implement_WhatsApp_Response_Sender]] |
| [[Create Audit Logging]] | Selesai | ✅ row nyata di PostgreSQL | [[Create_Audit_Logging]] |
| [[Implement Command Center Dashboard]] | Selesai | ✅ data nyata dari gateway | [[Implement_Command_Center_Dashboard]] |

Keputusan terbuka yang tetap terbuka setelah sprint ini: [[Open_Decisions_Carried_Forward]].

---

## 2. Apa yang Bertambah di Repo

**Service baru — `ml-service/`** (sebelumnya berstatus Planned):

```
ml-service/
  app/api/v1/endpoints/   health (liveness+readiness), inference, knowledge
  app/embeddings/         base, hashing (offline), openai
  app/llm/                base, prompt, validator, anthropic, openai, template
  app/models/registry.py  peta name+version → instance, dimuat sekali saat startup
  app/rag/qdrant_repo.py  retrieval + upsert (satu-satunya pemilik akses Qdrant)
  prompts/system_prompt.txt   salinan verbatim system prompt dari vault
```

**Gateway — `backend/app/`:**

```
clients/     ml_client, safe_browsing, virustotal, waha_client, reputation
pipeline/    categories, normalizer, url_extractor, intent_router,
             url_safety, orchestrator
services/    message_log (audit), dashboard (agregasi), health (probe 6 service)
scripts/     seed_facts, ingest_knowledge
api/v1/endpoints/dashboard.py   Control Panel read API
```

**Frontend — `frontend/`:** shell navigasi Control Panel, layar Command Center, layar Service Health, `lib/api.ts`, `hooks/use-polling.ts`.

**Infra:** service `ml-service` di `docker-compose.yml` (healthcheck berbasis **readiness**, bukan liveness), build args `NEXT_PUBLIC_*` untuk frontend, variabel baru di `.env.example`.

---

## 3. Bukti Verifikasi End-to-End

Dijalankan pada stack Docker penuh (7 container sehat) tanggal 2026-08-08:

```text
POST /api/v1/webhook  →  200, X-Queued: 1
worker: intent HEALTH_HOAX, engine text_verification,
        match_count 1, similarity 0.8707, risk HIGH,
        logged true
PostgreSQL: message_logs row e2e_test_001
        chat_type PERSONAL, input_type TEXT,
        detected_intent HEALTH_HOAX, risk_score HIGH,
        similarity 0.8707, user_hash ter-hash 64 char
```

Kiriman ulang `waha_message_id` yang sama menghasilkan `logged: false` dan **tidak** menambah row — idempotency lewat constraint UNIQUE bekerja.

Pesan kedua (link phishing, chat grup) tercatat sebagai `PHISHING_LINK` / `URL_LINK` / `GROUP` dengan `risk UNKNOWN` dan degradasi `url_intel_unavailable`, karena kedua API key threat intel kosong. Itu perilaku yang benar: tanpa penyedia, sistem berkata "tidak tahu", bukan "aman".

Jumlah test: **154 lulus** (`backend/`, termasuk integration dengan PostgreSQL/Redis/Qdrant nyata) dan **69 lulus** (`ml-service/`, termasuk integration Qdrant nyata). Frontend: `bun run lint`, `bun run typecheck`, `bun run build` bersih.

---

## 4. Yang Tidak Dikerjakan (dan alasannya)

| Item | Alasan |
| :--- | :--- |
| OCR (`POST /v1/ocr`) | Di luar scope Sprint 1 — task normalizer menyebut "no OCR-sourced text this milestone" |
| `POST /v1/classify` berbasis model | Belum ada model terlatih. Endpoint ada dan menjawab error terstruktur `model_not_available`; gateway jatuh ke Detection Rules ([[02_Data_Pipeline]] §6) |
| Engine `FINANCIAL_FRAUD` | Post-MVP. Router mengklasifikasi kategorinya, lalu route ke `unsupported` — bukan diam-diam dipetakan ke engine lain |
| Analisis statik APK | Opsional / Future ([[06_Optional_APK_Inspector]]). Lampiran `.apk` tetap dideteksi dan diperingatkan |
| Tabel threats / incidents / alerts | Bukan bagian dari 10 task ini. Panel terkait di dashboard melaporkan `available: false` |
| Auth operator + RBAC | Fase 2. Sementara ada `DASHBOARD_API_KEY` — lihat [[Implement_Command_Center_Dashboard]]. **Sudah tidak berlaku sejak 2026-08-09:** auth operator ada, `DASHBOARD_API_KEY` dihapus, RBAC tetap Planned ([[Implement_Operator_Auth]]) |
| Fallback Postgres full-text saat Qdrant mati | Task menyebutnya "defer unless time allows" |

---

**Related:** [[TASKS]] · [[05_Product_Scope_and_Roadmap]] · [[01_System_Architecture]] · [[Open_Decisions_Carried_Forward]]
