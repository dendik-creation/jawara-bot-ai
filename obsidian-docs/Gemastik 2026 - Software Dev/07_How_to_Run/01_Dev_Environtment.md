# Development Environment (Hybrid Run: Compose Infra + Local App)

Panduan ini untuk pemula yang ingin menjalankan project sehari-hari untuk development. Caranya pakai mode **hybrid**:

- **Infra berat** (WAHA, PostgreSQL, Redis, Qdrant) jalan di dalam Docker Compose. Kamu tidak perlu install ini satu-satu di komputer, cukup lewat container.
- **Backend (FastAPI)** dan **frontend (Next.js)** dijalankan langsung lewat CLI (command line) di komputer lokal, bukan lewat container. Tujuannya supaya ada **hot-reload** (perubahan kode langsung terlihat tanpa build ulang) dan lebih gampang untuk debugging.

> `ml-service` sudah ada di repo dan di compose (lihat [[04_ML_Service]]). Service ini dijalankan lewat Docker seperti infra lain, bukan lewat CLI lokal. Alasannya, model AI-nya dimuat sekali saat startup, jadi hot-reload tidak ada gunanya di sini.
>
> Catatan penting: container yang statusnya "up" (menyala) belum tentu "ready" (siap dipakai). Untuk cek kesiapan ml-service, pakai endpoint `GET /v1/ready`, bukan `GET /v1/health`.

---

## 1. Yang Perlu Disiapkan (Prerequisites)

| Tool | Versi | Catatan |
|---|---|---|
| Docker + Docker Compose | terbaru | untuk menjalankan waha, postgres, redis, qdrant |
| Python | 3.14 | harus sama dengan base image di `backend/Dockerfile` dan `requires-python` di `pyproject.toml` |
| uv | minimal 0.12 | satu-satunya tool untuk mengatur dependency Python di project ini (`pyproject.toml` + `uv.lock`). `uv` juga otomatis mengunduh Python 3.14 kalau belum ada di komputermu |
| Bun | terbaru | package manager untuk frontend (detail lain di `frontend/README.md`) |

---

## 2. Setup File `.env`

File `.env` berisi semua konfigurasi rahasia (password, API key, dll) yang dibutuhkan project. File ini **tidak boleh dicommit ke git**, makanya kamu harus membuatnya sendiri dari template.

Copy `.env.example` menjadi `.env` di folder root repo, lalu isi semua value di dalamnya (`WAHA_DASHBOARD_USERNAME`/`PASSWORD`, `WAHA_API_KEY`, `POSTGRES_*`, `USER_HASH_SALT`).

```bash
cp .env.example .env
```

Langkah "infra-only" di bagian 3 tetap butuh file `.env` ini sudah terisi.

---

## 3. Jalankan Infra Saja Lewat Docker Compose

Jangan jalankan `docker compose up` tanpa argumen apa pun. Kalau begitu, Docker akan ikut membangun dan menyalakan `api-gateway`, `celery-worker`, dan `frontend-dashboard`, padahal untuk mode dev hybrid kita mau tiga service itu dijalankan manual lewat CLI (lihat bagian 4 dan 5). Jadi sebutkan nama service-nya satu per satu:

```bash
docker compose up -d waha postgres redis qdrant ml-service
```

Cek semua service sudah sehat:

```bash
docker compose ps
```

| Service | Host Port (nama var di `.env`, default) | Cara Cek Sehat |
|---|---|---|
| waha | `WAHA_PORT` (3000) | buka http://localhost:3000/ |
| postgres | `POSTGRES_PORT` (5432) | `docker compose exec postgres pg_isready -U <POSTGRES_USER>` |
| redis | `REDIS_PORT` (6379) | `docker compose exec redis redis-cli ping` |
| qdrant | `QDRANT_PORT` (6333) | buka http://localhost:6333/healthz |
| ml-service | `ML_SERVICE_PORT` (9000) | `curl -H "X-Internal-Api-Key: <ML_SERVICE_API_KEY>" http://localhost:9000/v1/ready` |

Semua nomor port di atas diambil dari `.env` (`WAHA_PORT`, `API_GATEWAY_PORT`, `QDRANT_PORT`, `FRONTEND_PORT`, `POSTGRES_PORT`, `REDIS_PORT`), bukan ditulis langsung (hardcode) di file compose. Jadi kalau ada port yang bentrok dengan aplikasi lain di komputermu, cukup ganti value-nya di `.env`, tidak perlu ubah `docker-compose.yml`.

`postgres` dan `redis` sengaja dipublish ke `127.0.0.1:${POSTGRES_PORT}:5432` dan `127.0.0.1:${REDIS_PORT}:6379`. Ini supaya backend dan frontend yang jalan **di luar** jaringan Docker (`jawara-net`), yang memang jadi kasus di mode dev hybrid ini, bisa connect lewat `localhost:<port>`.

`127.0.0.1` (loopback, artinya hanya bisa diakses dari komputer itu sendiri) sengaja dipakai, bukan `0.0.0.0` (yang bisa diakses dari luar). Setting ini persis sama dengan yang dipakai di produksi (lihat [[02_Prod_Environtment]] bagian 1), jadi tidak ada file konfigurasi terpisah untuk "mode aman" versus "mode dev", semuanya satu standar.

Kalau file `.env` lama milikmu belum punya `POSTGRES_PORT` atau `REDIS_PORT`, tambahkan manual. Tanpa dua variabel ini, Docker Compose gagal mempublish port dan backend lokal tidak akan bisa connect (lihat troubleshooting di bagian 6).

---

## 4. Jalankan Backend (FastAPI) Lewat CLI Lokal

```bash
cd backend
uv sync
```

Perintah `uv sync` ini akan:
- Membuat virtual environment (`.venv`) sendiri secara otomatis, kamu tidak perlu jalankan `python -m venv` manual.
- Memasang persis versi package yang tertulis di `uv.lock`, termasuk dependency group `dev`.
- Mengunduh CPython 3.14 otomatis kalau komputermu belum punya.

Semua perintah di panduan ini ditulis dengan awalan `uv run`, jadi bisa langsung jalan tanpa perlu mengaktifkan virtual environment dulu. Kalau mau, kamu juga boleh jalankan `source .venv/Scripts/activate` sekali di awal, setelah itu awalan `uv run` bisa dilepas.

**Kamu tidak perlu export environment variable secara manual.** File `app/core/config.py` sudah otomatis membaca `.env` di folder root repo (pakai path absolut, jadi tidak masalah kamu jalankan perintah dari folder mana pun). File yang dibaca ini sama persis dengan yang dibaca Docker Compose, jadi kredensial antara backend lokal dan container tidak akan pernah beda.

Untuk variabel yang tidak ada di `.env`, backend menurunkannya sendiri dari komponen lain, dengan host `localhost` (karena proses backend lokal berada di luar jaringan `jawara-net`, hostname ala Docker seperti `postgres`/`redis`/`waha` **tidak akan bisa di-resolve**):

| Yang dipakai kode | Diturunkan dari | Hasil di dev hybrid |
|---|---|---|
| `DATABASE_URL` | `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `POSTGRES_PORT` | `postgresql://<user>:<pass>@localhost:5432/<db>` |
| `REDIS_URL`, `CELERY_BROKER_URL` | `REDIS_PORT` | `redis://localhost:6379/0` |
| `CELERY_RESULT_BACKEND` | `REDIS_PORT` | `redis://localhost:6379/1` (database Redis nomor 1, khusus untuk hasil task, terpisah dari antrean/queue) |
| `WAHA_API_URL` | `WAHA_PORT` | `http://localhost:3000` |
| `ML_SERVICE_URL` | `ML_SERVICE_PORT` | `http://localhost:9000` |

Sementara `WAHA_API_KEY`, `ML_SERVICE_API_KEY`, `USER_HASH_SALT`, `QDRANT_COLLECTION` dibaca langsung apa adanya dari `.env`. Ini penting supaya tidak ada kemungkinan salt yang berbeda antara backend lokal dan worker (kalau salt beda, `user_hash` yang dihasilkan juga beda, akibatnya baris di tabel `user_subscriptions` jadi tidak cocok/match).

Kalau kamu sempat `export` environment variable sendiri di terminal, nilai itu akan menang dibanding isi `.env`. Cara ini yang dipakai `docker-compose.yml` untuk menyuntikkan hostname khusus di dalam jaringan Docker (`postgres`, `redis`, `ml-service`). Kalau kamu cuma mau override satu nilai saja tanpa menyalin seluruh isi `.env`, buat file `backend/.env` terpisah, isinya akan dibaca setelah `.env` di root.

```bash
export DATABASE_URL="postgresql://user:pass@localhost:5433/other-db"   # hanya kalau memang beda
```

### Bootstrap Data Layer

Langkah ini sekali saja untuk tiap database/volume baru, dan aman kalau diulang (idempotent, artinya dijalankan berkali-kali hasilnya tetap sama, tidak error atau duplikat):

```bash
uv run python -m app.db.migrate               # terapkan skema PostgreSQL
uv run python -m app.vector.qdrant_setup      # buat collection fact_knowledge_base + payload index
uv run python -m app.scripts.seed_facts       # isi data demo ke fact_sources dan fact_items
uv run python -m app.scripts.ingest_knowledge # ubah fact_items jadi embedding lalu simpan ke Qdrant lewat ML Service

# Akun operator untuk Control Panel. Tanpa langkah ini, tidak ada yang bisa login ke dashboard.
# Nilai email/nama/password diambil dari OPERATOR_EMAIL/OPERATOR_NAME/OPERATOR_PASSWORD di .env,
# jadi perintah ini dijalankan tanpa argumen tambahan.
uv run python -m app.scripts.create_operator
```

Perlu diketahui: **tidak ada halaman pendaftaran mandiri** untuk operator. Control Panel adalah konsol internal, dan siapa pun yang bisa menjalankan perintah di atas memang sudah punya akses ke kredensial database. Perintah ini aman diulang, akun yang sudah ada akan dibiarkan apa adanya (keluar dengan status sukses, bukan error). Kalau mau ganti email/nama sekali pakai, gunakan flag `--email`/`--name` (ini akan override nilai di `.env`). Lupa password? Pakai `--reset-password` dengan email yang sama.

Perintah `qdrant_setup` akan mencetak konfigurasi live-nya di layar. Cocokkan hasilnya dengan tabel di [[02_VectorDB_Specifications]].

Dua perintah terakhir di atas (`seed_facts` dan `ingest_knowledge`) mengisi knowledge base (basis pengetahuan). Kalau ini belum dijalankan, endpoint `POST /v1/rag-query` akan selalu mengembalikan `unverified: true`. Ini bukan error, cuma artinya belum ada data yang bisa dicocokkan. Perintah `ingest_knowledge` juga butuh `ml-service` sudah menyala dan `ML_SERVICE_URL` sudah mengarah ke sana (`http://localhost:9000` untuk dev hybrid).

`ML_SERVICE_URL` dan `ML_SERVICE_API_KEY` sudah dijelaskan di tabel sebelumnya. Untuk `GOOGLE_SAFE_BROWSING_API_KEY` dan `VIRUSTOTAL_API_KEY`, boleh dikosongkan saja di `.env` kalau kamu belum punya. Provider yang tidak dikonfigurasi hanya akan menghasilkan verdict `UNKNOWN`, bukan bikin pipeline gagal. Justru mengisi dengan nilai asal-asalan lebih buruk, karena provider akan dianggap aktif lalu ditolak oleh servernya sendiri.

### (Opsional) Supaya LLM Membalas Asli, Bukan Template

Secara default, `LLM_PROVIDER=template` akan membalas memakai composer deterministik (jawaban yang disusun dari template teks, bukan hasil generate AI). Ini cukup untuk menguji apakah pipeline-nya jalan, tapi tidak cukup untuk menilai kualitas balasan sungguhan. Ada dua alternatif kalau kamu mau LLM asli:

- `LLM_PROVIDER=anthropic` ditambah `ANTHROPIC_API_KEY`, ini yang dipakai di produksi (model Claude Haiku).
- `LLM_PROVIDER=openai_compatible` ditambah `LLM_BASE_URL` (sampai `.../v1`, nanti kode akan menambahkan `/chat/completions` sendiri), `LLM_API_KEY`, dan `LLM_MODEL`. Ini bisa dipakai untuk endpoint apa pun yang mengikuti format Chat Completions: OpenAI asli, OpenRouter, Groq, atau vLLM/Ollama yang kamu hosting sendiri.

Catatan: variabel ini sengaja dipisah dari `OPENAI_API_KEY` yang dijelaskan di bawah. `OPENAI_API_KEY` dipakai untuk `EMBEDDING_PROVIDER=openai`, servis yang berbeda meski kebetulan dari vendor yang sama.

Kalau kamu memilih provider tapi lupa isi API key-nya, sistem akan otomatis jatuh (fallback) ke `template`. Cek ini di field `degraded_reasons` pada `GET /v1/ready`. Ini bukan crash, cuma pemberitahuan.

### (Opsional) Melatih Threat Classifier: Seed Data, Training, Evaluasi, Promosi

Model dasar (baseline) yang dipakai adalah TF-IDF + LogisticRegression (`ml-service/app/models/classifier.py`). Tanpa model berstatus `PRODUCTION`, pipeline tetap berjalan seperti biasa lewat Detection Rules saja. Jadi bagian ini murni untuk menguji alur training dari awal sampai akhir, bukan syarat wajib supaya bot bisa jalan.

```bash
# butuh minimal satu akun operator (bagian 4 di atas), karena created_by/added_by adalah foreign key ke tabel operators
uv run python -m app.scripts.seed_dataset_samples
```

Perintah ini membuat dua dataset berstatus VALIDATED: `core-detection-train` (240 sample, 40 per label) dan `core-detection-eval` (60 sample, 10 per label). Data ini sintetis, dibuat dari template kalimat Bahasa Indonesia per kategori (lihat docstring di scriptnya), bukan data asli. Cukup untuk membuktikan mekanismenya berjalan, bukan untuk mengukur akurasi setara produksi.

Training job, evaluasi, dan promosi model dijalankan lewat Control Panel di menu `/training-jobs`, `/evaluation`, dan `/models`. Urutannya:

1. Buat training job dengan dataset `core-detection-train`, tunggu sampai statusnya `COMPLETED`.
2. Buat evaluation dengan dataset `core-detection-eval`, tunggu sampai statusnya `COMPLETED`.
3. Klik `VALIDATE`, lalu `PROMOTE` pada model version yang muncul di `/models`.

Baru setelah `PROMOTE` ini dijalankan, `app.pipeline.orchestrator` akan mulai memanggil `/v1/classify` sebagai sinyal risiko tambahan (baca lebih lanjut di [[05_Training_Jobs]] dan [[07_Model_Registry_and_Deployment]]).

Jalankan backend dengan hot-reload:

```bash
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Verifikasi sudah jalan:

```bash
curl http://localhost:8000/health
```

Jalankan unit test:

```bash
uv run pytest -q -m "not integration"   # unit test murni, tanpa butuh infra
uv run pytest -q                        # ditambah integration test (butuh postgres/redis/qdrant menyala)
```

Test yang ditandai `integration` akan otomatis **di-skip** kalau service-nya tidak bisa dijangkau atau `DATABASE_URL` tidak valid. Jadi `pytest -q` tetap akan hijau (lulus) di komputer yang belum ada infra-nya, tapi tetap tidak diam-diam melewatkan kegagalan yang sungguhan.

---

## 4b. Jalankan Celery Worker Lewat CLI Lokal

Celery worker adalah proses terpisah yang mengambil dan mengerjakan job dari antrean (queue). Jalankan di terminal terpisah, pakai virtual environment yang sama seperti bagian 4 (environment-nya ikut membaca `.env` di root, jadi tidak ada yang perlu diulang):

```bash
cd backend
uv run celery -A app.worker worker --loglevel=info --pool=solo
```

Flag `--pool=solo` **wajib dipakai kalau kamu di Windows**, karena pool prefork bawaan Celery tidak bisa jalan di Windows. Kalau lewat container (Linux), tetap pakai prefork seperti biasa, flag ini tidak diperlukan.

Untuk verifikasi worker benar-benar memproses job, kirim request percobaan. Isi `body` menentukan jalur mana yang diuji, jadi pesannya harus benar-benar mengandung klaim (bukan sekadar teks kosong seperti `"tes"`):

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

Dua hal berikut wajar berbeda di komputer masing-masing orang, jadi jangan bingung kalau ketemu:

- **`response_dispatched: false` disertai `dispatch_failed:*`.** Ini muncul selama session WAHA bernama `default` belum ada atau belum berstatus `WORKING`. Pipeline-nya tetap berjalan lengkap, cuma balasannya yang tidak terkirim. Cek statusnya dengan `curl -H "X-Api-Key: <WAHA_API_KEY>" http://localhost:3000/api/sessions`.
- **`similarity_score` yang dihasilkan `EMBEDDING_PROVIDER=hash` (default).** Nilai ini sifatnya **leksikal** (mencocokkan kata secara literal), bukan **semantik** (memahami makna). Jadi kalimat yang diparafrase (ditulis ulang dengan kata beda tapi makna sama) tidak akan melewati ambang batas skor 0.80. Contoh kalimat di atas sengaja dibuat mirip dengan `claim_summary` dari data demo yang dibuat `seed_facts`. Untuk bisa mencocokkan parafrase, kamu butuh embedder yang semantik (lihat [[04_ML_Service]]).

Kalau kamu kirim `body` isi `"tes"`, hasilnya **tidak** akan seperti contoh di atas, dan itu bukan kegagalan. Tidak ada satu pun kata kunci atau URL yang cocok, jadi skornya nol dan router mengembalikan `intent: UNKNOWN`, `engine: none`, pipeline berhenti sebelum tahap verifikasi. Ini memang perilaku yang benar untuk pesan yang tidak mengandung klaim apa pun.

Field `degradations` adalah tempat kamu bisa melihat bagian mana yang tidak berjalan sempurna: `ml_unavailable:*`, `url_intel_unavailable`, `knowledge_unverified`, `llm_fallback:*`, `dispatch_failed:*`, `audit_write_failed`. Kalau daftarnya kosong, artinya seluruh jalur berjalan penuh tanpa hambatan.

Log worker (format JSON, satu baris per event) memuat `waha_message_id` yang sama dengan log gateway. Nilai ini berfungsi sebagai correlation ID (penanda yang menghubungkan log-log terkait), dan tetap terbawa sampai ke `request_id` saat memanggil ML Service. Untuk cek antrean secara langsung:

```bash
docker compose exec redis redis-cli LLEN jawara.messages   # kalau hasilnya 0, artinya worker sudah menghabiskan antrean
```

### Rate Limit

Gateway membatasi maksimal **20 request per 60 detik**, dihitung per kombinasi (session, chat_id), memakai sliding window di Redis (jendela waktu yang terus bergeser, bukan reset per menit tetap). Request ke-21 dalam jendela waktu itu akan dibalas `429` beserta header `Retry-After`.

Saat kamu melakukan load test manual, ganti nilai `payload.from`, atau ubah nilai `RATE_LIMIT_MAX_REQUESTS` di `.env`. Jangan ubah kodenya langsung.

Kalau Redis mati, rate limiter akan **fail open** (artinya request tetap diteruskan, kegagalannya cuma dicatat di log, bukan memblokir semua orang). Kalau broker (Redis untuk antrean Celery) mati, webhook tetap membalas `200`, tapi disertai header `X-Queued: 0`. Ini artinya event tersebut hilang, dan itu tercatat sebagai `enqueue failed` di log gateway.

### Troubleshooting: `password authentication failed for user "postgres"` di log worker

```
asyncpg.exceptions.InvalidPasswordError: password authentication failed for user "postgres"
```

User `postgres` memang tidak pernah ditulis di `.env` manapun, jadi error ini menandakan prosesnya **sama sekali tidak membaca konfigurasi apa pun** dan jatuh ke nilai placeholder lama. Penyebab historisnya: dulu `Settings` membaca `.env` secara relatif terhadap folder tempat perintah dijalankan (CWD), padahal `.env` ada di root repo sementara worker dijalankan dari folder `backend/`. Akibatnya file tidak pernah ketemu, dan kalau kamu `export` variabel di terminal lain, itu juga tidak ikut terbawa ke terminal worker.

Ini sudah diperbaiki. Sekarang `.env` di root dibaca lewat path absolut (lihat bagian 4). Kalau errornya masih muncul juga, cek tiga hal ini:

1. Pastikan file `.env` ada di **root repo**, bukan di dalam folder `backend/`.
2. Cek nilai yang benar-benar terbaca oleh kode: `uv run python -c "from app.core.config import get_settings; print(get_settings().database_url)"`. Hasilnya harus menampilkan `POSTGRES_USER` milikmu sendiri, bukan `postgres`.
3. Kalau `DATABASE_URL` sempat kamu `export` ke nilai lama, jalankan `unset DATABASE_URL`. Ingat, environment variable yang sudah di-export selalu menang dibanding isi `.env`.

Dampaknya terbatas pada `degradations: ["audit_write_failed"]`. Pipeline tetap selesai dan tetap membalas pesan, cuma tidak ada baris audit yang tersimpan. Ini memang disengaja, kegagalan menulis audit tidak boleh sampai menelan jawaban yang sudah dihasilkan untuk pengguna.

### Troubleshooting: `ml service call failed` dengan `error: ml_unreachable`

Penyebabnya mirip dengan di atas. Tanpa konfigurasi yang benar, `ML_SERVICE_URL` akan jatuh ke `http://ml-service:9000`, padahal hostname itu hanya bisa di-resolve **di dalam** jaringan `jawara-net`. Dari proses yang jalan di komputer lokal, alamat yang benar adalah `http://localhost:9000` (lihat bagian 4, nilai ini diturunkan dari `ML_SERVICE_PORT`).

Sebelum menyalahkan konfigurasi, cek dulu servicenya benar-benar hidup:

```bash
curl -H "X-Internal-Api-Key: <ML_SERVICE_API_KEY>" http://localhost:9000/v1/ready
```

Kalau kamu melihat `degradations: ["generation_unavailable:ml_unreachable"]`, artinya jawaban jatuh ke template dan klasifikasi cuma berjalan pakai rules saja. Ini bukan crash, tapi juga bukan hasil yang mau kamu ukur saat sedang menguji pipeline.

### Troubleshooting: `/health` membalas `{"status":"degraded","dependencies":{"database":false,"redis":false}}`

Akar masalahnya: container `postgres`/`redis` tidak bisa dijangkau dari `localhost`. Biasanya salah satu dari empat penyebab berikut:

1. **`.env` belum punya `POSTGRES_PORT`/`REDIS_PORT`.** Docker Compose butuh dua variabel ini untuk mempublish port container ke komputermu (`${POSTGRES_PORT}:5432`, `${REDIS_PORT}:6379`). Tambahkan ke `.env` (contoh nilainya ada di `.env.example`), lalu jalankan ulang `docker compose up -d postgres redis`.
2. **`docker compose ps` menunjukkan `postgres`/`redis` belum berstatus `healthy`.** Tunggu healthcheck-nya selesai dulu (butuh sekitar 10 detik untuk postgres, 5 detik untuk redis) sebelum test `/health`.
3. **`DATABASE_URL`/`REDIS_URL` di terminal backend masih mengarah ke hostname Docker (`postgres`/`redis`), bukan `localhost`.** Karena proses lokal berada di luar `jawara-net`, wajib pakai `localhost:<port>` (lihat tabel environment variable di bagian 4).
4. **(Khusus Windows/Docker Desktop) `docker compose up` gagal mempublish port** dengan pesan error `bind: An attempt was made to access a socket in a way forbidden by its access permissions`. Ini adalah bug jaringan di Docker Desktop, bukan masalah di compose atau kode project. Untuk memastikan, coba `docker run --rm -p <port>:80 nginx:alpine`. Kalau ini juga gagal, artinya semua publish port sedang terblokir. Solusinya: restart Docker Desktop (keluar sepenuhnya lewat ikon tray, lalu buka lagi), kemudian jalankan ulang `docker compose up -d waha postgres redis qdrant`.

---

## 5. Jalankan Frontend (Next.js) Lewat CLI Lokal

```bash
cd frontend
bun install
```

Port default dari Next.js dev server (`3000`) **bentrok** dengan port host milik WAHA (`3000:3000`). Jadi jalankan di port lain:

```bash
NEXT_PUBLIC_API_URL=http://localhost:8000 bun dev -- -p 3001
```

Buka `http://localhost:3001` di browser. Kamu akan dialihkan ke halaman `/login` selama belum ada sesi login. Masuk dengan akun yang sudah dibuat di bagian 4, setelah itu halaman Command Center akan terbuka. Layar kedua yang bisa dicoba: `/system/service-health`.

Sesi login berumur 8 jam (diatur lewat `AUTH_SESSION_TTL_MINUTES`) dan tersimpan di `localStorage` browser. Kalau salah password 5 kali dalam 5 menit, kamu akan dapat error `429` untuk kombinasi (email, IP) itu. Solusinya, tunggu sampai jendela waktunya lewat, atau untuk kebutuhan dev bisa hapus manual key-nya lewat `docker compose exec redis redis-cli --scan --pattern 'ratelimit:login:*'`.

Kalau dashboard sudah tampil tapi semua angkanya "belum tersedia", cek apakah `CORS_ALLOW_ORIGINS` di backend sudah memuat `http://localhost:3001`. Kalau tidak, browser akan diam-diam memblokir responsnya tanpa pemberitahuan yang jelas.

Perlu diketahui juga: kalau kamu menjalankan frontend lewat compose (bukan CLI lokal), `NEXT_PUBLIC_API_URL` dimasukkan sebagai **build arg** (nilai yang ditanamkan saat proses build, bukan saat runtime). Next.js akan meng-inline nilai ini ke bundle yang dikirim ke browser saat proses build. Jadi kalau kamu mengubah nilainya, kamu harus jalankan `docker compose build frontend-dashboard` ulang, restart saja tidak akan cukup.

---

## 5b. Menguji Bot di Grup WhatsApp

Prasyaratnya: `api-gateway` dan `celery-worker` **harus dijalankan lewat compose**, bukan CLI lokal. Alasannya, `WHATSAPP_HOOK_URL` di `docker-compose.yml` menunjuk ke `http://api-gateway:8000/api/v1/webhook`, dan hostname itu hanya bisa di-resolve **di dalam** jaringan `jawara-net`. Kalau gateway kamu jalankan secara lokal, log WAHA akan penuh dengan pesan error seperti ini:

```text
POST request failed: getaddrinfo ENOTFOUND api-gateway
```

Artinya, tiap pesan WhatsApp (baik personal maupun grup) akan dicoba ulang (retry) 15 kali lalu akhirnya dibuang. Kalau kamu tetap mau menguji dari lokal, lihat alternatifnya di bagian 6 (override `host.docker.internal`).

Langkah untuk menguji:

1. Jalankan `docker compose up -d api-gateway celery-worker`, tunggu sampai statusnya `healthy`.
2. Masukkan nomor bot ke grup WhatsApp yang dipakai untuk uji coba.
3. Kirim pesan biasa di grup itu. **Bot harus diam**, tidak membalas apa pun. Log worker akan menunjukkan pesan `group message not addressed to the bot, skipped`.
4. Sebut (mention) bot dengan klaim yang bisa dicek, misalnya `@62xxxx tolong cek: air rebusan daun kitolod bisa sembuhkan katarak tanpa operasi`. Bot akan membalas sambil mengutip pesan itu.
5. Cara lain: reply salah satu balasan bot sebelumnya, lalu tulis pertanyaan lanjutan.

Aturan ini diatur di `backend/app/pipeline/group_policy.py`. Di dalam grup, bot hanya akan menjawab kalau dia **di-mention** atau **di-reply**. Pesan grup yang tidak menyapa bot akan dibuang **sebelum** sempat memanggil ML dan **sebelum** dicatat di baris audit. Jadi isi obrolan grup yang tidak ditujukan untuk bot tidak pernah tersimpan sama sekali.

Ada satu setting bernama `GROUP_REPLY_REQUIRES_TRIGGER=false` yang bisa mematikan syarat di atas (bot akan membalas semua pesan di grup). Ini hanya masuk akal untuk grup uji coba sekali pakai. Kalau dipakai di grup nyata, ini akan dianggap spam dan berisiko membuat nomor bot diblokir WhatsApp.

Identitas bot (JID `@c.us` dan pasangannya `@lid`) diambil otomatis lewat `GET /api/sessions/{session}` dan disimpan sementara (cache) per proses worker. Kalau proses pengambilan identitas ini gagal, bot akan **diam** di grup, bukan malah membalas semua pesan. Untuk memaksa identitasnya, isi `BOT_WHATSAPP_IDS` di `.env`.

---

## 6. Catatan Penting: WAHA Webhook Tidak Bisa Menjangkau Backend Lokal Secara Default

Nilai `WHATSAPP_HOOK_URL` di `docker-compose.yml` sudah ditulis langsung (hardcode) ke `http://api-gateway:8000/api/v1/webhook`. Hostname ini hanya bisa di-resolve **di dalam** jaringan `jawara-net`. Kalau `api-gateway` tidak dijalankan lewat compose (seperti kasus dev di panduan ini), container WAHA tidak akan bisa menjangkau backend lokal yang jalan di komputermu.

Untuk menguji alur webhook secara end-to-end (dari WAHA ke FastAPI lokal) tanpa perlu mengubah kode, ada dua pilihan:

- **Opsi A, pakai compose override.** Tambahkan konfigurasi ini di `docker-compose.override.yml`:
  ```yaml
  services:
    waha:
      environment:
        - WHATSAPP_HOOK_URL=http://host.docker.internal:8000/api/v1/webhook
  ```
  `host.docker.internal` adalah alamat khusus yang otomatis mengarah ke komputer host di Docker Desktop (Windows/Mac).
- **Opsi B, lewati proses pairing webhook untuk kebutuhan dev harian**, langsung uji endpoint-nya saja:
  ```bash
  curl -X POST http://localhost:8000/api/v1/webhook \
    -H "X-Api-Key: <WAHA_API_KEY>" -H "Content-Type: application/json" \
    -d '{"event":"message.any","session":"default","payload":{"id":"1","body":"test"}}'
  ```

Pastikan Celery worker sudah menyala (lihat bagian 4b) dan jalankan bersamaan dengan backend. Tujuannya supaya job yang masuk ke antrean benar-benar diproses, bukan cuma menumpuk di Redis tanpa dikerjakan.

---

## 7. Stop / Teardown (Mematikan Semua Service)

```bash
docker compose stop waha postgres redis qdrant   # berhenti, data (volume) tetap disimpan
docker compose down                              # berhenti + hapus container, named volume tetap disimpan
docker compose down -v                           # DESTRUKTIF: ikut menghapus waha_sessions/postgres_data/qdrant_data
```

Peringatan: perintah ketiga (`docker compose down -v`) akan menghapus semua data secara permanen. Jangan jalankan kecuali kamu memang sengaja mau mulai dari nol.

Untuk mematikan proses yang jalan di CLI lokal (backend, Celery worker, frontend), cukup tekan `Ctrl+C` di masing-masing terminal.

---

**Related:** [[03_Tech_Stack]] · [[01_System_Architecture]] · [[02_Prod_Environtment]] · [[TASKS]]
