# Cara Kerja Sistem & Flowchart Utama (Proposal Paper Reference)

Dokumen ini memuat **Flowchart Utama Cara Kerja Sistem JAWARA: Jaringan Asisten WhatsApp Anti-Rekayasa & Ancaman** yang dirancang menggunakan Mermaid Markdown. Diagram dan penjelasan di bawah ini disesuaikan untuk dapat digunakan langsung pada **Proposal Paper / Karya Tulis Gemastik 2026 (Cabang Software Development)**.

> **Status:** tahap 1–2 (intake, auth, rate limit, queue, worker) sudah berjalan. Tahap 3–5 masih **Planned**. Diagram teknis lengkap beserta pemilik tiap tahap ada di [[02_Data_Pipeline]]; klasifikasi scope per fitur di [[05_Product_Scope_and_Roadmap]].

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

    %% Subgraph Detection Engine
    subgraph S4["4. Detection Engine (Rules + ML)"]
        RULES["Detection Rules<br/>(keyword, domain, blocklist, threshold)"]
        V_RAG["ML Service: RAG + Qdrant<br/>(Similarity Search >= 0.80)"]
        V_SAFE["URL Safety Scanner<br/>(VirusTotal & Safe Browsing)"]
        RISK["Threat Classification<br/>+ Risk Assessment"]
        POL{"Security Policy"}

        IR --> RULES
        IR --> V_RAG
        IR --> V_SAFE

        RULES --> RISK
        V_RAG --> RISK
        V_SAFE --> RISK
        RISK --> POL
    end

    %% Subgraph Action, Persistence, Response
    subgraph S5["5. Action, Persistence & WAHA Dispatch"]
        LLM["ML Service: LLM Response Generation"]
        OUT["WhatsApp Markdown Formatter<br/>(Status + Penjelasan + Sumber + Draf Forward)"]
        DB_LOG[("PostgreSQL<br/>Threat / Message / Audit")]
        DASH["Control Panel<br/>(Threats, Incidents, Alerts, Live Activity)"]
        WAHA_POST["WAHA REST API Dispatcher<br/>(POST /api/sendText)"]

        POL -- "ALLOW / WARN / BLOCK / ALERT / ESCALATE" --> DB_LOG
        POL -- "balas pengguna" --> LLM
        LLM --> OUT
        OUT --> DB_LOG
        OUT --> WAHA_POST
        DB_LOG --> DASH
        WAHA_POST -- "HTTP POST to WAHA Engine" --> WAHA
        WAHA -- "Balasan WhatsApp Terkirim (< 3.0s)" --> U1
    end

    %% Styling Nodes
    classDef primary fill:#e3f2fd,stroke:#1565c0,stroke-width:2px,color:#0d47a1;
    classDef success fill:#e8f5e9,stroke:#2e7d32,stroke-width:2px,color:#1b5e20;
    classDef warning fill:#fff3e0,stroke:#ef6c00,stroke-width:2px,color:#e65100;
    classDef danger fill:#ffebee,stroke:#c62828,stroke-width:2px,color:#b71c1c;

    class U1,U2,WAHA_POST success;
    class WAHA,GW,Q1,IR,DASH primary;
    class RULES,V_RAG,V_SAFE,RISK warning;
    class LLM,OUT,POL danger;
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

### Tahap 4: Deteksi Berbasis Rules + ML (*Detection Engine*)

Dua mekanisme berjalan berdampingan dan saling melengkapi — bukan saling menggantikan ([[03_Detection_Rules]]):

* **Detection Rules (deterministik):** keyword, domain, pola URL, repeat offender, allowlist/blocklist, dan risk threshold. Bisa diubah operator kapan saja tanpa melatih ulang model.
* **ML Analysis (probabilistik, dijalankan ML Service):** klasifikasi ancaman beserta *confidence* dan `model_version`. Bila dibutuhkan konteks pengetahuan, ML Service melakukan retrieval ke Qdrant (*Cosine Similarity* $\ge 0.80$) sebelum inference — parameter model tidak berubah karenanya ([[03_Knowledge_Base]]).
* **URL Safety Scanner:** memindai reputasi link via Google Safe Browsing API & VirusTotal (*Planned*). Kegagalan API eksternal tidak memblokir pipeline; indicator ditandai `unknown`.
* Keluaran keduanya digabung menjadi **Threat Classification + Risk Assessment**, lalu dievaluasi oleh **Security Policy** yang menentukan aksi: `ALLOW`, `WARN`, `BLOCK`, `ALERT`, atau `ESCALATE` ([[02_Security_Policies]]).

*Di luar scope MVP:* pengecekan rekening penipu (CekRekening.id) adalah **Post-MVP**; analisis statik file `.APK` adalah **Opsional / Future** ([[06_Optional_APK_Inspector]]). Lampiran `.apk` tetap dideteksi dan diperingatkan di MVP.

### Tahap 5: Aksi, Pencatatan & WAHA Dispatch (*Action, Persistence & Dispatch*)
* Bila policy meminta respons ke pengguna, **ML Service** menyusun pesan balasan dengan persona yang hangat, sopan ("Bapak/Ibu"), dan mudah dipahami lansia.
* Balasan diformat dalam 4 bagian standar WhatsApp Markdown:
  1. **Status Risiko:** 🔴 *HOAKS/BAHAYA TINGGI*, 🟡 *WASPADA*, atau 🟢 *FAKTA RESMI/AMAN*.
  2. **Penjelasan Empatik:** Maksimal 4 kalimat sederhana tanpa istilah teknis yang rumit.
  3. **Referensi Resmi:** Tautan sumber terpercaya (Kemenkes, TurnBackHoax, Kominfo, CekRekening).
  4. **Draf Balasan Siap Forward (`> ...`):** Teks klarifikasi santun yang mudah di-copy/forward pengguna ke grup keluarga.
* Transaksi dicatat secara anonim di **PostgreSQL** (`message_logs`) menggunakan hash SHA-256 untuk perlindungan privasi. Threat, keterkaitan incident, alert, dan entri audit ditulis pada tahap yang sama (*Planned*).
* Pesan dikirimkan kembali ke WhatsApp melalui endpoint **WAHA REST API** (`POST /api/sendText`) dengan estimasi waktu total $< 3.0\text{ detik}$.
* Hasilnya muncul di **Control Panel**: Command Center, Live Activity, Threat Monitoring, dan Incident Management ([[01_Control_Panel_Overview]]).

---

**Related:** [[01_System_Architecture]] · [[02_Data_Pipeline]] · [[01_LLM_System_Prompt]] · [[02_Security_Policies]] · [[03_Detection_Rules]] · [[01_Control_Panel_Overview]]
