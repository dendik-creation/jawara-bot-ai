# Development Environment — Hybrid Run (Compose Infra + Local App)

Panduan ini untuk development sehari-hari: **infra berat** (WAHA, PostgreSQL, Redis, Qdrant) jalan di Docker Compose, sementara **backend (FastAPI)** dan **frontend (Next.js)** dijalankan langsung via CLI lokal (hot-reload, debugging cepat, tanpa rebuild image tiap ganti kode).

> `ml-service` sudah ada di repo dan di compose ([[04_ML_Service]]). Ia dijalankan lewat Docker seperti infra lain, bukan lewat CLI lokal — modelnya dimuat sekali saat startup, jadi hot-reload tidak membantu di sana. Ingat: `container up` ≠ `ready`; pakai `GET /v1/ready`, bukan `GET /v1/health`.

---

## 1. Prerequisites

| Tool | Versi | Catatan |
|---|---|---|
| Docker + Docker Compose | terbaru | untuk waha/postgres/redis/qdrant |
| Python | 3.14 | sama dengan base image `backend/Dockerfile` dan `requires-python` di `pyproject.toml` |
| uv | ≥ 0.12 | satu-satunya dependency manager Python (`pyproject.toml` + `uv.lock`); `uv` juga yang mengunduh interpreter 3.14 kalau belum ada |
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
docker compose up -d waha postgres redis qdrant ml-service
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
| ml-service | `ML_SERVICE_PORT` (9000) | `curl -H "X-Internal-Api-Key: <ML_SERVICE_API_KEY>" http://localhost:9000/v1/ready` |

Semua host port datang dari `.env` (`WAHA_PORT`, `API_GATEWAY_PORT`, `QDRANT_PORT`, `FRONTEND_PORT`, `POSTGRES_PORT`, `REDIS_PORT`), bukan hardcoded di compose — ganti value di `.env` kalau port bentrok, tidak perlu edit `docker-compose.yml`.

`postgres` dan `redis` published ke host lewat `${POSTGRES_PORT}:5432` / `${REDIS_PORT}:6379` khusus supaya backend/frontend yang dijalankan **di luar** `jawara-net` (kasus dev hybrid ini) bisa connect ke `localhost:<port>`. Kalau file `.env` lama tidak punya `POSTGRES_PORT`/`REDIS_PORT`, tambahkan manual — tanpa var ini compose gagal publish port dan backend lokal tidak bisa connect (lihat §6).

---

## 4. Jalankan Backend (FastAPI) — CLI lokal

```bash
cd backend
uv sync
```

`uv sync` membuat `.venv` sendiri (tidak perlu `python -m venv`), memasang persis versi di `uv.lock` termasuk dependency group `dev`, dan mengunduh CPython 3.14 kalau mesin belum punya. Perintah di bawah ditulis dengan prefix `uv run` sehingga jalan tanpa aktivasi venv; `source .venv/Scripts/activate` sekali di awal juga boleh, lalu prefix-nya bisa dilepas.

Environment variable **tidak perlu di-export manual**. `app/core/config.py` membaca `.env` di root repo (path absolut, bukan relatif terhadap CWD), file yang sama dengan yang dibaca Compose — jadi backend lokal dan container tidak pernah berbeda kredensial.

Yang tidak ada di `.env` diturunkan dari komponennya, dengan host `localhost` (proses lokal ada di luar `jawara-net`, hostname docker seperti `postgres`/`redis`/`waha` **tidak resolve**):

| Yang dipakai kode | Diturunkan dari | Hasil di dev hybrid |
|---|---|---|
| `DATABASE_URL` | `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `POSTGRES_PORT` | `postgresql://<user>:<pass>@localhost:5432/<db>` |
| `REDIS_URL`, `CELERY_BROKER_URL` | `REDIS_PORT` | `redis://localhost:6379/0` |
| `CELERY_RESULT_BACKEND` | `REDIS_PORT` | `redis://localhost:6379/1` (DB 1 = hasil task, terpisah dari queue) |
| `WAHA_API_URL` | `WAHA_PORT` | `http://localhost:3000` |
| `ML_SERVICE_URL` | `ML_SERVICE_PORT` | `http://localhost:9000` |

`WAHA_API_KEY`, `ML_SERVICE_API_KEY`, `USER_HASH_SALT`, `DASHBOARD_API_KEY`, `QDRANT_COLLECTION` terbaca langsung dari `.env` — tidak ada lagi kemungkinan salt berbeda antara backend lokal dan worker (beda salt = beda `user_hash` = row `user_subscriptions` tidak match).

Environment variable asli tetap menang atas isi `.env`; itulah cara `docker-compose.yml` menyuntikkan hostname in-network (`postgres`, `redis`, `ml-service`). Untuk override satu nilai saja tanpa menyalin seluruh file, buat `backend/.env` — ia dibaca setelah `.env` root.

```bash
export DATABASE_URL="postgresql://user:pass@localhost:5433/other-db"   # hanya bila memang beda
```

Bootstrap data layer (sekali per database/volume baru, aman diulang):

```bash
uv run python -m app.db.migrate               # apply schema PostgreSQL (idempotent)
uv run python -m app.vector.qdrant_setup      # buat collection fact_knowledge_base + payload index
uv run python -m app.scripts.seed_facts       # isi fact_sources + fact_items (data demo)
uv run python -m app.scripts.ingest_knowledge # embed fact_items ke Qdrant lewat ML Service
```

`qdrant_setup` mencetak config live-nya untuk dicocokkan dengan tabel di [[02_VectorDB_Specifications]].

Dua langkah terakhir mengisi knowledge base. Tanpa itu, `POST /v1/rag-query` selalu mengembalikan `unverified: true` — bukan error, tapi tidak ada yang bisa dicocokkan. `ingest_knowledge` butuh `ml-service` hidup dan `ML_SERVICE_URL` mengarah ke sana (`http://localhost:9000` untuk dev hybrid).

`ML_SERVICE_URL`/`ML_SERVICE_API_KEY` sudah tertangani oleh tabel di atas. `GOOGLE_SAFE_BROWSING_API_KEY` dan `VIRUSTOTAL_API_KEY` boleh dikosongkan di `.env` — provider yang tidak dikonfigurasi hanya menghasilkan verdict `UNKNOWN`, bukan kegagalan pipeline. Isi dengan nilai asal-asalan justru lebih buruk: provider dianggap aktif lalu ditolak upstream.

Jalankan dengan hot-reload:

```bash
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Verifikasi:

```bash
curl http://localhost:8000/health
```

Jalankan unit test:

```bash
uv run pytest -q -m "not integration"   # murni unit, tanpa infra
uv run pytest -q                        # + integration test (butuh postgres/redis/qdrant hidup)
```

Test bertanda `integration` otomatis **skip** kalau service-nya tidak reachable atau `DATABASE_URL` tidak valid — jadi `pytest -q` tetap hijau di mesin tanpa infra, tapi tidak diam-diam melewatkan kegagalan nyata.

---

## 4b. Jalankan Celery Worker — CLI lokal

Terminal terpisah, venv yang sama seperti §4 (environment-nya ikut `.env` root, jadi tidak ada yang perlu diulang):

```bash
cd backend
uv run celery -A app.worker worker --loglevel=info --pool=solo
```

`--pool=solo` **wajib di Windows** — pool prefork default Celery tidak jalan di Windows. Container (Linux) tetap pakai prefork, tidak perlu flag ini.

Verifikasi worker melahap job. Isi `body` menentukan jalur mana yang diuji — pesan harus benar-benar mengandung klaim, bukan sekadar `"tes"`:

```bash
curl -X POST http://localhost:8000/api/v1/webhook \
  -H "X-Api-Key: <WAHA_API_KEY>" -H "Content-Type: application/json" \
  -d '{"event":"message.any","session":"default","payload":{"id":"dev_1","from":"628111@c.us","body":"Air rebusan atau perasan daun kitolod dapat menyembuhkan katarak dan membersihkan mata tanpa perlu operasi."}}'
```

Log worker akan menutup dengan satu baris `pipeline complete` berisi hasil akhirnya:

```json
{"message":"pipeline complete","waha_message_id":"dev_1","intent":"HEALTH_HOAX",
 "intent_confidence":1.0,"engine":"text_verification","risk":"HIGH","match_count":1,
 "similarity_score":0.9169,"response_dispatched":false,
 "logged":true,"degradations":["dispatch_failed:timeout"]}
```

Dua hal yang wajar berbeda di mesin sendiri:

- **`response_dispatched: false` + `dispatch_failed:*`** selama session WAHA bernama `default` belum ada / belum `WORKING`. Pipeline-nya tetap lengkap; hanya balasannya yang tidak terkirim. Cek dengan `curl -H "X-Api-Key: <WAHA_API_KEY>" http://localhost:3000/api/sessions`.
- **`similarity_score`** dengan `EMBEDDING_PROVIDER=hash` (default) bersifat **leksikal, bukan semantik** — parafrase tidak melewati `score_threshold` 0.80. Kalimat di atas sengaja dekat dengan `claim_summary` fakta demo dari `seed_facts`. Untuk mencocokkan parafrase, butuh embedder semantik (lihat [[04_ML_Service]]).

Body `"tes"` **tidak** menghasilkan output di atas, dan itu bukan kegagalan: tidak ada satu pun keyword lexicon maupun URL yang cocok, jadi skor total 0 dan router mengembalikan `intent: UNKNOWN`, `engine: none` — pipeline berhenti sebelum verifikasi. Itu perilaku yang benar untuk pesan tanpa klaim.

`degradations` adalah tempat melihat apa yang tidak berjalan: `ml_unavailable:*`, `url_intel_unavailable`, `knowledge_unverified`, `llm_fallback:*`, `dispatch_failed:*`, `audit_write_failed`. Daftar kosong berarti seluruh jalur berjalan penuh.

Log worker (JSON satu baris per event) memuat `waha_message_id` yang sama dengan log gateway — itu correlation ID-nya, dan ia berlanjut sampai ke `request_id` panggilan ML Service. Cek antrean langsung:

```bash
docker compose exec redis redis-cli LLEN jawara.messages   # 0 = worker sudah menghabiskan queue
```

### Rate limit

Gateway membatasi **20 request / 60 detik per (session, chat_id)** (sliding window Redis). Request ke-21 dalam window balas `429` + header `Retry-After`. Saat load test manual, ganti `payload.from` atau turunkan/naikkan `RATE_LIMIT_MAX_REQUESTS` di `.env` — jangan ubah kode.

Kalau Redis mati, rate limiter **fail open** (request diteruskan, kegagalan di-log). Kalau broker mati, webhook tetap balas `200` tapi dengan header `X-Queued: 0` — event-nya hilang, dan itu tercatat sebagai `enqueue failed` di log gateway.

### Troubleshooting: `password authentication failed for user "postgres"` di log worker

```
asyncpg.exceptions.InvalidPasswordError: password authentication failed for user "postgres"
```

User `postgres` tidak pernah muncul di `.env` — itu tanda proses **tidak membaca konfigurasi apa pun** dan jatuh ke placeholder lama. Penyebab historisnya: `Settings` membaca `.env` relatif terhadap CWD, sedangkan `.env` ada di root repo dan worker dijalankan dari `backend/`, jadi tidak ada file yang ketemu dan `export` di terminal lain tidak ikut terbawa.

Sudah diperbaiki — `.env` root sekarang dibaca lewat path absolut (§4). Kalau error ini masih muncul:

1. Pastikan `.env` ada di **root repo**, bukan di `backend/`.
2. Cek nilai yang benar-benar terbaca: `uv run python -c "from app.core.config import get_settings; print(get_settings().database_url)"`. Harus menampilkan `POSTGRES_USER` milikmu, bukan `postgres`.
3. Kalau `DATABASE_URL` sempat di-export ke nilai lama, `unset DATABASE_URL` — environment variable asli menang atas `.env`.

Efeknya terbatas pada `degradations: ["audit_write_failed"]`: pipeline tetap selesai dan tetap membalas, tapi tidak ada baris audit — by design, kegagalan penulisan audit tidak boleh menelan jawaban yang sudah dihasilkan.

### Troubleshooting: `ml service call failed` dengan `error: ml_unreachable`

Penyebabnya sama persis: tanpa konfigurasi, `ML_SERVICE_URL` jatuh ke `http://ml-service:9000` — hostname itu hanya resolve **di dalam** `jawara-net`. Dari proses lokal, yang benar `http://localhost:9000` (§4, diturunkan dari `ML_SERVICE_PORT`).

Cek layanannya hidup sebelum menyalahkan konfigurasi:

```bash
curl -H "X-Internal-Api-Key: <ML_SERVICE_API_KEY>" http://localhost:9000/v1/ready
```

`degradations: ["generation_unavailable:ml_unreachable"]` artinya jawaban jatuh ke template dan klasifikasi jalan dengan rules saja — bukan crash, tapi juga bukan hasil yang mau diukur saat menguji pipeline.

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

Buka `http://localhost:3001` — Command Center. Layar kedua: `/system/service-health`.

Kalau dashboard tampil tapi semua angka "belum tersedia", cek `CORS_ALLOW_ORIGINS` di backend memuat `http://localhost:3001`; browser akan memblokir responsnya secara diam-diam kalau tidak.

Saat menjalankan lewat compose (bukan CLI lokal), `NEXT_PUBLIC_API_URL` masuk sebagai **build arg** — Next.js meng-inline-nya ke bundle klien saat build, jadi mengubahnya menuntut `docker compose build frontend-dashboard`, bukan sekadar restart.

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
