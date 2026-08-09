# Platform Security Requirements

Persyaratan keamanan lintas-komponen. Tiap item ditandai statusnya: **Implemented** (ada kodenya) atau **Planned**.

---

## 1. Akses

| Persyaratan | Status | Catatan |
| :--- | :--- | :--- |
| Authentication (operator Control Panel) | Planned | Sesi berbasis token, expiry eksplisit. Sementara ada `DASHBOARD_API_KEY` — shared secret level deployment, **bukan** identitas per-pengguna dan **bukan** pengganti item ini |
| Authorization / RBAC | Planned | Ditegakkan di server, bukan hanya menyembunyikan menu ([[07_Users_and_Risk]]) |
| Webhook authentication (`X-Api-Key`) | Implemented | `backend/app/core/security.py` |
| Service-to-service auth (gateway ↔ ML Service) | Implemented | `X-Internal-Api-Key` via env, diperiksa sebagai FastAPI dependency (`ml-service/app/core/security.py`); ML Service hanya reachable di jaringan Docker internal |
| CORS | Implemented | Daftar origin eksplisit dari `CORS_ALLOW_ORIGINS`, bukan wildcard (`backend/app/main.py`) |

Dua kelas kredensial ini tidak boleh dicampur: token sesi operator (identitas per-user, berumur pendek) dan API key webhook (mesin, berumur panjang). Model ancamannya berbeda — pembajakan sesi vs pemalsuan webhook.

---

## 2. Input & Trafik

| Persyaratan | Status | Catatan |
| :--- | :--- | :--- |
| Input validation (Pydantic) di setiap boundary | Implemented untuk boundary yang ada | Webhook (`app/schemas/webhook.py`), kontrak ML Service (`ml-service/app/schemas/contract.py`), query param dashboard (`Query(ge=, le=)`) |
| Rate limiting | Implemented | 20 req / 60s per `(session, chat_id)`, sliding window Redis, `429` + `Retry-After`; **fail open** bila Redis mati |
| Ukuran payload maksimum | Partial | Teks pesan dipotong di `MAX_LENGTH` (4000 karakter) sebelum diproses; batas ukuran upload belum ada karena endpoint upload belum ada |
| Idempotency | Implemented untuk jalur pesan | `waha_message_id` UNIQUE mencegah pencatatan ganda saat webhook retry (terverifikasi live); `request_id` dibawa ke setiap panggilan ML Service dan diecho di responsnya |

---

## 3. Upload File (Knowledge Base & Dataset)

Semua **Planned**. Dokumen dan dataset yang di-upload **bukan input tepercaya**.

Satu kontrol dari daftar ini sudah berlaku lebih awal karena knowledge sudah masuk konteks LLM: **prompt injection**. Konteks knowledge disisipkan ke prompt di dalam blok berlabel data, dengan instruksi eksplisit untuk tidak mematuhi isinya, dan system prompt dikirim di field `system` terpisah — bukan digabung ke turn pengguna (`ml-service/app/llm/prompt.py`).

| Kontrol | Keterangan |
| :--- | :--- |
| Validasi tipe file | Whitelist ekstensi + verifikasi mime/magic bytes, bukan hanya nama file |
| Batas ukuran file | Ditetapkan per tipe; ditolak sebelum diproses |
| Sanitasi nama file & path | Cegah path traversal saat penyimpanan |
| Isolasi parsing | Parser dokumen adalah permukaan serangan; batasi waktu dan resource |
| Validasi dataset | Skema kolom, distribusi label, deteksi duplikat, deteksi label rusak ([[04_Datasets_and_Operator_Feedback]]) |
| Status review | Knowledge/dataset baru berstatus belum tepercaya sampai divalidasi |
| Prompt injection | Konten dokumen yang masuk konteks LLM diperlakukan sebagai data, bukan instruksi |

---

## 4. Operasi AI/ML

| Persyaratan | Status | Catatan |
| :--- | :--- | :--- |
| Training job isolation | Planned | Job berjalan di ML Service/worker terpisah dengan batas resource; **tidak pernah** sinkron di dalam request FastAPI |
| Model artifact validation | Planned | Verifikasi integritas (checksum) dan asal artefak sebelum dimuat |
| Explicit model deployment | Planned | Promosi ke produksi selalu tindakan manual yang diaudit ([[07_Model_Registry_and_Deployment]]) |
| Pembatasan pemicu training | Planned | Hanya role tertentu; job tercatat di audit log |

---

## 5. Rahasia & Konfigurasi

| Persyaratan | Status | Catatan |
| :--- | :--- | :--- |
| Rahasia lewat env, tidak di-commit | Implemented | `.env` di-gitignore; `.env.example` sebagai template |
| `USER_HASH_SALT` diperlakukan setara password DB | Implemented (konvensi) | Ganti salt = seluruh `user_subscriptions` lama tidak match dan `message_logs`-nya ikut terhapus lewat cascade |
| Rotasi `WAHA_API_KEY` | Planned | Rotasi berkala, jangan dipakai ulang antar environment |
| Tidak ada kredensial di contoh dokumentasi | Implemented | Blok compose di [[03_Tech_Stack]] memakai placeholder `${VAR}` |
| Secrets manager / vault | Deferred | Pola `.env` memadai untuk target deployment self-hosted saat ini |

---

## 6. Error Handling & Observability

| Persyaratan | Status | Catatan |
| :--- | :--- | :--- |
| Error terstruktur, tanpa membocorkan internal | Partial | ML Service memakai `{error_code, message, retryable}` di seluruh `/v1` termasuk handler exception terakhir; gateway masih memakai `detail` FastAPI standar |
| Structured logging | Implemented | JSON satu baris per event, di gateway, worker, dan ML Service |
| Correlation ID lintas hop | Implemented | `waha_message_id` mengalir gateway → worker → `request_id` ML Service → baris `message_logs` |
| Log tidak memuat rahasia atau isi pesan penuh | Partial | API key threat intel di-scrub sebelum di-log dan tidak pernah masuk body/URL yang di-log; isi pesan tidak pernah masuk log (hanya ke kolom `extracted_text`, yang bisa dimatikan lewat `LOG_MESSAGE_CONTENT`) |

---

## 7. Deployment

| Persyaratan | Status | Catatan |
| :--- | :--- | :--- |
| PostgreSQL/Redis/Qdrant tidak terekspos ke internet | Planned (operasional) | Port-nya dipublish untuk dev hybrid; wajib diblokir firewall di produksi ([[02_Prod_Environtment]]) |
| TLS termination via reverse proxy | Planned | Compose tidak menyediakan HTTPS sendiri |
| Backup terverifikasi | Partial | Prosedur backup terdokumentasi; belum ada uji restore |

---

**Related:** [[01_Threat_Model_and_Data_Protection]] · [[05_Audit_Logs]] · [[04_ML_Service]] · [[03_Knowledge_Base]] · [[02_Prod_Environtment]]
