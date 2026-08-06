# Naskah Pitching & Framing Produk

> **Target Audience:** Dewan Juri Gemastik 2026 (Cabang Pengembangan Perangkat Lunak)  
> **Tema Framing:** *"Menjaga Ruang Privat Keluarga dari Teror Disinformasi & Penipuan Digital"*  

---

## 1. Elevator Pitch (30 Detik)

> *"Bapak/Ibu Juri yang kami hormati, setiap hari jutaan lansia dan anggota keluarga di Indonesia menerima pesan berisi hoaks obat palsu, link phishing bansos, hingga file APK modus penipuan di grup WhatsApp mereka. Karena terlindungi enkripsi privat, tidak ada sistem publik yang bisa melindungi mereka secara otomatis.*
> 
> *Hadir **JAWARA: Jaringan Asisten WhatsApp Anti-Rekayasa & Ancaman (Smart Family Guard)**—asisten AI mandiri yang di-host secara self-hosted menggunakan **WAHA WhatsApp HTTP API**, bekerja secara frictionless, empatik, dan serba bisa. Cukup dengan men-tag atau meneruskan pesan, JAWARA secara otomatis memverifikasi klaim berita, memindai tautan dan APK berbahaya, mengecek nomor rekening penipu, serta menyajikan jawaban ramah lansia lengkap dengan draf balasan siap forward. **JAWARA: Menjaga Keluarga, Melindungi Indonesia dari Ruang Percakapan.**"*

---

## 2. Framing Problem-Solution Fit

```
  ┌────────────────────────────────────────┐
  │     MASALAH (THE PAIN POINT)           │
  │ • Hoaks & APK Penipuan di Grup WA      │
  │ • Lansia Rentan & Mudah Percaya        │
  │ • Hambatan Aplikasi/Browser Luar       │
  └───────────────────┬────────────────────┘
                      │
                      ▼
  ┌────────────────────────────────────────┐
  │       SOLUSI JAWARA (THE FIT)          │
  │ • Self-Hosted WAHA API Integration     │
  │ • Persona Empatik ("Bapak/Ibu")        │
  │ • Draf Forwardable (`> ...`)           │
  │ • Multimodal & Fraud Checking Engine   │
  └───────────────────┬────────────────────┘
                      │
                      ▼
  ┌────────────────────────────────────────┐
  │    DAMPAK (SOCIAL & TECH IMPACT)       │
  │ • Zero Kerugian Finansial Korban       │
  │ • Edukasi Literasi Digital Berkelanjutan│
  │ • Early Warning System B2G             │
  └────────────────────────────────────────┘
```

---

## 3. Strategi Integrasi & Model Dampak B2G (Business-to-Government)

Selain melayani masyarakat secara mandiri (self-hosted via WAHA WhatsApp API), JAWARA dirancang dengan potensi **B2G (Government / Public Health Dashboard)**:

1. **Spatial Early Warning System:**
   - Menyediakan dashboard agregasi tren hoaks secara anonim bagi **Kementerian Kominfo / Dinas Kesehatan**.
   - Contoh: Ketika tren hoaks *"Air rebusan obat X menyembuhkan katarak"* meningkat pesat di wilayah Jawa Barat, Dinas Kesehatan dapat menerbitkan edukasi resmi secara presisi.
2. **Pengayaan Data Kejahatan Siber:**
   - Mengirimkan laporan otomatis rekening penipu dan tautan phishing baru yang terdeteksi pengguna ke database **CekRekening.id** & **Patroli Siber**.

---

## 4. Key Performance Indicators (KPI) & Pengukuran Keberhasilan

- **Accuracy & Precision Rate:** $\ge 95\%$ akurasi pada verifikasi klaim hoaks terdaftar.
- **Latency Processing Time:** $< 3.0$ detik dari WAHA webhook diterima hingga balasan WhatsApp terkirim via WAHA REST API.
- **User Retention & Forward Rate:** $\ge 60\%$ draf balasan (`> ...`) yang dihasilkan AI berhasil di-copy/forward oleh pengguna ke grup lain.
- **Safety Violation Rate:** $0\%$ insiden *hallucination* pada isu medis/kesehatan (dikunci oleh strict RAG guardrails).

---

**Related:** [[01_Problem_Statement]] · [[02_Value_Proposition]] · [[04_How_it_Works]]
