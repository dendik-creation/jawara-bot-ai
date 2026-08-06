# Spesifikasi Tech Stack & Deployment

Dokumen ini memuat Rincian Spesifikasi Teknologi yang digunakan dalam membangun platform **JAWARA: Jaringan Asisten WhatsApp Anti-Rekayasa & Ancaman (Smart Family Guard)** berarsitektur **WAHA WhatsApp HTTP API Self-Hosted** beserta pertimbangan teknis pemilihan stack.

---

## 1. Tabel Matriks Tech Stack

| Layer / Komponen        | Teknologi Terpilih                        | Versi                      | Alasan Pemilihan & Keunggulan Utama                                                                                                                   |
| :---------------------- | :---------------------------------------- | :------------------------- | :---------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Messaging Engine**    | **WAHA (WhatsApp HTTP API)**              | `devlikeapro/waha:latest`  | Engine WhatsApp self-hosted berbasis Docker. Menyediakan REST API lokal, WebSocket/Webhook event, bebas biaya per-pesan, dan kontrol penuh atas sesi. |
| **Backend Framework**   | **Python (FastAPI)**                      | `0.110+`                   | Dukungan async native (ASGI) yang sangat cepat, integrasi mudah dengan library AI/ML Python, dan otogenerasi OpenAPI spec.                            |
| **Task Queue & Broker** | **Redis + Celery**                        | `Redis 7.2` / `Celery 5.3` | Mencegah timeout pada webhook WAHA dengan mengalihkan pemrosesan berat (OCR/LLM) ke antrean async worker.                                             |
| **Relational Database** | **PostgreSQL**                            | `16.x`                     | Database relational yang andal untuk audit log anonim, metadata fakta, serta indeks b-tree/hash yang efisien.                                         |
| **Vector Database**     | **Qdrant**                                | `1.8+`                     | Vector DB yang sangat ringan, cepat, hemat memori, mendukung *HNSW indexing*, payload filtering, dan sangat Docker-friendly.                          |
| **RAG Framework**       | **LlamaIndex**                            | `0.10+`                    | Framework RAG terdepan untuk indexing dokumen, prompt orchestration, dan integrasi mulus dengan Qdrant DB.                                            |
| **Embedding Model**     | **`text-embedding-3-small` / `IndoBERT`** | -                          | Presisi tinggi dalam memahami konteks semantik dan struktur kalimat Bahasa Indonesia.                                                                 |
| **OCR Engine**          | **EasyOCR / Tesseract**                   | `1.7+`                     | Mampu menguraikan teks tulisan pada flyer, infografis, dan tangkapan layar percakapan dalam Bahasa Indonesia.                                         |
| **LLM Engine**          | **OpenAI GPT-4o-mini / Claude 3.5 Haiku** | -                          | Latensi sangat rendah (< 1 detik), biaya terjangkau, dan sangat patuh terhadap batasan System Prompt.                                                 |
| **Frontend Dashboard**  | **Next.js (App Router) + ShadcnUI**       | `14.2+` / `v4`             | Framework React modern untuk visualisasi dashboard analitik B2G / instansi pemerintah secara responsif.                                               |

---

## 2. Infrastructure & Containerization Setup

Seluruh layanan dikemas menggunakan **Docker & Docker Compose** dengan menyertakan container **WAHA (WhatsApp HTTP API)**:

```yaml
# Docker Compose Production Architecture
version: "3.8"

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

## 3. Estimasi Latensi & Batasan Opsional

* **Local WAHA Webhook Target:** $< 50\text{ ms}$ (WAHA container ke FastAPI Gateway).
* **End-to-End Latency Target:** $< 3.0\text{ detik}$ (dari pesan dikirim hingga balasan WAHA terkirim).
* **Cost Efficiency:** Penggunaan WAHA self-hosted menghemat 100% biaya per pesan Meta WhatsApp API, sementara `text-embedding-3-small` dan `GPT-4o-mini` menghemat biaya AI tanpa mengurangi presisi.

---

**Related:** [[01_System_Architecture]] · [[02_Data_Pipeline]]