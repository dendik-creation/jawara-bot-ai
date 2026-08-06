# Index Dokumentasi Proyek JAWARA: Jaringan Asisten WhatsApp Anti-Rekayasa & Ancaman

> **Project Name:** JAWARA: Jaringan Asisten WhatsApp Anti-Rekayasa & Ancaman (Smart Family Guard)
> *Previously known as CucuDigital; renamed to JAWARA.*
> **Target Competition:** Gemastik 2026 — Cabang Software Development  
> **Role:** Lead Developer & System Architect  
> **Status:** Full Specification & Production Architecture Ready (Self-Hosted WAHA API)  

---

## Navigasi Dokumentasi

### 01. Overview & Business Strategy
- [[01_Problem_Statement|01. Masalah & Ruang Lingkup Proyek]] — *Analisis akar masalah disinformasi & penipuan digital di WhatsApp, E2EE constraint, dan target audiens rentan.*
- [[02_Value_Proposition|02. Value Proposition & Pembeda Utama]] — *Empat pilar keunggulan, frictionless WhatsApp integration, dan matriks komparasi dengan solusi eksisting.*
- [[03_Pitching_Narrative|03. Naskah Pitching & Framing Produk]] — *Elevator pitch, Problem-Solution fit, rencana integrasi B2G (Pemerintah/Dinas), dan indikator dampak sosial.*
- [[04_How_it_Works|04. Cara Kerja Sistem & Flowchart Utama]] — *Flowchart utama Mermaid-compatible (WAHA API Engine) dan penjelasannya untuk referensi penulisan proposal paper Gemastik.*

### 02. System Architecture & Technical Specifications
- [[01_System_Architecture|01. Arsitektur Sistem (4-Layer)]] — *Desain arsitektur Modular Monolith/Microservices: WAHA Self-Hosted Engine, FastAPI Gateway, Core AI, dan Data Layer.*
- [[02_Data_Pipeline|02. Data Pipeline & Sequence Flow]] — *Alur pemrosesan WAHA Webhook, async worker queue, pemrosesan multimodal (Teks, Gambar OCR, Link Phishing, File APK, Rekening Fraud), dan latency strategy.*
- [[03_Tech_Stack|03. Spesifikasi Tech Stack & Deployment]] — *Rincian teknologi (WAHA Self-Hosted, FastAPI, Redis, Celery, PostgreSQL 16, Qdrant, LlamaIndex, Next.js 14), pertimbangan biaya, dan Dockerization.*

### 03. Database & Knowledge Base Specifications
- [[01_PostgreSQL_Schema|01. Skema Relational Database (PostgreSQL)]] — *ERD, skema tabel terintegrasi (WAHA message ID), Enum, trigger timestamp, indeks performa tinggi, dan SQL DDL.*
- [[02_VectorDB_Specifications|02. Skema & Konfigurasi Vector DB (Qdrant/Milvus)]] — *Struktur Payload JSON, HNSW index config, strategi Hybrid Search, dan query retrieval RAG.*

### 04. AI Engine & Prompt Engineering
- [[01_LLM_System_Prompt|01. System Prompt LLM & Few-Shot Examples]] — *Persona JAWARA, panduan WhatsApp Markdown output, safety guardrails, serta 5 contoh kasus penanganan nyata.*

### 05. Documentation Audit
- [[01_Documentation_Audit_Report|01. Documentation Audit Report]] — *Problem-feature correlation matrix, inconsistencies, missing sections (Security, Deployment, Roadmap), priority-ranked action items.*

### 06. Sprint Board
- [[TASKS|Sprint Kanban Board]] — *Engineering task board (To Do / In Progress / Revision / Finished) derived from the full vault, sequenced by implementation dependency.*

---

## Ringkasan Arsitektur Singkat

```
[WhatsApp User / Group] <───> [WAHA Self-Hosted API Engine]
                                        │
                               (Local HTTP Webhook)
                                        │
                                        ▼
                           [FastAPI Gateway + Redis Queue]
                                        │
    ┌───────────────────────────────────┴───────────────────────────────────┐
    │                                                                       │
[Multimodal OCR / Safety Engine]                                   [Intent Router]
(EasyOCR, VirusTotal, CekRekening)                                          │
    │                                                                       ▼
    └─────────────────────────────────────────────────────────> [RAG & Vector Search]
                                                                (Qdrant + LlamaIndex)
                                                                            │
                                                                            ▼
                                                                   [JAWARA LLM]
                                                                   (WAHA REST Dispatch)
```

---
*Dokumentasi ini dirancang secara modular dan komprehensif sebagai acuan pengembangan Perangkat Lunak Gemastik 2026.*
