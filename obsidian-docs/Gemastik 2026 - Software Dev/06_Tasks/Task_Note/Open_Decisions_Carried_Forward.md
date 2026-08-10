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

### 2.2 Transport live activity feed

Masih terbuka. Sementara: polling ([[Implement_Command_Center_Dashboard]] §5).

### 2.3 Retention policy `message_logs.extracted_text`

Masih terbuka, dan sekarang lebih mendesak karena kolom itu benar-benar terisi. Mitigasi sementara: flag `LOG_MESSAGE_CONTENT` ([[Create_Audit_Logging]] §3).

Yang perlu diputuskan: berapa lama disimpan, siapa yang boleh membaca, bagaimana penghapusan dijalankan (job terjadwal vs partisi tabel).

### 2.4 Pemetaan kategori ancaman Control Panel ke `category_enum`

Masih terbuka ([[01_PostgreSQL_Schema]] §0, [[Build_Intent_Router]] §5).

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
