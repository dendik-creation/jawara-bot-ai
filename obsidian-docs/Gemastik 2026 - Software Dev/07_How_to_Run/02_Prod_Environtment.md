# Production Environment (Full Docker Compose Deployment)

Panduan ini untuk deploy penuh ke server produksi. Semua 9 service (`waha`, `api-gateway`, `celery-worker`, `celery-beat`, `ml-service`, `postgres`, `qdrant`, `redis`, `frontend-dashboard`) dijalankan sebagai container, diatur (orchestrated) lewat satu file `docker-compose.yml` di root repo.

> Compose ini **tidak menyediakan reverse proxy atau TLS termination sendiri** (reverse proxy adalah server perantara yang meneruskan trafik publik ke aplikasi, TLS termination artinya tempat sertifikat HTTPS diproses). Setiap service, kecuali webhook milik WAHA (port `3000`, hanya untuk pairing/scan QR, lihat bagian 5), sengaja diikat (bind) ke `127.0.0.1`, bukan `0.0.0.0` (lihat bagian 1). Kamu wajib membawa reverse proxy sendiri (contoh: Nginx Proxy Manager, Caddy, Traefik) dan menghubungkannya lewat Docker network, bukan lewat port host yang dipublish keluar.

---

## 1. Yang Perlu Disiapkan (Prerequisites)

- Server atau VM dengan Docker Engine dan Docker Compose plugin sudah terinstall.
- **Tidak ada satu pun port dari compose ini yang perlu dibuka di firewall.** Setiap baris `ports:` di `docker-compose.yml` sekarang diikat secara eksplisit ke `127.0.0.1:<port>:<container_port>`, yaitu `waha` (3000), `api-gateway` (8000), `ml-service` (9000), `postgres` (5432), `qdrant` (6333), `redis` (6379), `frontend-dashboard` (3001, atau sesuai nilai `FRONTEND_PORT`). Semua port ini hanya bisa dijangkau dari `localhost` di server itu sendiri, misalnya untuk keperluan debugging atau `docker exec`. Port-port ini **tidak akan pernah** bisa diakses dari internet, apa pun status firewall-nya. Perlu diketahui, Redis di stack ini **sama sekali tidak punya mekanisme auth** di dalam kodenya. Jadi pembatasan ke loopback (`127.0.0.1`) ini adalah satu-satunya penghalang antara Redis dan internet terbuka, kalau sampai portnya ter-publish keluar.
- Reverse proxy (baik yang sudah berjalan, atau yang baru mau kamu buat) plus sertifikat TLS. Kalau reverse proxy-nya berupa container lain (misalnya Nginx Proxy Manager) yang jalan di Docker network sendiri, gabungkan (join) `frontend-dashboard`/`api-gateway` ke network itu, lalu arahkan proxy langsung ke `<container_name>:<container_port>` (contoh: `jawara-dashboard:3000`, `jawara-gateway:8000`) lewat DNS internal Docker. **Jangan** pakai port host yang dipublish. Cara menambahkan network kedua ke sebuah service di `docker-compose.yml`:
  ```yaml
  services:
    frontend-dashboard:
      networks:
        - jawara-net
        - proxy-network   # ganti dengan nama network reverse proxy milikmu

  networks:
    proxy-network:
      external: true
  ```

---

## 2. Clone Repo dan Atur Konfigurasi

```bash
git clone <repo-url>
cd software-dev-2026
cp .env.example .env
```

Isi `.env` dengan **kredensial produksi yang asli**, bukan placeholder. Setiap nilai `changeme` yang ada di `.env.example` wajib diganti sebelum deploy.

| Var | Catatan |
|---|---|
| `WAHA_DASHBOARD_USERNAME` / `WAHA_DASHBOARD_PASSWORD` | login untuk dashboard WAHA. Pakai password yang kuat, karena dashboard hanya bisa diakses dari `localhost` (lihat bagian 1), aksesnya lewat SSH tunnel |
| `WAHA_API_KEY` | dipakai gateway untuk verifikasi header `X-Api-Key`. Generate string random yang panjang |
| `POSTGRES_DB` / `POSTGRES_USER` / `POSTGRES_PASSWORD` | kredensial database produksi |
| `ML_SERVICE_API_KEY` | dipakai untuk header `X-Internal-Api-Key` antara gateway dan `ml-service`. Ini komunikasi antar service saja, tapi tetap harus generate random, jangan biarkan `changeme` |
| `NEXT_PUBLIC_API_URL` | domain publik API gateway (contoh `https://api.jawara.example.id`), bukan `localhost`. Ini **build arg**, bukan environment variable runtime biasa. Kalau nilainya diganti, kamu harus jalankan `docker compose up -d --build frontend-dashboard`, restart saja tidak cukup |
| `CORS_ALLOW_ORIGINS` | domain publik frontend (contoh `https://app.jawara.example.id`). Kalau origin-nya tidak cocok, browser akan diam-diam memblokir responsnya |
| `USER_HASH_SALT` | salt SHA-256 untuk membuat `user_hash`. Generate random yang panjang, **jangan** pakai `changeme`. Perhatian: mengganti salt setelah produksi berjalan akan membuat semua `user_subscriptions` lama (dan `message_logs`-nya, karena foreign key cascade) jadi tidak terpakai lagi |
| `OPERATOR_EMAIL` / `OPERATOR_NAME` / `OPERATOR_PASSWORD` | akun operator pertama untuk Control Panel. Dibaca oleh `app.scripts.create_operator` saat bootstrap (lihat bagian 4b), tidak dipakai langsung saat runtime oleh `api-gateway` |
| `LLM_PROVIDER` | `template` (default, tanpa perlu API key) atau `anthropic` (butuh `ANTHROPIC_API_KEY`) atau `openai_compatible` (butuh `LLM_BASE_URL` sampai `.../v1`, plus `LLM_API_KEY` dan `LLM_MODEL`. Bisa dipakai untuk endpoint apa pun yang mengikuti format Chat Completions: OpenAI, OpenRouter, Groq, atau vLLM/Ollama self-hosted) |
| `EMBEDDING_PROVIDER` | `hash` (default, mencocokkan secara leksikal/kata literal, bukan makna) atau `openai` (butuh `OPENAI_API_KEY`, ini API key terpisah dari `LLM_API_KEY` di atas meski sama-sama bisa mengarah ke OpenAI) |
| `RATE_LIMIT_MAX_REQUESTS` / `RATE_LIMIT_WINDOW_SECONDS` | default-nya `20` request per `60` detik, dihitung per kombinasi (session, chat) |
| `QDRANT_COLLECTION` / `EMBEDDING_DIM` | `fact_knowledge_base` dengan dimensi `1536` (untuk `text-embedding-3-small`), atau `768` kalau kamu pindah ke IndoBERT. Mengganti dimensi berarti kamu harus membuat ulang collection dan meng-embed ulang semua data |
| `WAHA_PORT` / `API_GATEWAY_PORT` / `ML_SERVICE_PORT` / `QDRANT_PORT` / `FRONTEND_PORT` / `POSTGRES_PORT` / `REDIS_PORT` | pemetaan port host (loopback-only, lihat bagian 1). Ganti nilainya kalau bentrok dengan service lain di server yang sama, tidak perlu edit `docker-compose.yml` |

Jangan commit file `.env` ke git, filenya sudah masuk `.gitignore`.

---

## 3. Build dan Jalankan

```bash
docker compose up -d --build
```

Compose akan menyalakan service secara berurutan mengikuti aturan `depends_on` dan `healthcheck`:

```
postgres, redis, qdrant, waha  →  ml-service  →  api-gateway, celery-worker  →  celery-beat, frontend-dashboard
```

`ml-service` dicek lewat **readiness** (`GET /v1/ready`, artinya modelnya sudah termuat), bukan sekadar liveness (container hidup atau tidak). Container yang statusnya "up" belum tentu "ready". Jangan cuma mengandalkan status container saja.

---

## 4. Verifikasi

```bash
docker compose ps
```

Semua service harus berstatus `healthy` (kecuali `celery-beat`, karena ini scheduler tanpa endpoint jadi memang tidak punya healthcheck, cek lewat lognya saja). Ingat, **harus persis satu** replika `celery-beat` yang jalan. Kalau ada dua scheduler yang jalan bersamaan, setiap tick (termasuk crawl cek fakta) akan digandakan.

Kalau ada yang statusnya `unhealthy` atau terus restart, cek lognya:

```bash
docker compose logs -f api-gateway
docker compose logs -f celery-worker
docker compose logs -f celery-beat
docker compose logs -f ml-service
docker compose logs -f waha
```

Cek endpoint kesehatan gateway (dijalankan dari server itu sendiri, karena portnya loopback-only, lihat bagian 1):

```bash
curl http://127.0.0.1:8000/health
# {"status":"ok","dependencies":{"database":true,"redis":true}}

curl -H "X-Internal-Api-Key: <ML_SERVICE_API_KEY>" http://127.0.0.1:9000/v1/ready
```

---

## 4b. Bootstrap Data Layer

Langkah ini dilakukan sekali untuk setiap deployment baru, dan lagi setiap kali kamu menambahkan file migrasi baru. Semua perintah di bawah aman diulang (idempotent), jadi tidak masalah kalau dijalankan lagi di setiap redeploy:

```bash
docker exec jawara-gateway python -m app.db.migrate
docker exec jawara-gateway python -m app.vector.qdrant_setup
docker exec jawara-gateway python -m app.scripts.seed_facts
docker exec jawara-gateway python -m app.scripts.ingest_knowledge

# Akun operator pertama. Tanpa ini, tidak ada satu pun yang bisa login.
# Nilainya diambil dari OPERATOR_EMAIL/OPERATOR_NAME/OPERATOR_PASSWORD di .env, tanpa argumen tambahan.
# Aman diulang di setiap redeploy: akun yang sudah ada akan dibiarkan apa adanya.
docker exec jawara-gateway python -m app.scripts.create_operator
```

`migrate` menerapkan setiap file di `app/db/migrations/*.sql` secara berurutan, lalu mencatatnya di tabel `schema_migrations`. `qdrant_setup` membuat collection `fact_knowledge_base` kalau belum ada, lalu mencetak konfigurasi live-nya. Kalau collection-nya sudah ada, ia **tidak** dibuat ulang, hanya payload index-nya saja yang di-assert ulang. Ini supaya embedding yang sudah ada tidak ikut terhapus.

Verifikasi:

```bash
docker exec jawara-postgres psql -U <POSTGRES_USER> -d <POSTGRES_DB> -c "\dt"
curl -H "X-Internal-Api-Key: <ML_SERVICE_API_KEY>" http://127.0.0.1:9000/v1/ready
```

### (Opsional) Threat Classifier: Seed Data, Training, Evaluasi, Promosi

Model dasarnya TF-IDF + LogisticRegression. Tanpa model berstatus `PRODUCTION`, pipeline tetap berjalan normal lewat Detection Rules saja. Bagian ini bukan syarat wajib supaya bot berfungsi, tujuannya murni untuk mengaktifkan sinyal ML tambahan.

```bash
docker exec jawara-gateway python -m app.scripts.seed_dataset_samples
```

Perintah ini membuat dua dataset VALIDATED yang sifatnya sintetis: `core-detection-train` (240 sample) dan `core-detection-eval` (60 sample). Cukup untuk membuktikan mekanisme training, evaluasi, dan promosi berjalan, bukan untuk mengukur akurasi setara produksi. Kalau kamu punya data asli atau ingin data yang lebih besar, tambahkan sample lewat Control Panel di menu `/datasets` sebelum membuat training job.

Training job, evaluasi, dan promosi dijalankan lewat Control Panel, urutannya: `/training-jobs` lalu `/evaluation` lalu `/models`. Detailnya:

1. Buat training job dengan dataset train, tunggu sampai `COMPLETED`.
2. Buat evaluation dengan dataset eval, tunggu sampai `COMPLETED`.
3. Klik `VALIDATE`, lalu `PROMOTE` pada model version yang muncul.

Promosi **selalu dilakukan manual** by design (lihat [[07_Model_Registry_and_Deployment]] bagian 3-4). Model baru tidak akan pernah otomatis jadi model produksi. `app.pipeline.orchestrator` baru mulai memanggil `/v1/classify` setelah kamu melakukan `PROMOTE` secara eksplisit. Detail lebih lanjut di [[05_Training_Jobs]].

---

## 5. Pairing Session WhatsApp di WAHA

Dashboard WAHA sekarang hanya bisa diakses lewat `localhost` (lihat bagian 1). Untuk mengaksesnya dari komputer lokalmu, pakai SSH tunnel:

```bash
ssh -L 3000:127.0.0.1:3000 user@<host>
```

Setelah itu, buka `http://localhost:3000` di browser komputer lokalmu.

1. Login pakai `WAHA_DASHBOARD_USERNAME`/`WAHA_DASHBOARD_PASSWORD`.
2. Start session baru, lalu scan QR code memakai WhatsApp yang akan dijadikan nomor bot.
3. Session akan tersimpan di named volume `waha_sessions`. Jadi kalau container di-restart (`docker compose restart waha`), kamu tidak perlu scan ulang.
4. Verifikasi webhook: kirim pesan test dari nomor WhatsApp lain ke nomor bot, lalu cek log `api-gateway`:
   ```bash
   docker compose logs -f api-gateway | grep webhook
   ```
5. Verifikasi webhook status session: jalankan `docker compose restart waha`, lalu amati event `session.status` masuk ke gateway saat session disconnect dan reconnect.

---

## 6. Update / Redeploy

```bash
git pull
docker compose up -d --build
docker image prune -f   # buang image lama yang sudah tidak dipakai
```

Perintah `up -d --build` hanya akan rebuild image yang memang berubah: `api-gateway`, `celery-worker`, `celery-beat` (dari folder `./backend`), `ml-service` (dari `./ml-service`), dan `frontend-dashboard` (dari `./frontend`). Service lain yang image-nya diambil dari registry (`waha`, `postgres`, `qdrant`, `redis`) tidak akan ikut di-rebuild.

Kalau kamu mengganti `NEXT_PUBLIC_API_URL`, `CORS_ALLOW_ORIGINS`, atau `LLM_*`/`OPENAI_API_KEY`, perlu diketahui: khusus `NEXT_PUBLIC_API_URL` wajib pakai `--build frontend-dashboard` (karena ini build arg, lihat bagian 2). Untuk variabel lainnya, cukup recreate service-nya saja (`docker compose up -d <service>`), yang mana sudah otomatis terjadi lewat perintah `up -d` di atas.

---

## 7. Backup Data

```bash
./scripts/backup.sh
```

Script ini membuat dump Postgres (pakai `pg_dump`) plus snapshot Qdrant, disimpan ke folder `backups/<timestamp>/` (folder ini sudah masuk `.gitignore`, tidak ikut kecommit). Script ini tidak menjadwalkan dirinya sendiri secara otomatis, jadi kamu perlu memasangnya di cron atau systemd-timer:

```cron
0 3 * * * cd /path/to/software-dev-2026 && ./scripts/backup.sh >> /var/log/jawara-backup.log 2>&1
```

| Volume | Isi | Dicover `backup.sh`? |
|---|---|---|
| `postgres_data` | message log, knowledge base, dataset, model registry, audit log, dan semua state relational lain | Ya |
| `qdrant_data` | vector embedding untuk fact knowledge base | Ya |
| `waha_sessions` | data auth session WhatsApp (hasil scan QR) | Tidak, backup manual: `docker run --rm -v waha_sessions:/data -v $(pwd):/backup alpine tar czf /backup/waha_sessions.tar.gz /data` |
| `ml_model_artifacts` | file model classifier hasil training (`.joblib`) | Tidak, bisa dibuat ulang lewat training job (lihat bagian 4b). Backup ini opsional saja, kalau proses training-nya butuh waktu lama untuk diulang |

Untuk cara restore, lihat komentar di bagian atas file `scripts/backup.sh`.

---

## 8. Catatan Keamanan

- **Tidak ada port dari compose ini yang publik secara default** (lihat bagian 1). `postgres`, `redis`, `qdrant`, `waha`, `api-gateway`, `ml-service`, `frontend-dashboard` semuanya diikat ke `127.0.0.1`. Satu-satunya yang boleh publik adalah reverse proxy milikmu sendiri (di luar compose ini), yang meneruskan trafik ke `frontend-dashboard`/`api-gateway` lewat Docker network internal, bukan lewat port host.
- Redis di stack ini **tidak punya password atau mekanisme auth apa pun** di dalam kodenya. Pembatasan loopback (bagian 1) adalah satu-satunya proteksi yang ada. Jangan pernah mempublish port Redis ke `0.0.0.0` di produksi.
- `WAHA_API_KEY` adalah satu-satunya lapisan auth untuk webhook (lewat header `X-Api-Key`). Rotasi (ganti) secara berkala, dan jangan pakai ulang antar environment yang berbeda.
- `ML_SERVICE_API_KEY` adalah header `X-Internal-Api-Key` yang dipakai antara gateway dan `ml-service`. Ini komunikasi antar service saja, tapi tetap harus dirotasi dari nilai default saat development.
- Control Panel mengharuskan sesi operator (email plus password). Akun pertama dibuat otomatis dari `OPERATOR_EMAIL`/`OPERATOR_NAME`/`OPERATOR_PASSWORD` di `.env` (lihat bagian 4b). Tanpa itu, tidak ada yang bisa login, dan ini memang perilaku yang benar, bukan akun default yang berbahaya. Ganti `OPERATOR_PASSWORD` setelah login pertama kali, karena tidak ada rotasi otomatis. Umur sesi diatur lewat `AUTH_SESSION_TTL_MINUTES`. **RBAC (pembagian hak akses per role) belum ada**, jadi setiap akun bisa melihat seluruh panel (lihat [[Implement_Operator_Auth]]).
- Rate-limiting webhook sudah aktif: **20 request per 60 detik** per kombinasi (session, chat_id), memakai sliding window di Redis, membalas `429` disertai header `Retry-After`. Catatan operasional: limiter ini bersifat **fail open**, artinya kalau Redis tidak bisa dijangkau, request tetap diteruskan dan kegagalannya cuma dicatat di log. Sebaiknya tetap pasang rate limit di level reverse proxy juga sebagai lapisan kedua, terutama untuk trafik yang belum lolos auth `X-Api-Key`.
- `USER_HASH_SALT` adalah satu-satunya hal yang memisahkan `user_hash` dari nomor WhatsApp asli penggunanya. Kalau salt ini bocor bersama daftar nomor telepon, hash-nya bisa dibalik lewat brute force (karena ruang kemungkinan nomor telepon relatif kecil). Simpan setara dengan password database, jangan commit ke git, jangan pakai ulang antar environment.
- Kolom `message_logs.extracted_text` menyimpan isi pesan pengguna dalam bentuk plaintext (tidak dienkripsi) dan **belum punya kebijakan retensi** (isu ini masih terbuka, lihat [[01_Threat_Model_and_Data_Protection]] bagian 5.1). Kalau kebijakan retensinya belum diputuskan, kamu bisa set `LOG_MESSAGE_CONTENT=false` untuk mematikan penulisan kolom ini sepenuhnya.
- File model classifier (`ml_model_artifacts`) diverifikasi checksum-nya sebelum dimuat. `ml-service` tidak punya database sendiri untuk tahu model mana yang sah, jadi gateway (yang memegang model registry) mengirim `expected_sha256` di setiap panggilan `/v1/classify`/`/v1/evaluate`. Kalau checksum-nya tidak cocok, model akan ditolak, bukan diam-diam tetap dimuat (lihat [[07_Model_Registry_and_Deployment]] bagian 7).
- Persyaratan keamanan lintas komponen (auth, RBAC, validasi upload, auth antar service, pengelolaan secret) ada di [[06_Platform_Security_Requirements]].

---

## 9. Stop / Teardown (Mematikan Semua Service)

```bash
docker compose down       # berhenti + hapus container, volume tetap ada
docker compose down -v    # DESTRUKTIF: ikut menghapus postgres_data/qdrant_data/waha_sessions/ml_model_artifacts
```

Peringatan: perintah kedua akan menghapus semua data secara permanen, termasuk database produksi dan session WhatsApp. Jangan jalankan kecuali kamu benar-benar yakin.

---

**Related:** [[03_Tech_Stack]] · [[01_System_Architecture]] · [[01_Dev_Environtment]] · [[05_Training_Jobs]] · [[07_Model_Registry_and_Deployment]] · [[TASKS]]
