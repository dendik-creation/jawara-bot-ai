# Platform Security Requirements

Persyaratan keamanan lintas-komponen. Tiap item ditandai statusnya: **Implemented** (ada kodenya) atau **Planned**.

---

## 1. Akses

| Persyaratan | Status | Catatan |
| :--- | :--- | :--- |
| Authentication (operator Control Panel) | Planned | Sesi berbasis token, expiry eksplisit |
| Authorization / RBAC | Planned | Ditegakkan di server, bukan hanya menyembunyikan menu ([[07_Users_and_Risk]]) |
| Webhook authentication (`X-Api-Key`) | Implemented | `backend/app/core/security.py` |
| Service-to-service auth (gateway ↔ ML Service) | Planned | Internal API key via env, diperiksa sebagai FastAPI dependency; ML Service tidak terekspos publik |
| CORS | Planned | Kunci ke origin dashboard yang diketahui, jangan wildcard |

Dua kelas kredensial ini tidak boleh dicampur: token sesi operator (identitas per-user, berumur pendek) dan API key webhook (mesin, berumur panjang). Model ancamannya berbeda — pembajakan sesi vs pemalsuan webhook.

---

## 2. Input & Trafik

| Persyaratan | Status | Catatan |
| :--- | :--- | :--- |
| Input validation (Pydantic) di setiap boundary | Partial | Sudah ada untuk payload webhook (`app/schemas/webhook.py`); boundary lain menyusul |
| Rate limiting | Implemented | 20 req / 60s per `(session, chat_id)`, sliding window Redis, `429` + `Retry-After`; **fail open** bila Redis mati |
| Ukuran payload maksimum | Planned | Perlu ditetapkan per endpoint, khususnya upload |
| Idempotency | Partial | `waha_message_id` UNIQUE mencegah pencatatan ganda saat webhook retry; `request_id` untuk panggilan ML Service masih Planned |

---

## 3. Upload File (Knowledge Base & Dataset)

Semua **Planned**. Dokumen dan dataset yang di-upload **bukan input tepercaya**.

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
| Error terstruktur, tanpa membocorkan internal | Partial | Perlu kontrak error konsisten di seluruh API |
| Structured logging | Implemented | JSON satu baris per event |
| Correlation ID lintas hop | Partial | `waha_message_id` sudah dipakai gateway↔worker; perlu diperluas ke ML Service dan baris audit |
| Log tidak memuat rahasia atau isi pesan penuh | Planned | Perlu aturan eksplisit sebelum volume log bertambah |

---

## 7. Deployment

| Persyaratan | Status | Catatan |
| :--- | :--- | :--- |
| PostgreSQL/Redis/Qdrant tidak terekspos ke internet | Planned (operasional) | Port-nya dipublish untuk dev hybrid; wajib diblokir firewall di produksi ([[02_Prod_Environtment]]) |
| TLS termination via reverse proxy | Planned | Compose tidak menyediakan HTTPS sendiri |
| Backup terverifikasi | Partial | Prosedur backup terdokumentasi; belum ada uji restore |

---

**Related:** [[01_Threat_Model_and_Data_Protection]] · [[05_Audit_Logs]] · [[04_ML_Service]] · [[03_Knowledge_Base]] · [[02_Prod_Environtment]]
