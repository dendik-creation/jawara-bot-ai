# Message Inspection

> **Scope:** MVP · **Status:** Planned

Layar untuk memeriksa satu pesan yang sudah dianalisis: apa isinya, bagaimana sistem menilainya, dan kenapa.

---

## 1. Field yang Ditampilkan

| Field | Keterangan |
| :--- | :--- |
| Message ID | Identitas internal pesan |
| User reference | Referensi pengguna (bentuk ter-hash, lihat §3) |
| Timestamp | Waktu terima dan waktu selesai analisis |
| Message content | Ditampilkan **sesuai kebijakan privasi/keamanan** yang berlaku (lihat §3) |
| Classification | Kategori ancaman hasil analisis |
| Risk score | Skor risiko gabungan rules + ML |
| ML confidence | Keyakinan model terhadap klasifikasinya |
| Detected indicators | Indicator yang ditemukan (domain, nomor, pola) |
| URLs / domains | Daftar URL dan domain yang diekstrak |
| Applied detection rule | Rule deterministik mana yang cocok |
| Model version | Versi model yang mengklasifikasi |
| Final action | Aksi akhir yang diterapkan policy |
| Processing status | Status pipeline (selesai, gagal, sebagian) |
| Related threat | Threat yang terkait |
| Related incident | Incident yang terkait, bila ada |

---

## 2. Contoh Ringkasan

```text
Risk Score: 0.94
Classification: PHISHING
Confidence: 97.2%
Action: BLOCKED
Model: JAWARA-v1.2
```

---

## 3. Batas Privasi

Nilai jual JAWARA adalah privasi, jadi layar ini adalah titik paling sensitif di seluruh Control Panel.

- Referensi pengguna disimpan sebagai `user_hash` (SHA-256 bersalt), bukan nomor telepon mentah — sudah berjalan di `backend/app/core/hashing.py`.
- Isi pesan (`message_logs.extracted_text`) saat ini tersimpan plaintext dan **belum punya retention policy**. Ini temuan terbuka berprioritas tinggi; keputusannya harus diambil sebelum tabel mulai terisi trafik nyata. Lihat [[01_Threat_Model_and_Data_Protection]].
- Siapa yang boleh melihat isi pesan penuh ditentukan RBAC ([[07_Users_and_Risk]]). Akses ke isi pesan sendiri layak dicatat sebagai event audit.

**Open question:** apakah isi pesan ditampilkan penuh, dipotong, atau di-redact per role — belum diputuskan.

---

## 4. Pencarian & Filter

Minimal: rentang waktu, klasifikasi, risk score (range), aksi, model version, indicator/domain, user reference, status pemrosesan.

---

**Related:** [[03_Threat_Monitoring]] · [[05_Incident_Management]] · [[01_Threat_Model_and_Data_Protection]] · [[04_Datasets_and_Operator_Feedback]] · [[01_PostgreSQL_Schema]]
