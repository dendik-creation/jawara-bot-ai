# Spesifikasi Tech Stack & Deployment

Dokumen ini memuat Rincian Spesifikasi Teknologi platform **JAWARA — Jaringan Asisten WhatsApp Anti-Rekayasa & Ancaman** beserta pertimbangan teknis pemilihan stack.

---

## 1. Tabel Matriks Tech Stack

Kolom **Status** mengikuti kosakata di [[05_Product_Scope_and_Roadmap]] §2.

| Layer / Komponen        | Teknologi Terpilih                        | Versi                      | Status | Alasan Pemilihan & Keunggulan Utama                                                                                                                   |
| :---------------------- | :---------------------------------------- | :------------------------- | :--- | :---------------------------------------------------------------------------------------------------------------------------------------------------- |
| **WhatsApp Integration**| **WAHA (WhatsApp HTTP API)**              | `devlikeapro/waha:latest`  | Implemented | Engine WhatsApp self-hosted berbasis Docker. Menyediakan REST API lokal, webhook event, bebas biaya per-pesan, dan kontrol penuh atas sesi. |
| **API Gateway**         | **Python (FastAPI)**                      | `0.110+`                   | Partial | Async native (ASGI), integrasi mudah dengan ekosistem Python, otogenerasi OpenAPI spec. Berperan sebagai gateway API, bukan tempat kode ML. |
| **Task Queue & Broker** | **Redis + Celery**                        | `Redis 7.2` / `Celery 5.3` | Implemented | Mencegah timeout webhook WAHA dengan mengalihkan pemrosesan berat ke antrean async worker. Redis juga dipakai untuk rate limiting dan cache. |
| **Relational Database** | **PostgreSQL**                            | `16.x`                     | Partial | Sistem pencatatan relasional utama: users, threats, incidents, policies, audit, metadata AI/ML ([[01_PostgreSQL_Schema]]).                  |
| **Vector Database**     | **Qdrant**                                | `1.8+`                     | Partial | Retrieval vektor untuk Knowledge Base/RAG. HNSW indexing, payload filtering, Docker-friendly ([[02_VectorDB_Specifications]]).              |
| **ML Service**          | **FastAPI (proses terpisah)**             | -                          | Planned | Service standalone untuk inference, embedding, OCR, training, evaluasi. Direktori `ml-service/` belum ada ([[04_ML_Service]]).              |
| **RAG Framework**       | **LlamaIndex**                            | `0.10+`                    | Planned | Indexing dokumen, orkestrasi prompt, integrasi Qdrant. Berjalan **di dalam ML Service**, bukan di gateway.                                   |
| **Embedding Model**     | **`text-embedding-3-small` / `IndoBERT`** | -                          | Planned | Konteks semantik Bahasa Indonesia. Dimensi vektor adalah config (`EMBEDDING_DIM`): 1536 / 768.                                              |
| **OCR Engine**          | **EasyOCR / Tesseract**                   | `1.7+`                     | Planned | Ekstraksi teks flyer/infografis/tangkapan layar. Dimuat sekali per proses ML Service, bukan per request.                                     |
| **LLM Engine**          | **Belum diputuskan** (kandidat: OpenAI GPT-4o-mini / Claude Haiku) | - | Planned | Keputusan terbuka. Kontrak `/v1/generate` dirancang provider-agnostic agar pergantian provider jadi perubahan internal ML Service saja.      |
| **Frontend Control Panel** | **Next.js (App Router) + shadcn/ui**   | Next.js 16.x / React 19.x  | Planned | Control Panel operator. Repo saat ini masih scaffold `create-next-app`; belum ada layar produk ([[01_Control_Panel_Overview]]).             |

---

## 2. Infrastructure & Containerization Setup

Seluruh layanan dikemas menggunakan **Docker & Docker Compose**. Compose nyata ada di `docker-compose.yml` root repo dengan 7 service: `waha`, `api-gateway`, `celery-worker`, `postgres`, `qdrant`, `redis`, `frontend-dashboard` — semuanya ber-healthcheck dan memakai host port dari `.env`.

`ml-service` **belum ada** di compose. Saat ditambahkan nanti: `build: ./ml-service`, healthcheck berbasis readiness (model sudah dimuat, bukan sekadar proses hidup), restart policy sendiri, dan skala sendiri (`docker compose up --scale ml-service=N`). Lihat [[04_ML_Service]].

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

| Keputusan | Dampak |
| :--- | :--- |
| Provider LLM | Memblokir finalisasi kontrak `/v1/generate`, walau kontraknya sengaja dirancang provider-agnostic |
| Toolchain dependency backend (`uv` via `pyproject.toml` vs `pip` via `requirements.txt`) | Dua manifest hidup berdampingan saat ini; akan drift bila hanya satu yang diedit |
| Transport live activity feed (SSE / WebSocket / polling) | Menentukan perlu tidaknya channel pub/sub Redis tambahan ([[02_Command_Center]]) |
| Retention policy `message_logs.extracted_text` | Prasyarat privasi sebelum trafik nyata ([[01_Threat_Model_and_Data_Protection]]) |

---

**Related:** [[01_System_Architecture]] · [[02_Data_Pipeline]] · [[04_ML_Service]] · [[05_Integrations]] · [[02_Prod_Environtment]]