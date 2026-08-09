# Spesifikasi Tech Stack & Deployment

Dokumen ini memuat Rincian Spesifikasi Teknologi platform **JAWARA — Jaringan Asisten WhatsApp Anti-Rekayasa & Ancaman** beserta pertimbangan teknis pemilihan stack.

---

## 1. Tabel Matriks Tech Stack

Kolom **Status** mengikuti kosakata di [[05_Product_Scope_and_Roadmap]] §2.

| Layer / Komponen        | Teknologi Terpilih                        | Versi                      | Status | Alasan Pemilihan & Keunggulan Utama                                                                                                                   |
| :---------------------- | :---------------------------------------- | :------------------------- | :--- | :---------------------------------------------------------------------------------------------------------------------------------------------------- |
| **WhatsApp Integration**| **WAHA (WhatsApp HTTP API)**              | `devlikeapro/waha:latest`  | Implemented | Engine WhatsApp self-hosted berbasis Docker. Menyediakan REST API lokal, webhook event, bebas biaya per-pesan, dan kontrol penuh atas sesi. |
| **API Gateway**         | **Python (FastAPI)**                      | `0.110+`                   | Implemented | Async native (ASGI), integrasi mudah dengan ekosistem Python, otogenerasi OpenAPI spec. Berperan sebagai gateway API, bukan tempat kode ML. |
| **Task Queue & Broker** | **Redis + Celery**                        | `Redis 7.2` / `Celery 5.3` | Implemented | Mencegah timeout webhook WAHA dengan mengalihkan pemrosesan berat ke antrean async worker. Redis juga dipakai untuk rate limiting dan cache. |
| **Relational Database** | **PostgreSQL**                            | `16.x`                     | Partial | Sistem pencatatan relasional utama: users, threats, incidents, policies, audit, metadata AI/ML ([[01_PostgreSQL_Schema]]).                  |
| **Vector Database**     | **Qdrant**                                | `1.8+`                     | Implemented | Retrieval vektor untuk Knowledge Base/RAG. HNSW indexing, payload filtering, Docker-friendly ([[02_VectorDB_Specifications]]).              |
| **ML Service**          | **FastAPI (proses terpisah)**             | `0.110+`                   | Partial | Service standalone di `ml-service/`. Sudah: embed, rag-query, generate, kb/upsert, health/ready. Belum: classify berbasis model, OCR, train, evaluate ([[04_ML_Service]]). |
| **RAG Framework**       | **`qdrant-client` langsung (tanpa LlamaIndex)** | `1.8.2`              | Implemented | Retrieval MVP adalah single-shot embed + filtered search + threshold. LlamaIndex tidak dipakai: ia menambah lapisan abstraksi tanpa menambah kemampuan pada bentuk query ini. Pertimbangkan lagi bila multi-hop retrieval / re-ranking masuk scope (Post-MVP). |
| **Embedding Model**     | **`hash-embed-v0` (default) / `text-embedding-3-small` / `IndoBERT`** | - | Partial | Default `hash-embed-v0`: deterministik, offline, **leksikal bukan semantik**. Set `EMBEDDING_PROVIDER=openai` untuk semantik nyata. Dimensi adalah config (`EMBEDDING_DIM`): 1536 / 768 ([[Build_Text_Verification_Pipeline]]). |
| **OCR Engine**          | **EasyOCR / Tesseract**                   | `1.7+`                     | Planned | Ekstraksi teks flyer/infografis/tangkapan layar. Di luar scope Sprint 1. Dimuat sekali per proses ML Service, bukan per request.             |
| **LLM Engine**          | **Anthropic Claude Haiku** (`claude-haiku-4-5`) | -                    | Partial | **Keputusan diambil 2026-08-08** — alasan di [[Generate_LLM_Responses]]. `openai` (`gpt-4o-mini`) diimplementasikan sebagai pembanding; `template` adalah komposer deterministik offline saat tidak ada API key. Kontrak `/v1/generate` tetap provider-agnostic. |
| **Frontend Control Panel** | **Next.js (App Router) + shadcn/ui**   | Next.js 16.x / React 19.x  | Partial | Shell navigasi + Command Center + Service Health sudah ada; layar lain dan auth operator belum ([[01_Control_Panel_Overview]]).             |

---

## 2. Infrastructure & Containerization Setup

Seluruh layanan dikemas menggunakan **Docker & Docker Compose**. Compose nyata ada di `docker-compose.yml` root repo dengan 8 service: `waha`, `api-gateway`, `celery-worker`, `ml-service`, `postgres`, `qdrant`, `redis`, `frontend-dashboard` — semuanya ber-healthcheck dan memakai host port dari `.env`.

`ml-service` memakai healthcheck berbasis **readiness** (`GET /v1/ready`, model sudah dimuat), bukan liveness, sesuai [[04_ML_Service]] §6. Ia bisa diskalakan sendiri (`docker compose up --scale ml-service=N`); satu worker uvicorn per container disengaja, karena instance model tinggal di memori proses.

`frontend-dashboard` menerima `NEXT_PUBLIC_*` sebagai **build arg**, bukan environment runtime — Next.js meng-inline nilai itu ke bundle klien saat build, jadi environment runtime tidak pernah sampai ke browser.

Blok di bawah adalah **contoh referensi** (disederhanakan, bukan salinan file nyata). Prosedur menjalankan yang akurat ada di [[01_Dev_Environtment]] dan [[02_Prod_Environtment]].

```yaml
# Contoh referensi — bukan isi docker-compose.yml yang sebenarnya
services:
  # WAHA WhatsApp HTTP API Engine (Self-Hosted)
  waha:
    image: devlikeapro/waha:latest
    container_name: jawara-waha
    restart: always
    ports:
      - "3000:3000"
    environment:
      - WAHA_DASHBOARD_USERNAME=${WAHA_DASHBOARD_USERNAME}
      - WAHA_DASHBOARD_PASSWORD=${WAHA_DASHBOARD_PASSWORD}
      - WAHA_API_KEY=${WAHA_API_KEY}
      - WHATSAPP_HOOK_URL=http://api-gateway:8000/api/v1/webhook
      - WHATSAPP_HOOK_EVENTS=message,message.any
    volumes:
      - waha_sessions:/app/.sessions

  # FastAPI Backend Gateway
  api-gateway:
    build: ./backend
    container_name: jawara-gateway
    restart: always
    ports:
      - "8000:8000"
    environment:
      - DATABASE_URL=postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@postgres:5432/jawara
      - QDRANT_HOST=qdrant
      - REDIS_URL=redis://redis:6379/0
      - WAHA_API_URL=http://waha:3000
      - WAHA_API_KEY=${WAHA_API_KEY}
    depends_on:
      - postgres
      - redis
      - waha

  # Celery Async Worker Pool
  celery-worker:
    build: ./backend
    container_name: jawara-worker
    command: celery -A app.worker worker --loglevel=info
    environment:
      - DATABASE_URL=postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@postgres:5432/jawara
      - QDRANT_HOST=qdrant
      - REDIS_URL=redis://redis:6379/0
      - WAHA_API_URL=http://waha:3000
      - WAHA_API_KEY=${WAHA_API_KEY}
    depends_on:
      - redis
      - qdrant

  # Relational Database
  postgres:
    image: postgres:16-alpine
    container_name: jawara-postgres
    environment:
      - POSTGRES_DB=jawara
      - POSTGRES_USER=${POSTGRES_USER}
      - POSTGRES_PASSWORD=${POSTGRES_PASSWORD}
    volumes:
      - postgres_data:/var/lib/postgresql/data

  # Vector Database
  qdrant:
    image: qdrant/qdrant:v1.8.0
    container_name: jawara-qdrant
    ports:
      - "6333:6333"
    volumes:
      - qdrant_data:/qdrant/storage

  # Redis Broker
  redis:
    image: redis:7.2-alpine
    container_name: jawara-redis

  # Frontend Dashboard
  frontend-dashboard:
    build: ./frontend
    container_name: jawara-dashboard
    ports:
      - "3001:3000"
    environment:
      - NEXT_PUBLIC_API_URL=http://localhost:8000

volumes:
  waha_sessions:
  postgres_data:
  qdrant_data:
```

---

## 3. Estimasi Latensi & Pertimbangan Biaya

* **Local WAHA Webhook Target:** $< 50\text{ ms}$ (WAHA container ke FastAPI Gateway).
* **Webhook ack:** $< 200\text{ ms}$ — sudah tercapai lewat offload async ke Redis queue.
* **End-to-End Latency Target:** $< 3.0\text{ detik}$ (dari pesan diterima hingga balasan terkirim). Target ini **belum diukur** karena pipeline deteksi belum lengkap.
* **Budget timeout per panggilan ML Service** diusulkan di [[04_ML_Service]] §4, dipotong dari anggaran 3 detik di atas.
* **Cost Efficiency:** WAHA self-hosted menghilangkan biaya per pesan Meta WhatsApp API. Biaya AI bergantung pada keputusan provider LLM yang masih terbuka.

---

## 4. Keputusan Teknis yang Masih Terbuka

| Keputusan | Status | Dampak |
| :--- | :--- | :--- |
| Provider LLM | **Ditutup 2026-08-08: Anthropic Claude Haiku** | Alasan pemilihan dan implikasinya di [[Generate_LLM_Responses]] |
| Toolchain dependency Python (`uv` vs `pip`) | **Ditutup 2026-08-09: `uv`** | Satu manifest per service (`pyproject.toml` + `uv.lock`); `requirements*.txt` dihapus, kedua `Dockerfile` memakai `uv sync --locked --no-dev` |
| Transport live activity feed (SSE / WebSocket / polling) | Terbuka | Sementara memakai polling dan ditandai sementara di respons API ([[02_Command_Center]]) |
| Retention policy `message_logs.extracted_text` | Terbuka, makin mendesak | Kolomnya kini benar-benar terisi. Mitigasi sementara: flag `LOG_MESSAGE_CONTENT` ([[Create_Audit_Logging]]) |
| Anggaran latensi vs `WAHA_SEND_TIMEOUT_SECONDS` | Terbuka, baru | Timeout kirim 5 detik lebih besar dari seluruh target 3 detik ([[Implement_WhatsApp_Response_Sender]]) |

Daftar lengkap keputusan terbuka setelah Sprint 1: [[Open_Decisions_Carried_Forward]].

---

**Related:** [[01_System_Architecture]] · [[02_Data_Pipeline]] · [[04_ML_Service]] · [[05_Integrations]] · [[02_Prod_Environtment]]