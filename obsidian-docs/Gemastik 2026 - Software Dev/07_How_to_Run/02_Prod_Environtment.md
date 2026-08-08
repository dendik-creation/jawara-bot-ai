# Production Environment — Full Docker Compose Deployment

Panduan deploy penuh: semua 7 service (`waha`, `api-gateway`, `celery-worker`, `postgres`, `qdrant`, `redis`, `frontend-dashboard`) jalan sebagai container, orchestrated oleh `docker-compose.yml` di root repo.

---

## 1. Prerequisites

- Server/VM dengan Docker Engine + Docker Compose plugin terinstall.
- Port terbuka sesuai kebutuhan akses (default, override lewat `.env` — lihat §2): `3000` (WAHA dashboard, `WAHA_PORT`), `8000` (API gateway, `API_GATEWAY_PORT`), `3001` (frontend dashboard, `FRONTEND_PORT`). `postgres`/`redis`/`qdrant` juga di-publish (`POSTGRES_PORT`/`REDIS_PORT`/`QDRANT_PORT`, untuk kebutuhan dev hybrid) — di produksi **wajib** block port ini di firewall/security group, jangan biarkan reachable dari internet (lihat §8).
- Reverse proxy (Nginx/Caddy/Traefik) + TLS certificate — compose ini tidak menyediakan HTTPS termination sendiri.

---

## 2. Clone & Configure

```bash
git clone <repo-url>
cd software-dev-2026
cp .env.example .env
```

Isi `.env` dengan **credential produksi asli**, bukan placeholder:

| Var | Catatan |
|---|---|
| `WAHA_DASHBOARD_USERNAME` / `WAHA_DASHBOARD_PASSWORD` | login dashboard WAHA — pakai password kuat, bukan `changeme` |
| `WAHA_API_KEY` | dipakai gateway untuk verifikasi header `X-Api-Key` — generate random string panjang |
| `POSTGRES_DB` / `POSTGRES_USER` / `POSTGRES_PASSWORD` | credential database produksi |
| `NEXT_PUBLIC_API_URL` | domain publik API gateway (misal `https://api.jawara.example.id`), bukan `localhost` |
| `USER_HASH_SALT` | salt SHA-256 untuk `user_hash` — generate random panjang, **jangan** pakai `changeme`. Mengganti salt setelah produksi jalan mematikan semua `user_subscriptions` lama beserta `message_logs`-nya (FK cascade) |
| `RATE_LIMIT_MAX_REQUESTS` / `RATE_LIMIT_WINDOW_SECONDS` | default `20` / `60` detik per (session, chat) |
| `QDRANT_COLLECTION` / `EMBEDDING_DIM` | `fact_knowledge_base` / `1536` (`text-embedding-3-small`); `768` kalau pindah ke IndoBERT — ganti dimensi berarti buat ulang collection dan embed ulang |
| `WAHA_PORT` / `API_GATEWAY_PORT` / `QDRANT_PORT` / `FRONTEND_PORT` / `POSTGRES_PORT` / `REDIS_PORT` | host port mapping — ganti kalau bentrok dengan service lain di server yang sama, tidak perlu edit `docker-compose.yml` |

Jangan commit `.env` — sudah di `.gitignore`.

---

## 3. Build & Start

```bash
docker compose up -d --build
```

Compose akan start berurutan sesuai `depends_on` + `healthcheck`:

```
postgres, redis, qdrant, waha  →  api-gateway, celery-worker  →  frontend-dashboard
```

---

## 4. Verifikasi

```bash
docker compose ps
```

Semua service harus `healthy`. Cek log kalau ada yang `unhealthy`/restart loop:

```bash
docker compose logs -f api-gateway
docker compose logs -f celery-worker
docker compose logs -f waha
```

Health endpoint gateway:

```bash
curl http://localhost:8000/health
# {"status":"ok","dependencies":{"database":true,"redis":true}}
```

---

## 4b. Bootstrap Data Layer

Sekali per deployment baru (dan setelah menambah file migrasi). Keduanya idempotent — aman diulang di setiap redeploy:

```bash
docker compose exec api-gateway python -m app.db.migrate
docker compose exec api-gateway python -m app.vector.qdrant_setup
```

`migrate` apply `app/db/migrations/*.sql` berurutan dan mencatatnya di tabel `schema_migrations`; `qdrant_setup` membuat collection `fact_knowledge_base` lalu mencetak config live-nya. Collection yang sudah ada **tidak** dibuat ulang — hanya payload index yang di-assert ulang, supaya embedding tidak terhapus.

Verifikasi:

```bash
docker compose exec postgres psql -U <POSTGRES_USER> -d <POSTGRES_DB> -c "\dt"
curl http://localhost:6333/collections/fact_knowledge_base
```

---

## 5. Pairing WAHA WhatsApp Session

1. Buka `http://<host>:3000` (atau lewat reverse proxy), login pakai `WAHA_DASHBOARD_USERNAME`/`WAHA_DASHBOARD_PASSWORD`.
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

`up -d --build` hanya rebuild image yang berubah (`api-gateway`, `celery-worker` dari `./backend`; `frontend-dashboard` dari `./frontend`) — service lain (image dari registry) tidak kena rebuild.

---

## 7. Backup Data

| Volume | Isi | Cara backup |
|---|---|---|
| `postgres_data` | relational audit log, schema | `docker compose exec postgres pg_dump -U <POSTGRES_USER> <POSTGRES_DB> > backup.sql` |
| `qdrant_data` | vector embeddings | Qdrant snapshot API: `curl -X POST http://localhost:6333/collections/<name>/snapshots` |
| `waha_sessions` | WhatsApp session auth | `docker run --rm -v waha_sessions:/data -v $(pwd):/backup alpine tar czf /backup/waha_sessions.tar.gz /data` |

---

## 8. Security Notes

- `postgres` (`POSTGRES_PORT`), `redis` (`REDIS_PORT`), `qdrant` (`QDRANT_PORT`) di-publish ke host (dibutuhkan untuk dev hybrid) — di server produksi, block port ini di firewall/security group supaya hanya reachable dari `localhost`/VPN, jangan biarkan terbuka ke internet publik.
- Taruh `api-gateway` (8000) dan `frontend-dashboard` (3001) di belakang reverse proxy dengan TLS, jangan expose port raw ke publik.
- `WAHA_API_KEY` adalah satu-satunya auth layer webhook (`X-Api-Key`) — rotate berkala, jangan reuse across environment.
- Rate-limiting webhook sudah live: **20 request / 60 detik per (session, chat_id)**, sliding window di Redis, balas `429` + `Retry-After`. Catatan operasional: limiter ini **fail open** — kalau Redis tidak reachable, request tetap diteruskan dan kegagalannya di-log. Rate limit reverse-proxy tetap layak dipasang sebagai lapisan kedua, khususnya untuk trafik yang belum lolos auth `X-Api-Key`.
- `USER_HASH_SALT` adalah satu-satunya hal yang memisahkan `user_hash` dari nomor WhatsApp asli. Bocornya salt + daftar nomor = hash bisa dibalik brute force (ruang nomor telepon kecil). Simpan setara password database, jangan commit, jangan reuse antar environment.
- `message_logs.extracted_text` menyimpan isi pesan pengguna dalam plaintext dan **belum punya retention policy** (temuan terbuka di [[01_Documentation_Audit_Report]]). Putuskan sebelum tabel ini mulai diisi oleh [[Create Audit Logging]].

---

## 9. Stop / Teardown

```bash
docker compose down       # stop + remove containers, volumes tetap ada
docker compose down -v    # DESTRUCTIVE: hapus juga postgres_data/qdrant_data/waha_sessions
```

---

**Related:** [[03_Tech_Stack]] · [[01_System_Architecture]] · [[01_Dev_Environtment]] · [[TASKS]]
