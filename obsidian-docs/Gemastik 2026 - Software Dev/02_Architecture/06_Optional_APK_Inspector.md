# APK Inspector (Opsional / Future)

> **Scope:** Opsional / Future. **Bukan MVP.** Modul ini tidak boleh menjadi dependensi arsitektur awal JAWARA, dan tidak boleh dicampur ke dalam pipeline deteksi WhatsApp.
> **Status implementasi:** belum ada kode.

---

## 1. Posisi Terhadap MVP

Sebelumnya APK analysis digambarkan sebagai salah satu dari lima verification engine inti (`FILE_APK` → "Malicious APK Inspector"). Itu tidak lagi berlaku sebagai scope MVP.

Yang **tetap ada di MVP**:

- Deteksi bahwa sebuah pesan membawa lampiran `.apk` (tipe file, nama, ukuran, hash).
- Klasifikasi kategori ancaman dan risk score berdasarkan konteks pesan (rules + ML), bukan berdasarkan isi APK.
- Aksi policy dan peringatan generik: file aplikasi yang dikirim lewat WhatsApp jangan dipasang.

Yang **tidak ada di MVP**:

- Static analysis isi APK, pembacaan Android Manifest, analisis permission, deteksi API mencurigakan, analisis signature, malware classification, laporan keamanan per-APK.

---

## 2. Kemampuan yang Mungkin Dibangun Nanti

- Upload APK dari Control Panel
- Static analysis
- Inspeksi Android Manifest
- Analisis permission
- Deteksi pemanggilan API mencurigakan
- Analisis metadata package
- Analisis signature
- Threat scoring
- Malware classification
- Pembuatan security report

---

## 3. Arsitektur Potensial

```text
Dashboard
    ↓
FastAPI
    ↓
APK Analysis Service
    ↓
Static Analysis / ML
    ↓
Security Report
```

Catatan desain bila modul ini jadi dibangun:

- Berdiri sebagai **service terpisah** (bukan di dalam gateway, bukan di dalam ML Service inti), dengan Dockerfile, healthcheck, dan skala sendiri.
- Sandbox eksekusi: file APK adalah input tidak tepercaya. Parsing harus terisolasi, dibatasi waktu, dan dibatasi resource.
- Batas ukuran file dan validasi tipe di gateway, sebelum file mencapai analyzer.
- Hasilnya masuk sebagai *enrichment* pada Threat/Incident yang sudah ada, bukan sebagai jalur deteksi paralel yang bersaing.

---

## 4. Alasan Ditunda

1. Pipeline utama JAWARA adalah teks/URL/social engineering di WhatsApp; APK adalah permukaan serangan yang berbeda dan butuh toolchain sendiri.
2. Static analysis yang setengah jadi menghasilkan false confidence — lebih berbahaya daripada tidak menganalisis sama sekali dan memberi peringatan generik.
3. Membuat MVP bergantung pada modul ini berarti rilis pertama tertahan oleh pekerjaan yang bisa dilepas.

---

**Related:** [[05_Product_Scope_and_Roadmap]] · [[01_System_Architecture]] · [[05_Integrations]] · [[03_Threat_Monitoring]]
