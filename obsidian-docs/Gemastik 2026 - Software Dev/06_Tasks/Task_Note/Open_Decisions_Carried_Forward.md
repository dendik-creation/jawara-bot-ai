# Keputusan Terbuka yang Dibawa ke Sprint Berikutnya

Indeks: [[00_Sprint_1_Completion_Notes]]

Satu keputusan terbuka ditutup di sprint ini (provider LLM). Sisanya masih terbuka, ditambah beberapa yang baru muncul justru karena pipeline-nya sekarang benar-benar berjalan.

---

## 1. Ditutup di Sprint 1

| Keputusan | Hasil |
| :--- | :--- |
| Provider LLM | **Anthropic Claude Haiku** (`claude-haiku-4-5-20251001`). Alasan lengkap di [[Generate_LLM_Responses]]. Kontrak tetap provider-agnostic; `openai` diimplementasikan sebagai pembanding |

## 1b. Ditutup 2026-08-09

| Keputusan | Hasil |
| :--- | :--- |
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

### 3.1 Anggaran latensi vs timeout kirim WAHA

`WAHA_SEND_TIMEOUT_SECONDS` default 5 detik, sementara target end-to-end adalah 3 detik. Satu percobaan kirim yang lambat sudah melampaui seluruh anggaran.

Dua opsi:

1. Turunkan timeout kirim ke ~2 detik dan terima bahwa jaringan lambat berarti gagal kirim.
2. Definisikan ulang KPI: 3 detik diukur sampai **dispatch dimulai**, bukan sampai WAHA membalas.

Detail pengukuran di [[Implement_WhatsApp_Response_Sender]] §3.

### 3.2 Auth Control Panel sebelum ekspos publik

`DASHBOARD_API_KEY` adalah tambalan, bukan RBAC. Gateway tidak boleh diekspos ke internet sebelum auth operator ada ([[Implement_Command_Center_Dashboard]] §4).

### 3.3 Throttle kuota threat intel lintas worker

Cache dan batas per pesan sudah ada, tapi tidak ada rate limiter global. VirusTotal free tier hanya mengizinkan 4 request/menit — satu pesan berisi 5 URL sudah melampauinya ([[Integrate_VirusTotal]] §4).

### 3.4 Kehilangan baris audit saat PostgreSQL down

Disengaja (retry akan mengirim balasan dobel), tapi berarti jejaknya hilang permanen. Solusi yang benar bila ini tidak dapat diterima: task Celery terpisah dan idempoten khusus penulisan audit ([[Create_Audit_Logging]] §2).

### 3.5 Embedder produksi

Default `hash-embed-v0` bersifat leksikal; pencocokan parafrase butuh `EMBEDDING_PROVIDER=openai`. Pindah ke IndoBERT (768 dimensi) menuntut pembuatan ulang collection dan re-embedding seluruh knowledge base ([[Build_Text_Verification_Pipeline]] §3).

---

**Related:** [[03_Tech_Stack]] · [[01_Documentation_Audit_Report]] · [[05_Product_Scope_and_Roadmap]] · [[00_Sprint_1_Completion_Notes]]
