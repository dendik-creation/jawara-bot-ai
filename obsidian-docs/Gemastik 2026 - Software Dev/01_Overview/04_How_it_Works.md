# Cara Kerja Sistem & Flowchart Utama (Proposal Paper Reference)

Dokumen ini memuat **Flowchart Utama Cara Kerja Sistem JAWARA: Jaringan Asisten WhatsApp Anti-Rekayasa & Ancaman (Smart Family Guard)** berarsitektur **WAHA (WhatsApp HTTP API) Self-Hosted** yang dirancang menggunakan Mermaid Markdown. Diagram dan penjelasan di bawah ini disesuaikan untuk dapat digunakan langsung pada **Proposal Paper / Karya Tulis Gemastik 2026 (Cabang Software Development)**.

---

## 1. Flowchart Utama Cara Kerja Sistem (Mermaid Diagram)

```mermaid
flowchart TD
    %% Subgraph User & Messaging Interface
    subgraph S1["1. Antarmuka Pengguna & WhatsApp Network"]
        U1["User / Group WhatsApp"]
        U2["Pemicu: Mention / Reply / Forward Message"]
        U1 --> U2
    end

    %% Subgraph WAHA API & Ingestion Layer
    subgraph S2["2. WAHA Self-Hosted Engine & Queue Layer"]
        WAHA["WAHA WhatsApp HTTP API Container<br/>(devlikeapro/waha)"]
        GW["FastAPI Gateway & API Key Auth"]
        Q1["Redis Job Queue & Celery Worker"]

        U2 -- "WhatsApp Message Event" --> WAHA
        WAHA -- "Local HTTP Webhook (message.any)" --> GW
        GW -- "Async Offloading (< 200ms)" --> Q1
    end

    %% Subgraph Multimodal & Intent Processor
    subgraph S3["3. Preprocessing & Intent Classification"]
        P1["Multimodal Preprocessor"]
        P_TXT["Text Normalizer"]
        P_OCR["EasyOCR Engine"]
        P_LINK["Link & File Extractor"]

        IR{"Intent Router"}

        Q1 --> P1
        P1 --> P_TXT --> IR
        P1 --> P_OCR --> IR
        P1 --> P_LINK --> IR
    end

    %% Subgraph Core Verification Engine
    subgraph S4["4. Multi-Threat Verification Engine"]
        V_RAG["RAG Engine & Qdrant Vector DB<br/>(Similarity Search >= 0.80)"]
        V_SAFE["URL Safety Scanner<br/>(VirusTotal & Safe Browsing)"]
        V_BANK["Bank Fraud Matcher<br/>(CekRekening.id DB)"]
        V_APK["Malicious APK Inspector"]

        IR -- "HEALTH_HOAX / GENERAL_NEWS" --> V_RAG
        IR -- "PHISHING_LINK" --> V_SAFE
        IR -- "FINANCIAL_FRAUD" --> V_BANK
        IR -- "FILE_APK" --> V_APK
    end

    %% Subgraph LLM & Outbound WAHA Response
    subgraph S5["5. Output Generation & WAHA REST Dispatch"]
        LLM["JAWARA LLM Engine"]
        OUT["WhatsApp Markdown Formatter<br/>(Status + Penjelasan + Sumber + Draf Forward)"]
        DB_LOG[("PostgreSQL Audit Log<br/>(Hashed User Privacy Data)")]
        WAHA_POST["WAHA REST API Dispatcher<br/>(POST /api/sendText)"]

        V_RAG --> LLM
        V_SAFE --> LLM
        V_BANK --> LLM
        V_APK --> LLM

        LLM --> OUT
        OUT --> DB_LOG
        OUT --> WAHA_POST
        WAHA_POST -- "HTTP POST to WAHA Engine" --> WAHA
        WAHA -- "Balasan WhatsApp Terkirim (< 3.0s)" --> U1
    end

    %% Styling Nodes
    classDef primary fill:#e3f2fd,stroke:#1565c0,stroke-width:2px,color:#0d47a1;
    classDef success fill:#e8f5e9,stroke:#2e7d32,stroke-width:2px,color:#1b5e20;
    classDef warning fill:#fff3e0,stroke:#ef6c00,stroke-width:2px,color:#e65100;
    classDef danger fill:#ffebee,stroke:#c62828,stroke-width:2px,color:#b71c1c;

    class U1,U2,WAHA_POST success;
    class WAHA,GW,Q1,IR primary;
    class V_RAG,V_SAFE,V_BANK,V_APK warning;
    class LLM,OUT danger;
```

---

## 2. Keterangan Flowchart untuk Proposal Paper

Penjelasan alur kerja di bawah ini dapat dikutip atau disesuaikan untuk bagian **Bab III / Metode Pengembangan & Cara Kerja Sistem** pada naskah proposal paper:

### Tahap 1: Pengiriman Pesan & Inisiasi (*User-Initiated Trigger*)
* Pengguna WhatsApp (individu maupun anggota grup keluarga) meneruskan (*forward*), mereply, atau menyebut (*mention*) bot **JAWARA** saat menerima pesan mencurigakan, baik berupa teks klaim, gambar flyer, link tautan, file `.APK`, maupun nomor rekening bank.
* Sistem bekerja secara *consent-based*, artinya enkripsi *End-to-End* WhatsApp tetap terjaga penuh karena sistem hanya memproses pesan yang secara sadar dikirimkan oleh pengguna.

### Tahap 2: WAHA Webhook Ingestion & Antrean Asinkron (*WAHA Async Queue*)
* Container **WAHA (WhatsApp HTTP API)** yang di-host mandiri (*self-hosted via Docker*) menerima event pesan dari WhatsApp network dan langsung mengirimkan HTTP POST Webhook event (`message.any`) ke **FastAPI Gateway**.
* Gateway memverifikasi keaslian request menggunakan API Key header (`X-Api-Key`).
* Untuk mencegah kebocoran antrean (*timeout* webhook), Gateway memberikan respon instan `HTTP 200 OK` dalam $< 200\text{ ms}$ dan melemparkan tugas pemrosesan berat ke **Redis Job Queue** untuk dieksekusi secara asinkron oleh **Celery Workers**.

### Tahap 3: Pemrosesan Multimodal & Klasifikasi Niat (*Preprocessing & Intent Router*)
* Worker membedakan tipe masukan:
  - **Teks:** Dibersihkan dari karakter aneh dan dinormalisasi (*Text Normalizer*).
  - **Gambar:** Teks diekstraksi menggunakan mesin **EasyOCR / Tesseract**.
  - **Link/File/Rekening:** Ekstraksi komponen URL, header file, atau digit nomor rekening.
* **Intent Router** menentukan kategori ancaman utama ke dalam salah satu dari 5 domain: `HEALTH_HOAX`, `FINANCIAL_FRAUD`, `GENERAL_NEWS`, `PHISHING_LINK`, atau `FILE_APK`.

### Tahap 4: Verifikasi Ancaman Berbasis Multi-Engine (*Deep Verification*)
* **RAG Vector Search (Qdrant DB):** Teks klaim diubah menjadi *vector embedding* (1536-dim / 768-dim) dan dibandingkan dengan basis data fakta terverifikasi (*Cosine Similarity* $\ge 0.80$).
* **URL Safety Scanner:** Memindai reputasi link secara *real-time* via Google Safe Browsing API & VirusTotal.
* **Bank Fraud Matcher:** Mengecek identitas rekening/e-wallet ke basis data kejahatan finansial (CekRekening.id & database internal).
* **Malicious APK Inspector:** Memeriksa struktur header file untuk mendeteksi virus penipuan berwujud aplikasi Android.

### Tahap 5: Formulasi Balasan Empatik & WAHA Dispatch (*Output Generation & WAHA REST Dispatch*)
* **JAWARA LLM Engine** menyusun pesan balasan dengan persona yang hangat, sopan ("Bapak/Ibu"), dan mudah dipahami lansia.
* Balasan diformat dalam 4 bagian standar WhatsApp Markdown:
  1. **Status Risiko:** 🔴 *HOAKS/BAHAYA TINGGI*, 🟡 *WASPADA*, atau 🟢 *FAKTA RESMI/AMAN*.
  2. **Penjelasan Empatik:** Maksimal 4 kalimat sederhana tanpa istilah teknis yang rumit.
  3. **Referensi Resmi:** Tautan sumber terpercaya (Kemenkes, TurnBackHoax, Kominfo, CekRekening).
  4. **Draf Balasan Siap Forward (`> ...`):** Teks klarifikasi santun yang mudah di-copy/forward pengguna ke grup keluarga.
* Transaksi dicatat secara anonim di **PostgreSQL** (`message_logs`) menggunakan hash SHA-256 untuk perlindungan privasi.
* Pesan dikirimkan kembali ke WhatsApp melalui endpoint **WAHA REST API** (`POST /api/sendText`) dengan estimasi waktu total $< 3.0\text{ detik}$.

---

**Related:** [[01_System_Architecture]] · [[02_Data_Pipeline]] · [[01_LLM_System_Prompt]]
