# Production Environment — Full Docker Compose Deployment

Panduan deploy penuh: semua 8 service (`waha`, `api-gateway`, `celery-worker`, `ml-service`, `postgres`, `qdrant`, `redis`, `frontend-dashboard`) jalan sebagai container, orchestrated oleh `docker-compose.yml` di root repo.

> Compose ini **tidak menyediakan reverse proxy atau TLS termination sendiri** — setiap service selain webhook-nya WAHA (`3000` — hanya untuk pairing/QR, lihat §5) sengaja di-bind ke `127.0.0.1`, bukan `0.0.0.0` (§1). Bawa reverse proxy sendiri (Nginx Proxy Manager, Caddy, Traefik, ...) dan hubungkan lewat Docker network, bukan port host yang di-publish.

---

## 1. Prerequisites

- Server/VM dengan Docker Engine + Docker Compose plugin terinstall.
- **Tidak ada port dari compose ini yang perlu dibuka di firewall.** Setiap `ports:` di `docker-compose.yml` sekarang di-bind eksplisit ke `127.0.0.1:<port>:<container_port>` — `waha` (3000), `api-gateway` (8000), `ml-service` (9000), `postgres` (5432), `qdrant` (6333), `redis` (6379), `frontend-dashboard` (3001, atau nilai `FRONTEND_PORT`). Semuanya reachable dari `localhost` di server itu sendiri (debugging, `docker exec`, dsb) — **tidak pernah** dari internet, terlepas dari status firewall. Redis di stack ini **tidak punya mekanisme auth sama sekali** di kodenya — binding loopback ini satu-satunya penghalang antara Redis dan internet terbuka kalau port itu sampai ter-publish.
- Reverse proxy (sudah berjalan terpisah, atau baru) + TLS certificate. Kalau reverse proxy-nya container lain (mis. Nginx Proxy Manager) di Docker network sendiri, join-kan `frontend-dashboard`/`api-gateway` ke network itu dan proxy langsung ke `<container_name>:<container_port>` (`jawara-dashboard:3000`, `jawara-gateway:8000`) lewat DNS internal Docker — **bukan** port host yang di-publish. Menambahkan network kedua ke sebuah service di `docker-compose.yml`:
  ```yaml
  services:
    frontend-dashboard:
      networks:
        - jawara-net
        - proxy-network   # nama network reverse proxy-mu

  networks:
    proxy-network:
      external: true
  ```

---

## 2. Clone & Configure

```bash
git clone <repo-url>
cd software-dev-2026
cp .env.example .env
```

Isi `.env` dengan **credential produksi asli**, bukan placeholder — setiap `changeme` di `.env.example` wajib diganti:

| Var | Catatan |
|---|---|
| `WAHA_DASHBOARD_USERNAME` / `WAHA_DASHBOARD_PASSWORD` | login dashboard WAHA — password kuat, dashboard cuma reachable dari `localhost` (§1), akses lewat SSH tunnel |
| `WAHA_API_KEY` | dipakai gateway untuk verifikasi header `X-Api-Key` — generate random string panjang |
| `POSTGRES_DB` / `POSTGRES_USER` / `POSTGRES_PASSWORD` | credential database produksi |
| `ML_SERVICE_API_KEY` | header `X-Internal-Api-Key` antara gateway dan `ml-service` — service-to-service saja, tapi tetap generate random, jangan `changeme` |
| `NEXT_PUBLIC_API_URL` | domain publik API gateway (misal `https://api.jawara.example.id`), bukan `localhost`. **Build arg**, bukan runtime env — ganti nilainya menuntut `docker compose up -d --build frontend-dashboard`, restart saja tidak cukup |
| `CORS_ALLOW_ORIGINS` | domain publik frontend (misal `https://app.jawara.example.id`) — browser diam-diam blokir response kalau origin tidak match |
| `USER_HASH_SALT` | salt SHA-256 untuk `user_hash` — generate random panjang, **jangan** pakai `changeme`. Mengganti salt setelah produksi jalan mematikan semua `user_subscriptions` lama beserta `message_logs`-nya (FK cascade) |
| `OPERATOR_EMAIL` / `OPERATOR_NAME` / `OPERATOR_PASSWORD` | akun operator Control Panel pertama — dibaca oleh `app.scripts.create_operator` saat bootstrap (§4b), bukan dipakai runtime oleh `api-gateway` sendiri |
| `LLM_PROVIDER` | `template` (default, tanpa key) / `anthropic` (`ANTHROPIC_API_KEY`) / `openai_compatible` (`LLM_BASE_URL` sampai `.../v1` + `LLM_API_KEY` + `LLM_MODEL` — endpoint apa pun berformat Chat Completions: OpenAI, OpenRouter, Groq, vLLM/Ollama self-hosted) |
| `EMBEDDING_PROVIDER` | `hash` (default, leksikal bukan semantik) / `openai` (`OPENAI_API_KEY` — punya sendiri, terpisah dari `LLM_API_KEY` di atas meski sama-sama bisa mengarah ke OpenAI) |
| `RATE_LIMIT_MAX_REQUESTS` / `RATE_LIMIT_WINDOW_SECONDS` | default `20` / `60` detik per (session, chat) |
| `QDRANT_COLLECTION` / `EMBEDDING_DIM` | `fact_knowledge_base` / `1536` (`text-embedding-3-small`); `768` kalau pindah ke IndoBERT — ganti dimensi berarti buat ulang collection dan embed ulang |
| `WAHA_PORT` / `API_GATEWAY_PORT` / `ML_SERVICE_PORT` / `QDRANT_PORT` / `FRONTEND_PORT` / `POSTGRES_PORT` / `REDIS_PORT` | host port mapping (loopback-only, §1) — ganti kalau bentrok dengan service lain di server yang sama, tidak perlu edit `docker-compose.yml` |

Jangan commit `.env` — sudah di `.gitignore`.

---

## 3. Build & Start

```bash
docker compose up -d --build
```

Compose akan start berurutan sesuai `depends_on` + `healthcheck`:

```
postgres, redis, qdrant, waha  →  ml-service  →  api-gateway, celery-worker  →  frontend-dashboard
```

`ml-service` dicek lewat **readiness** (`GET /v1/ready`, model termuat), bukan liveness — container yang "up" belum tentu "ready", jangan andalkan status container saja.

---

## 4. Verifikasi

```bash
docker compose ps
```

Semua 8 service harus `healthy`. Cek log kalau ada yang `unhealthy`/restart loop:

```bash
docker compose logs -f api-gateway
docker compose logs -f celery-worker
docker compose logs -f ml-service
docker compose logs -f waha
```

Health endpoint gateway (dari server itu sendiri, port loopback-only — §1):

```bash
curl http://127.0.0.1:8000/health
# {"status":"ok","dependencies":{"database":true,"redis":true}}

curl -H "X-Internal-Api-Key: <ML_SERVICE_API_KEY>" http://127.0.0.1:9000/v1/ready
```

---

## 4b. Bootstrap Data Layer

Sekali per deployment baru (dan setelah menambah file migrasi). Semuanya idempotent — aman diulang di setiap redeploy:

```bash
docker exec jawara-gateway python -m app.db.migrate
docker exec jawara-gateway python -m app.vector.qdrant_setup
docker exec jawara-gateway python -m app.scripts.seed_facts
docker exec jawara-gateway python -m app.scripts.ingest_knowledge

# Akun operator pertama — nothing can sign in until this exists. Baca
# OPERATOR_EMAIL/OPERATOR_NAME/OPERATOR_PASSWORD dari .env, tanpa argumen.
# Aman diulang di setiap redeploy: akun yang sudah ada dibiarkan (exit 0).
docker exec jawara-gateway python -m app.scripts.create_operator
```

`migrate` apply `app/db/migrations/*.sql` berurutan dan mencatatnya di tabel `schema_migrations`; `qdrant_setup` membuat collection `fact_knowledge_base` lalu mencetak config live-nya. Collection yang sudah ada **tidak** dibuat ulang — hanya payload index yang di-assert ulang, supaya embedding tidak terhapus.

Verifikasi:

```bash
docker exec jawara-postgres psql -U <POSTGRES_USER> -d <POSTGRES_DB> -c "\dt"
curl -H "X-Internal-Api-Key: <ML_SERVICE_API_KEY>" http://127.0.0.1:9000/v1/ready
```

### (Opsional) Threat classifier: seed data, train, evaluate, promote

Baseline TF-IDF + LogisticRegression. Tanpa model `PRODUCTION`, pipeline berjalan normal lewat Detection Rules saja — ini bukan prasyarat bot berfungsi, murni untuk mengaktifkan sinyal ML tambahan.

```bash
docker exec jawara-gateway python -m app.scripts.seed_dataset_samples
```

Membuat dua dataset VALIDATED sintetis (`core-detection-train` 240 sample, `core-detection-eval` 60 sample) — cukup untuk membuktikan mekanisme training/evaluasi/promosi jalan, bukan akurasi produksi. Data asli/lebih besar: tambah sample lewat Control Panel `/datasets` sebelum training job dibuat.

Training job, evaluation, dan promosi dijalankan lewat Control Panel (`/training-jobs` → `/evaluation` → `/models`, urutan: buat training job dengan dataset train → tunggu `COMPLETED` → buat evaluation dengan dataset eval → tunggu `COMPLETED` → `VALIDATE` lalu `PROMOTE` model version). Promosi **selalu manual** by design ([[07_Model_Registry_and_Deployment]] §3-4) — model baru tidak pernah otomatis jadi produksi, dan `app.pipeline.orchestrator` baru mulai memanggil `/v1/classify` setelah `PROMOTE` yang eksplisit. Lihat [[05_Training_Jobs]].

---

## 5. Pairing WAHA WhatsApp Session

WAHA dashboard sekarang loopback-only (§1) — akses dari mesin lokalmu lewat SSH tunnel:

```bash
ssh -L 3000:127.0.0.1:3000 user@<host>
```

lalu buka `http://localhost:3000` di browser lokal.

1. Login pakai `WAHA_DASHBOARD_USERNAME`/`WAHA_DASHBOARD_PASSWORD`.
2. Start session baru, scan QR pakai WhatsApp yang jadi nomor bot.
3. Session tersimpan di named volume `waha_sessions` — restart container (`docker compose restart waha`) tidak akan minta scan ulang.
4. Verifikasi webhook: kirim pesan test dari WhatsApp lain ke nomor bot, cek log `api-gateway`:
   ```bash
   docker compose logs -f api-gateway | grep webhook
   ```
5. Verifikasi session-status webhook: `docker compose restart waha`, amati event `session.status` masuk ke gateway saat disconnect/reconnect.

---

## 6. Update / Redeploy

```bash
git pull
docker compose up -d --build
docker image prune -f   # buang image lama yang menganggur
```

`up -d --build` hanya rebuild image yang berubah (`api-gateway`, `celery-worker` dari `./backend`; `ml-service` dari `./ml-service`; `frontend-dashboard` dari `./frontend`) — service lain (image dari registry: `waha`, `postgres`, `qdrant`, `redis`) tidak kena rebuild.

Ganti `NEXT_PUBLIC_API_URL`, `CORS_ALLOW_ORIGINS`, atau `LLM_*`/`OPENAI_API_KEY`? `NEXT_PUBLIC_API_URL` wajib `--build frontend-dashboard` (build arg — §2); var lain cukup recreate (`docker compose up -d <service>`), sudah otomatis terjadi lewat `up -d` di atas.

---

## 7. Backup Data

```bash
./scripts/backup.sh
```

Postgres dump (`pg_dump`) + Qdrant snapshot ke `backups/<timestamp>/` (gitignored). Skrip tidak menjadwalkan dirinya sendiri — pasang di cron/systemd-timer:

```cron
0 3 * * * cd /path/to/software-dev-2026 && ./scripts/backup.sh >> /var/log/jawara-backup.log 2>&1
```

| Volume | Isi | Di-cover `backup.sh`? |
|---|---|---|
| `postgres_data` | message logs, knowledge base, dataset, model registry, audit log, dll — semua relational state | Ya |
| `qdrant_data` | vector embeddings fact knowledge base | Ya |
| `waha_sessions` | WhatsApp session auth (QR pairing) | Tidak — backup manual: `docker run --rm -v waha_sessions:/data -v $(pwd):/backup alpine tar czf /backup/waha_sessions.tar.gz /data` |
| `ml_model_artifacts` | artefak classifier terlatih (`.joblib`) | Tidak — regenerable lewat training job ulang (§4b); backup opsional kalau training butuh waktu lama untuk diulang |

Restore: lihat komentar di kepala `scripts/backup.sh`.

---

## 8. Security Notes

- **Tidak ada port dari compose ini yang publik secara default** (§1) — `postgres`, `redis`, `qdrant`, `waha`, `api-gateway`, `ml-service`, `frontend-dashboard` semua `127.0.0.1`. Satu-satunya hal yang boleh publik adalah reverse proxy-mu sendiri (di luar compose ini), yang meneruskan ke `frontend-dashboard`/`api-gateway` lewat Docker network internal — bukan port host.
- Redis di stack ini **tidak punya password/auth apa pun di kodenya** — binding loopback (§1) adalah satu-satunya proteksi. Jangan pernah publish port Redis ke `0.0.0.0` di produksi.
- `WAHA_API_KEY` adalah satu-satunya auth layer webhook (`X-Api-Key`) — rotate berkala, jangan reuse across environment.
- `ML_SERVICE_API_KEY` adalah header `X-Internal-Api-Key` antara gateway dan `ml-service` — service-to-service, tapi tetap rotate dari default dev.
- Control Panel menuntut sesi operator (email + password). Akun pertama dibuat otomatis dari `OPERATOR_EMAIL`/`OPERATOR_NAME`/`OPERATOR_PASSWORD` di `.env` (§4b) — tanpa itu tidak ada yang bisa masuk, dan itu memang perilaku yang benar, bukan akun default. Ganti `OPERATOR_PASSWORD` setelah login pertama; tidak ada rotasi otomatis. Umur sesi diatur `AUTH_SESSION_TTL_MINUTES`. **RBAC belum ada**: setiap akun melihat seluruh panel ([[Implement_Operator_Auth]]).
- Rate-limiting webhook sudah live: **20 request / 60 detik per (session, chat_id)**, sliding window di Redis, balas `429` + `Retry-After`. Catatan operasional: limiter ini **fail open** — kalau Redis tidak reachable, request tetap diteruskan dan kegagalannya di-log. Rate limit reverse-proxy tetap layak dipasang sebagai lapisan kedua, khususnya untuk trafik yang belum lolos auth `X-Api-Key`.
- `USER_HASH_SALT` adalah satu-satunya hal yang memisahkan `user_hash` dari nomor WhatsApp asli. Bocornya salt + daftar nomor = hash bisa dibalik brute force (ruang nomor telepon kecil). Simpan setara password database, jangan commit, jangan reuse antar environment.
- `message_logs.extracted_text` menyimpan isi pesan pengguna dalam plaintext dan **belum punya retention policy** (isu terbuka, lihat [[01_Threat_Model_and_Data_Protection]] §5.1). `LOG_MESSAGE_CONTENT=false` mematikan penulisan ini sepenuhnya kalau retention belum diputuskan.
- Artefak classifier (`ml_model_artifacts`) diverifikasi checksum sebelum dimuat — `ml-service` tidak punya database sendiri untuk tahu model mana yang sah, jadi gateway (pemilik model registry) mengirim `expected_sha256` di setiap panggilan `/v1/classify`/`/v1/evaluate`; checksum tidak cocok = ditolak, bukan dimuat diam-diam ([[07_Model_Registry_and_Deployment]] §7).
- Persyaratan keamanan lintas komponen (auth, RBAC, validasi upload, service-to-service auth, secret management) ada di [[06_Platform_Security_Requirements]].

---

## 9. Stop / Teardown

```bash
docker compose down       # stop + remove containers, volumes tetap ada
docker compose down -v    # DESTRUCTIVE: hapus juga postgres_data/qdrant_data/waha_sessions/ml_model_artifacts
```

---

**Related:** [[03_Tech_Stack]] · [[01_System_Architecture]] · [[01_Dev_Environtment]] · [[05_Training_Jobs]] · [[07_Model_Registry_and_Deployment]] · [[TASKS]]
