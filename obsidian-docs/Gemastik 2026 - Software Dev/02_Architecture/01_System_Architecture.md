# Arsitektur Sistem (4-Layer Production Architecture)

Sistem **JAWARA: Jaringan Asisten WhatsApp Anti-Rekayasa & Ancaman** dirancang menggunakan arsitektur **Modular Monolith yang Containerized (Docker-Ready)** berbasis engine **WAHA (WhatsApp HTTP API)** self-hosted untuk menjamin performa tinggi, efisiensi biaya (bebas biaya per pesan Meta), dan privasi data lokal.

---

## High-Level System Architecture Diagram

```mermaid
flowchart TD

    %% Presentation Layer
    subgraph L1["1. Presentation & Messaging Engine Layer"]
        WA[WhatsApp User / Group]
        WAHA["WAHA WhatsApp HTTP API<br/>(Self-Hosted Container)"]
        FE[Next.js 14 Web Dashboard]
        DH[B2G / Health Agency Dashboard]

        WA <--> WAHA
        DH <--> FE
    end

    %% Gateway & API Layer
    subgraph L2["2. Gateway & Messaging Layer"]
        GW[FastAPI Gateway]
        RL[Redis Rate Limiter]
        AU[API Key Verification & Auth]
        MQ[Redis Message Broker]
        QW[Celery Async Workers]

        GW --> RL
        GW --> AU
        GW --> MQ
        MQ --> QW
    end

    %% Core Processing Layer
    subgraph L3["3. Core AI & Safety Processing Layer"]

        subgraph PRE["Multimodal Input Processor"]
            OCR[EasyOCR / Tesseract Engine]
            TXT[Bahasa Indonesia Text Normalizer]
        end

        subgraph SAFE["Safety & Fraud Inspection Engine"]
            URL[VirusTotal & Google Safe Browsing API]
            APK[Malicious APK / File Header Inspector]
            BANK[CekRekening.id Fraud Database Matcher]
        end

        INT[Intent Router & Classifier]
        RAG[LlamaIndex RAG Retriever]
        LLM[JAWARA LLM Response Engine]

        OCR --> INT
        TXT --> INT

        URL --> INT
        APK --> INT
        BANK --> INT

        INT --> RAG
        RAG --> LLM
    end

    %% Data & Persistence Layer
    subgraph L4["4. Data & Persistence Layer"]
        VDB[(Vector Database: Qdrant)]
        SQL[(Relational Database: PostgreSQL 16)]
        EXT[External Threat Intelligence APIs]

        EXT --> API1[Cekrekening.id]
        EXT --> API2[VirusTotal API]
        EXT --> API3[Google Safe Browsing API]
    end

    WAHA -- Local HTTP Webhook --> GW
    QW --> L3
    RAG <--> VDB
    LLM --> SQL
    SAFE --> EXT
    LLM -- POST /api/sendText --> WAHA
```

---

## 1. Presentation & Messaging Engine Layer

Layer antarmuka pengguna dan engine messaging yang di-host mandiri (*self-hosted*).

| Komponen | Spesifikasi & Tanggung Jawab |
| :--- | :--- |
| **WhatsApp Client** | Interface utama end-user (HP lansia/keluarga). Menerima pesan teks, flyer gambar, link, file APK, atau nomor rekening. |
| **WAHA WhatsApp API Engine** | Container Docker (`devlikeapro/waha`) yang menghubungkan sistem ke jaringan WhatsApp Web/Engine. Mengirim webhook lokal & menyediakan REST API endpoint (`POST /api/sendText`, `/api/sendMedia`). |
| **Next.js 14 Frontend** | Dashboard analitik web berbasis React/TailwindCSS untuk memantau aktivitas sistem. |
| **B2G Health Dashboard** | Interface khusus instansi pemerintah untuk melihat *spatial heatmap* sebaran hoaks kesehatan & penipuan. |

---

## 2. Gateway & Messaging Layer

Mengelola beban trafik masuk, keamanan webhook lokal, dan pengantrean tugas agar tidak memblokir respon webhook WAHA.

```mermaid
sequenceDiagram
    autonumber
    participant WAHA as WAHA Engine (Container)
    participant GW as FastAPI Gateway
    participant REDIS as Redis Queue
    participant WORKER as Celery Worker

    WAHA->>GW: POST /api/v1/webhook (Event message.any)
    GW->>GW: Verifikasi Header API Key & Secret
    GW->>REDIS: Push Job ke Queue (Payload)
    GW-->>WAHA: 200 OK (Instant Response < 200ms)
    REDIS->>WORKER: Consume Job secara Asynchronous
```

* **FastAPI Gateway:** Asynchronous web framework berbasis Python 3.11+.
* **Redis Rate Limiter:** Mencegah spamming dan serangan DDOS dari nomor WhatsApp tertentu.
* **Celery Worker Pool:** Memproses analisis AI secara paralel di latar belakang.

---

## 3. Core AI & Safety Processing Layer

Pusat kecerdasan buatan dan pemindaian keamanan multi-vektor.

```mermaid
flowchart LR
    IN[Async Worker Payload] --> INT{Intent Router}

    INT -- Kategori Gambar --> OCR[EasyOCR Processing]
    INT -- Kategori Link/URL --> URL[URL Safety Scan]
    INT -- Kategori File --> APK[APK Header Check]
    INT -- Kategori Rekening --> BANK[Fraud DB Matcher]
    INT -- Kategori Teks/Hoaks --> RAG[RAG Semantic Search]

    OCR --> RAG
    URL --> LLM[LLM Response Generator]
    APK --> LLM
    BANK --> LLM
    RAG --> LLM
```

---

## 4. Data & Persistence Layer

* **PostgreSQL 16:** Relational database untuk menyimpan metadata fakta (`fact_items`), log pesan anonim (`message_logs`), pendaftaran pengguna (`user_subscriptions`), dan rekening penipu (`fraud_blacklists`).
* **Vector Database (Qdrant):** Menyimpan *vector embedding* dari dokumen fakta terverifikasi dengan struktur indeks HNSW.

---

**Related:** [[04_How_it_Works]] · [[02_Data_Pipeline]] · [[03_Tech_Stack]] · [[01_PostgreSQL_Schema]]