# Development Environment — Hybrid Run (Compose Infra + Local App)

Panduan ini untuk development sehari-hari: **infra berat** (WAHA, PostgreSQL, Redis, Qdrant) jalan di Docker Compose, sementara **backend (FastAPI)** dan **frontend (Next.js)** dijalankan langsung via CLI lokal (hot-reload, debugging cepat, tanpa rebuild image tiap ganti kode).

---

## 1. Prerequisites

| Tool | Versi | Catatan |
|---|---|---|
| Docker + Docker Compose | terbaru | untuk waha/postgres/redis/qdrant |
| Python | 3.11+ | sama dengan target image `backend/Dockerfile` |
| pip | — | dependency manager backend (`requirements-dev.txt`) |
| Bun | terbaru | package manager frontend (lihat `frontend/README.md`) |

---

## 2. Setup `.env`

Copy `.env.example` → `.env` di root repo, isi semua value (`WAHA_DASHBOARD_USERNAME/PASSWORD`, `WAHA_API_KEY`, `POSTGRES_*`, `USER_HASH_SALT`). Compose infra-only step di bawah tetap butuh file ini.

```bash
cp .env.example .env
```

---

## 3. Jalankan infra-only via Docker Compose

Jangan `docker compose up` tanpa argumen (itu akan build & start `api-gateway`, `celery-worker`, `frontend-dashboard` juga). Sebutkan service eksplisit:

```bash
docker compose up -d waha postgres redis qdrant
```

Cek semua sehat:

```bash
docker compose ps
```

| Service | Host Port (`.env` var, default) | Health Check |
|---|---|---|
| waha | `WAHA_PORT` (3000) | http://localhost:3000/ |
| postgres | `POSTGRES_PORT` (5432) | `docker compose exec postgres pg_isready -U <POSTGRES_USER>` |
| redis | `REDIS_PORT` (6379) | `docker compose exec redis redis-cli ping` |
| qdrant | `QDRANT_PORT` (6333) | http://localhost:6333/healthz |

Semua host port datang dari `.env` (`WAHA_PORT`, `API_GATEWAY_PORT`, `QDRANT_PORT`, `FRONTEND_PORT`, `POSTGRES_PORT`, `REDIS_PORT`), bukan hardcoded di compose — ganti value di `.env` kalau port bentrok, tidak perlu edit `docker-compose.yml`.

`postgres` dan `redis` published ke host lewat `${POSTGRES_PORT}:5432` / `${REDIS_PORT}:6379` khusus supaya backend/frontend yang dijalankan **di luar** `jawara-net` (kasus dev hybrid ini) bisa connect ke `localhost:<port>`. Kalau file `.env` lama tidak punya `POSTGRES_PORT`/`REDIS_PORT`, tambahkan manual — tanpa var ini compose gagal publish port dan backend lokal tidak bisa connect (lihat §6).

---

## 4. Jalankan Backend (FastAPI) — CLI lokal

```bash
cd backend
python -m venv .venv
source .venv/Scripts/activate

pip install -r requirements-dev.txt
```

Set environment variables (proses lokal di luar `jawara-net` — hostname docker seperti `postgres`/`redis`/`waha` **tidak resolve**; pakai `localhost` + port host yang di-publish/di-override):

```bash
export DATABASE_URL="postgresql://<POSTGRES_USER>:<POSTGRES_PASSWORD>@localhost:5432/<POSTGRES_DB>"
export REDIS_URL="redis://localhost:6379/0"
export QDRANT_HOST="localhost"
export QDRANT_PORT="6333"
export WAHA_API_URL="http://localhost:3000"
export WAHA_API_KEY="<sama dengan WAHA_API_KEY di .env>"

# Celery broker/result backend (DB 0 = queue, DB 1 = hasil task)
export CELERY_BROKER_URL="redis://localhost:6379/0"
export CELERY_RESULT_BACKEND="redis://localhost:6379/1"

# Salt anonimisasi user_hash — samakan dengan USER_HASH_SALT di .env,
# beda salt = beda user_hash = row user_subscriptions tidak match
export USER_HASH_SALT="<sama dengan USER_HASH_SALT di .env>"
```

Bootstrap data layer (sekali per database/volume baru, aman diulang):

```bash
python -m app.db.migrate            # apply schema PostgreSQL (idempotent)
python -m app.vector.qdrant_setup   # buat collection fact_knowledge_base + payload index
```

`qdrant_setup` mencetak config live-nya untuk dicocokkan dengan tabel di [[02_VectorDB_Specifications]].

Jalankan dengan hot-reload:

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Verifikasi:

```bash
curl http://localhost:8000/health
```

Jalankan unit test:

```bash
pytest -q -m "not integration"   # murni unit, tanpa infra
pytest -q                        # + integration test (butuh postgres/redis/qdrant hidup)
```

Test bertanda `integration` otomatis **skip** kalau service-nya tidak reachable atau `DATABASE_URL` tidak valid — jadi `pytest -q` tetap hijau di mesin tanpa infra, tapi tidak diam-diam melewatkan kegagalan nyata.

---

## 4b. Jalankan Celery Worker — CLI lokal

Terminal terpisah, venv dan environment variable yang sama seperti §4:

```bash
cd backend
source .venv/Scripts/activate
celery -A app.worker worker --loglevel=info --pool=solo
```

`--pool=solo` **wajib di Windows** — pool prefork default Celery tidak jalan di Windows. Container (Linux) tetap pakai prefork, tidak perlu flag ini.

Verifikasi worker melahap job:

```bash
curl -X POST http://localhost:8000/api/v1/webhook \
  -H "X-Api-Key: <WAHA_API_KEY>" -H "Content-Type: application/json" \
  -d '{"event":"message.any","session":"default","payload":{"id":"dev_1","from":"628111@c.us","body":"tes"}}'
```

Log worker (JSON satu baris per event) akan memuat `waha_message_id` yang sama dengan log gateway — itu correlation ID-nya. Cek antrean langsung:

```bash
docker compose exec redis redis-cli LLEN jawara.messages   # 0 = worker sudah menghabiskan queue
```

### Rate limit

Gateway membatasi **20 request / 60 detik per (session, chat_id)** (sliding window Redis). Request ke-21 dalam window balas `429` + header `Retry-After`. Saat load test manual, ganti `payload.from` atau turunkan/naikkan `RATE_LIMIT_MAX_REQUESTS` di `.env` — jangan ubah kode.

Kalau Redis mati, rate limiter **fail open** (request diteruskan, kegagalan di-log). Kalau broker mati, webhook tetap balas `200` tapi dengan header `X-Queued: 0` — event-nya hilang, dan itu tercatat sebagai `enqueue failed` di log gateway.

### Troubleshooting: `/health` balas `{"status":"degraded","dependencies":{"database":false,"redis":false}}`

Root cause: `postgres`/`redis` container tidak reachable dari `localhost` — biasanya karena salah satu dari ini:

1. **`.env` belum punya `POSTGRES_PORT`/`REDIS_PORT`.** Compose butuh dua var ini untuk publish port container ke host (`${POSTGRES_PORT}:5432`, `${REDIS_PORT}:6379`). Tambahkan ke `.env` (lihat `.env.example`), lalu `docker compose up -d postgres redis` ulang.
2. **`docker compose ps` menunjukkan `postgres`/`redis` belum `healthy`.** Tunggu healthcheck selesai (`start_period` 10s/5s) sebelum test `/health`.
3. **`DATABASE_URL`/`REDIS_URL` di shell backend masih mengarah ke hostname docker (`postgres`/`redis`) bukan `localhost`.** Proses lokal ada di luar `jawara-net`, wajib pakai `localhost:<port>` (lihat env vars di §4 atas).
4. **(Windows/Docker Desktop) `docker compose up` gagal publish port dengan error `bind: An attempt was made to access a socket in a way forbidden by its access permissions`.** Ini bug jaringan Docker Desktop, bukan masalah compose/kode — coba `docker run --rm -p <port>:80 nginx:alpine` untuk isolasi masalah (kalau ini juga gagal, publish port apa pun sedang blocked). Fix: restart Docker Desktop (quit sepenuhnya lewat tray icon, buka lagi), lalu `docker compose up -d waha postgres redis qdrant` ulang.

---

## 5. Jalankan Frontend (Next.js) — CLI lokal

```bash
cd frontend
bun install
```

Port default Next.js dev server (`3000`) **bentrok** dengan host port WAHA (`3000:3000`). Jalankan di port lain:

```bash
NEXT_PUBLIC_API_URL=http://localhost:8000 bun dev -- -p 3001
```

Buka `http://localhost:3001`.

---

## 6. Catatan penting: WAHA webhook tidak bisa mencapai backend lokal by default

`WHATSAPP_HOOK_URL` di `docker-compose.yml` hardcoded ke `http://api-gateway:8000/api/v1/webhook` — hostname ini hanya resolve **di dalam** `jawara-net`. Saat `api-gateway` tidak dijalankan via compose (kasus dev ini), WAHA container tidak bisa reach backend lokal di host.

Untuk test end-to-end webhook (WAHA → FastAPI lokal) tanpa mengubah kode:

- **Opsi A (compose override):** tambahkan di `docker-compose.override.yml` yang sama:
  ```yaml
  services:
    waha:
      environment:
        - WHATSAPP_HOOK_URL=http://host.docker.internal:8000/api/v1/webhook
  ```
  `host.docker.internal` resolve ke host machine di Docker Desktop (Windows/Mac).
- **Opsi B:** skip pairing webhook saat dev harian, test endpoint langsung:
  ```bash
  curl -X POST http://localhost:8000/api/v1/webhook \
    -H "X-Api-Key: <WAHA_API_KEY>" -H "Content-Type: application/json" \
    -d '{"event":"message.any","session":"default","payload":{"id":"1","body":"test"}}'
  ```

Celery worker sudah live (lihat §4b) — jalankan bersama backend supaya job yang masuk queue benar-benar dikonsumsi, bukan menumpuk di Redis.

---

## 7. Stop / Teardown

```bash
docker compose stop waha postgres redis qdrant   # stop, keep volumes
docker compose down                              # stop + remove containers, keep named volumes
docker compose down -v                           # DESTRUCTIVE: also wipes waha_sessions/postgres_data/qdrant_data
```

Backend lokal: `Ctrl+C`. Celery worker: `Ctrl+C`. Frontend lokal: `Ctrl+C`.

---

**Related:** [[03_Tech_Stack]] · [[01_System_Architecture]] · [[02_Prod_Environtment]] · [[TASKS]]
