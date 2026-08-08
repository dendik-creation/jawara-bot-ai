# Threat Model & Data Protection

> **Status:** Dokumen desain. Sebagian kontrol sudah berjalan (ditandai Implemented), sebagian besar masih Planned.

JAWARA menangani isi percakapan pribadi. Dokumen ini menyatakan apa yang dilindungi, dari siapa, dan dengan kontrol apa.

---

## 1. Aset yang Dilindungi

| Aset | Kenapa berharga bagi penyerang |
| :--- | :--- |
| Isi pesan yang dianalisis | Data percakapan pribadi keluarga |
| Pemetaan `user_hash` ↔ nomor WhatsApp | Membuka identitas pengguna |
| `USER_HASH_SALT` | Salt bocor + daftar nomor = hash bisa dibalik brute force (ruang nomor telepon kecil) |
| Sesi WhatsApp (volume `waha_sessions`) | Pengambilalihan akun bot |
| `WAHA_API_KEY` | Injeksi event webhook palsu |
| Kredensial operator & token sesi Control Panel | Akses penuh ke data dan kontrol keamanan |
| Knowledge Base & dataset | Peracunan konteks/model (poisoning) |
| Artefak model | Manipulasi keputusan deteksi |

---

## 2. Aktor Ancaman

| Aktor | Kemampuan |
| :--- | :--- |
| Penipu/spammer di WhatsApp | Mengirim pesan bervolume tinggi, mencoba menghindari deteksi |
| Penyerang yang menemukan webhook publik | Mengirim event palsu, membanjiri antrean |
| Operator internal yang lalai atau jahat | Menyalahgunakan akses ke isi pesan, mengubah policy, mempromosikan model |
| Penyuplai dokumen/dataset | Meng-upload konten beracun atau file berbahaya |
| Penyerang jaringan lokal (server salah konfigurasi) | Mengakses Postgres/Redis/Qdrant yang port-nya terbuka |

---

## 3. Kontrol Saat Ini (Implemented)

| Kontrol | Lokasi |
| :--- | :--- |
| Autentikasi webhook `X-Api-Key` | `backend/app/core/security.py` |
| Rate limit sliding-window per `(session, chat_id)` — 20/60s, balas `429` + `Retry-After` | `backend/app/core/rate_limit.py` |
| Anonimisasi `user_hash` SHA-256 bersalt | `backend/app/core/hashing.py` |
| Ack webhook cepat + offload async (mengurangi permukaan DoS pada jalur sinkron) | `app/services/queue.py`, `app/worker/` |
| Structured logging dengan `waha_message_id` sebagai correlation ID | `backend/app/core/logging.py` |
| Migrasi schema idempotent dengan ledger `schema_migrations` | `backend/app/db/` |

Catatan operasional: rate limiter **fail open** — bila Redis tidak reachable, request diteruskan dan kegagalan dicatat. Ini keputusan sadar (ketersediaan di atas penegakan), dan alasan kenapa rate limit di reverse proxy tetap layak sebagai lapisan kedua.

---

## 4. Kontrol yang Belum Ada (Planned)

- Autentikasi & sesi operator Control Panel
- RBAC dan penegakannya di sisi server ([[07_Users_and_Risk]])
- Audit log aksi operator ([[05_Audit_Logs]])
- Validasi upload (tipe, ukuran, scanning) untuk Knowledge Base dan dataset
- Autentikasi service-to-service gateway ↔ ML Service
- Konfigurasi CORS untuk origin dashboard
- Retention/deletion policy untuk isi pesan

---

## 5. Isu Terbuka Berprioritas Tinggi

### 5.1 Retensi `message_logs.extracted_text`

Isi pesan disimpan plaintext tanpa batas waktu. Ini bertentangan dengan posisi privasi produk. Yang harus diputuskan:

- Berapa lama isi pesan disimpan?
- Apakah disimpan penuh, dipotong, atau hanya fitur turunan (hash, indicator, panjang)?
- Siapa yang boleh membacanya, dan apakah pembacaan itu diaudit?
- Bagaimana penghapusan dijalankan (job terjadwal, partisi per periode)?

Keputusan ini harus diambil **sebelum** tabel mulai menerima trafik nyata, dan sebelum ML Service ikut menyentuh payload yang sama.

### 5.2 Ruang Lingkup Consent

Produk diposisikan sebagai *consent-based* (hanya memproses pesan yang sengaja diteruskan/di-tag pengguna). Konfigurasi webhook saat ini berlangganan `message.any`. Bila filter consent tidak ditegakkan di sisi gateway, sistem memproses lebih banyak daripada yang dijanjikan dokumen produk. Filter ini **belum diimplementasikan**.

### 5.3 Kepatuhan UU PDP

Belum ada analisis kepatuhan terhadap UU Perlindungan Data Pribadi, padahal sistem memproses data percakapan dan konteks kesehatan. Perlu ditetapkan: dasar pemrosesan, hak subjek data, dan prosedur permintaan penghapusan.

---

## 6. Data Minimization

Prinsip yang dianut:

1. Simpan hasil analisis, bukan bahan mentah, kecuali bahan mentah memang dibutuhkan untuk investigasi.
2. Identitas selalu dalam bentuk hash bersalt.
3. Isi pesan hanya tampil ke role yang membutuhkannya.
4. Dataset training memakai data yang sudah dikurasi dan divalidasi, bukan dump trafik mentah ([[04_Datasets_and_Operator_Feedback]]).

---

**Related:** [[06_Platform_Security_Requirements]] · [[05_Audit_Logs]] · [[04_Message_Inspection]] · [[01_PostgreSQL_Schema]] · [[02_Prod_Environtment]]
