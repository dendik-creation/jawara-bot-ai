# Keputusan Terbuka yang Dibawa ke Sprint Berikutnya

Indeks: [[00_Sprint_1_Completion_Notes]]

Satu keputusan terbuka ditutup di sprint ini (provider LLM). Sisanya masih terbuka, ditambah beberapa yang baru muncul justru karena pipeline-nya sekarang benar-benar berjalan.

---

## 1. Ditutup di Sprint 1

| Keputusan | Hasil |
| :--- | :--- |
| Provider LLM | **Anthropic Claude Haiku** (`claude-haiku-4-5-20251001`). Alasan lengkap di [[Generate_LLM_Responses]]. Kontrak tetap provider-agnostic; `openai` diimplementasikan sebagai pembanding |

## 1b. Ditutup 2026-08-09

Indeks sprint: [[00_Sprint_2_Completion_Notes]].

| Keputusan | Hasil |
| :--- | :--- |
| Auth Control Panel | **Email + password, sesi server-side, tanpa RBAC.** `DASHBOARD_API_KEY` dihapus seluruhnya (config, compose, build arg frontend, dokumen). Alasan tiap pilihan di [[Implement_Operator_Auth]] |
| Toolchain dependency Python | **`uv`, satu-satunya.** `backend/` dan `ml-service/` masing-masing punya `pyproject.toml` (dependency terpin) + `uv.lock`; `requirements.txt` / `requirements-dev.txt` dihapus dari keduanya. Kedua `Dockerfile` menyalin biner `uv` terpin dari `ghcr.io/astral-sh/uv:0.12.2` lalu `uv sync --locked --no-dev` ke interpreter sistem (`UV_PROJECT_ENVIRONMENT=/usr/local`), jadi `uvicorn`/`celery`/healthcheck `python -c` tetap jalan tanpa aktivasi venv. Base image naik dari `python:3.11-slim` ke `python:3.14-slim` supaya `requires-python = ">=3.14"` (yang sudah ada sejak awal di `backend/pyproject.toml`) benar-benar dipenuhi image, bukan hanya venv dev. Stub `backend/src/backend/` bawaan `uv init` dihapus — kode aplikasi ada di `backend/app/`, dan `[tool.uv] package = false` menegaskan service ini aplikasi, bukan library |

---

## 2. Masih terbuka (dari [[03_Tech_Stack]] §4)

### 2.1 Toolchain dependency Python — ~~`uv` vs `pip`~~ → **ditutup 2026-08-09: `uv`**

Lihat §1.

### 2.2 Transport live activity feed — **ditutup 2026-08-10**

**SSE lewat Redis Pub/Sub**, bukan WebSocket atau polling. `message_log.record_message()` publish ke channel `dashboard:activity` setelah setiap insert sukses; `GET /api/v1/dashboard/activity/stream` fan-out event itu ke operator yang terhubung. `GET /api/v1/dashboard/activity` biasa tetap ada, sekarang perannya cuma muat awal (Pub/Sub tidak punya histori — klien yang baru konek tidak dapat apa pun yang terjadi sebelum ia terhubung).

WebSocket ditolak: arah datanya cuma satu (server → browser), jadi full-duplex WebSocket menambah kompleksitas tanpa dipakai. Kendala nyata yang muncul saat implementasi: `EventSource` bawaan browser tidak bisa kirim header `Authorization`, dan gateway ini murni bearer-token (tidak ada sesi cookie). Taruh token di query string URL akan bocor ke access log gateway/proxy — jadi frontend baca SSE manual lewat `fetch()` + `ReadableStream.getReader()` (`frontend/lib/api.ts::streamActivity`), bukan `new EventSource(...)`. Diverifikasi live: publish manual ke Redis muncul di stream dalam hitungan milidetik.

Detail: [[Implement_Command_Center_Dashboard]] §5, `backend/app/api/v1/endpoints/dashboard.py::dashboard_activity_stream`.

### 2.3 Retention policy `message_logs.extracted_text` — **ditutup 2026-08-10**

Keputusan: **simpan tanpa batas waktu, bisa dibaca operator manapun (tidak ada tingkatan RBAC), dihapus hanya lewat aksi eksplisit per baris** — bukan job terjadwal atau partisi tabel. `LOG_MESSAGE_CONTENT` ([[Create_Audit_Logging]] §3) tetap ada sebagai saklar deployment-level yang independen dari keputusan ini.

Dibangun sebagai layar Message Inspection minimal ([[04_Message_Inspection]]): `GET /api/v1/dashboard/messages` (satu-satunya endpoint Control Panel yang mengembalikan `extracted_text` — semua endpoint lain di `services/dashboard.py` sengaja tidak pernah menyeleksinya) dan `DELETE /api/v1/dashboard/messages/{id}`, keduanya di belakang `require_operator` yang sama seperti seluruh router. Frontend: `/messages`, dengan konfirmasi hapus (`AlertDialog`) karena aksinya permanen.

Field lengkap di spesifikasi awal ([[04_Message_Inspection]] §1 — applied detection rule, model version, related threat/incident) belum ada kolomnya di skema dan tidak dibangun di sini; itu perluasan terpisah, bukan bagian dari menutup keputusan retention.

### 2.4 Pemetaan kategori ancaman Control Panel ke `category_enum` — **ditutup 2026-08-10**

Opsi yang diambil: **dua level**, bukan perluasan enum atau tabel referensi. `category_enum` tetap murni untuk intent router dan `fact_items` (terkunci ke `tests/test_categories.py`, yang mem-parse skema SQL); kategori ancaman Control Panel (Phishing, Scam, Social Engineering, Malicious Link, Impersonation, Spam, Other) jadi enum Python terpisah, `ThreatCategory` di `backend/app/pipeline/threat_categories.py`, dengan fungsi murni `to_threat_category()` yang memetakan satu arah.

Pemetaannya lossy di kedua arah dan itu disengaja, bukan celah:

| `Category` | → `ThreatCategory` |
| :--- | :--- |
| `HEALTH_HOAX` | `OTHER` |
| `FINANCIAL_FRAUD` | `SCAM` |
| `GENERAL_NEWS` | `OTHER` |
| `PHISHING_LINK` | `PHISHING` |
| `FILE_APK` | `MALICIOUS_LINK` |

`SOCIAL_ENGINEERING`, `IMPERSONATION`, dan `SPAM` belum bisa dicapai dari `Category` manapun — pipeline belum punya sinyal untuk membedakannya. Mereka tetap ada di `ThreatCategory` supaya filter dropdown di Control Panel lengkap, dan menambah sinyalnya nanti adalah perubahan mapping, bukan enum baru.

Sudah dipakai di `dashboard.recent_activity` dan `dashboard.recent_threats` (field `threat_category`), ditampilkan di `activity-feed.tsx` dan `recent-panels.tsx`. Test: `tests/test_threat_categories.py`.

---

## 3. Terbuka dan baru — muncul dari implementasi

### 3.1 Anggaran latensi vs timeout kirim WAHA — **ditutup 2026-08-10**

`WAHA_SEND_TIMEOUT_SECONDS` default 5 detik ternyata lebih pendek dari yang WAHA butuh: log WAHA sendiri menunjukkan `"request aborted"` di `responseTime: 5007` — server masih bekerja, klien yang menyerah. Kirim pertama ke grup/peserta `@lid` yang belum di-resolve WAHA butuh **~7,6 detik nyata**, bukan macet tanpa batas. Timeout dinaikkan ke **15 detik**, `WAHA_SEND_MAX_ATTEMPTS` diturunkan lagi ke **2** — dengan timeout yang cukup, satu percobaan sudah berhasil, jadi percobaan kedua kembali jadi anggaran retry genuine, bukan penambal.

Bug terpisah yang ikut ketahuan di jalur yang sama: WAHA mengirim event `message` **dan** `message.any` untuk pesan yang sama, keduanya di-enqueue sebagai job terpisah — setiap pesan diproses dua kali paralel, dua percobaan kirim rebutan slot WEBJS yang serial per sesi. Diperbaiki dengan dedup `waha_message_id` di Redis sebelum enqueue.

Target KPI 3 detik end-to-end **tetap tidak terpenuhi** (aktual ~7,6 detik pada kirim pertama ke chat baru) — itu bukan lagi soal timeout salah konfigurasi, itu representasi biaya WEBJS yang sebenarnya. Opsi "hangatkan sesi berkala" atau "definisikan ulang KPI sampai dispatch dimulai" masih relevan kalau angka itu perlu dikejar lebih jauh, tapi di luar cakupan perbaikan ini.

Detail pengukuran dan commit: [[Implement_WhatsApp_Response_Sender]] §3.

### 3.2 ~~Auth Control Panel sebelum ekspos publik~~ → **ditutup 2026-08-09**

Autentikasi operator (email + password, sesi server-side) sudah ada dan `DASHBOARD_API_KEY` dihapus — lihat §1c dan [[Implement_Operator_Auth]].

Yang **tetap** menghalangi ekspos publik, dan bukan lagi soal auth: belum ada RBAC, belum ada TLS di compose (§7 [[06_Platform_Security_Requirements]]), dan port PostgreSQL/Redis/Qdrant masih dipublish untuk dev hybrid.

### 3.6 Penyimpanan token sesi di browser — **baru**

Token sesi operator disimpan di `localStorage`, jadi XSS di Control Panel bisa membacanya. Mitigasi sekarang expiry 8 jam + pencabutan saat logout; itu memperkecil jendela, bukan menutup lubang.

Alternatifnya cookie `httpOnly`, yang menuntut salah satu dari:

1. Gateway dan panel satu origin (reverse proxy di depan keduanya), atau
2. Route handler Next.js yang mem-proxy setiap panggilan Control Panel supaya cookie-nya milik origin panel.

Keduanya perubahan arsitektur, bukan penggantian satu modul — walau di sisi frontend dampaknya terbatas ke `lib/session.ts`, satu-satunya tempat yang tahu kunci penyimpanan.

### 3.3 Throttle kuota threat intel lintas worker

Cache dan batas per pesan sudah ada, tapi tidak ada rate limiter global. VirusTotal free tier hanya mengizinkan 4 request/menit — satu pesan berisi 5 URL sudah melampauinya ([[Integrate_VirusTotal]] §4).

### 3.4 Kehilangan baris audit saat PostgreSQL down

Disengaja (retry akan mengirim balasan dobel), tapi berarti jejaknya hilang permanen. Solusi yang benar bila ini tidak dapat diterima: task Celery terpisah dan idempoten khusus penulisan audit ([[Create_Audit_Logging]] §2).

### 3.5 Embedder produksi

Default `hash-embed-v0` bersifat leksikal; pencocokan parafrase butuh `EMBEDDING_PROVIDER=openai`. Pindah ke IndoBERT (768 dimensi) menuntut pembuatan ulang collection dan re-embedding seluruh knowledge base ([[Build_Text_Verification_Pipeline]] §3).

---

**Related:** [[03_Tech_Stack]] · [[01_Documentation_Audit_Report]] · [[05_Product_Scope_and_Roadmap]] · [[00_Sprint_1_Completion_Notes]]
