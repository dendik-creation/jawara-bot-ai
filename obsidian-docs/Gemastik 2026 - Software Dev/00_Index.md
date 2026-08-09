# Index Dokumentasi JAWARA

> **Product:** JAWARA — Jaringan Asisten WhatsApp Anti-Rekayasa & Ancaman
> *Sebelumnya bernama CucuDigital; referensi nama lama hanya boleh muncul sebagai catatan historis.*
> **Kompetisi:** Gemastik 2026 — Cabang Software Development
> **Kategori produk:** WhatsApp-oriented security platform — mendeteksi, menganalisis, memantau, dan merespons pesan mencurigakan, penipuan, phishing, social engineering, dan ancaman digital lain.
> **Status:** Dokumentasi arsitektur target lengkap. Pipeline deteksi berjalan end-to-end sejak 2026-08-08 — pesan masuk lewat webhook keluar sebagai balasan WhatsApp dan baris audit. Status per fitur ada di [[05_Product_Scope_and_Roadmap]]; batasan yang belum bisa diverifikasi ada di [[00_Sprint_1_Completion_Notes]].

---

## Baca Dulu

| Pertanyaan | Dokumen |
| :--- | :--- |
| Apa yang masuk MVP, apa yang tidak? | [[05_Product_Scope_and_Roadmap]] |
| Bagaimana bentuk sistemnya? | [[01_System_Architecture]] |
| Apa yang sudah benar-benar jalan? | [[01_System_Architecture]] §7 · [[00_Sprint_1_Completion_Notes]] |
| Bagaimana data mengalir? | [[02_Data_Pipeline]] |
| Bedanya Knowledge Base dan training? | [[03_Knowledge_Base]] §5 |

---

## 01. Overview & Product

- [[01_Problem_Statement|01. Masalah & Ruang Lingkup]] — akar masalah, kendala E2EE, audiens rentan, domain ancaman.
- [[02_Value_Proposition|02. Value Proposition]] — pilar keunggulan dan matriks komparasi.
- [[03_Pitching_Narrative|03. Naskah Pitching]] — elevator pitch, problem-solution fit, arah B2G (Post-MVP), KPI.
- [[04_How_it_Works|04. Cara Kerja Sistem]] — flowchart utama untuk proposal paper.
- [[05_Product_Scope_and_Roadmap|05. Product Scope & Roadmap]] — **klasifikasi MVP / Post-MVP / Opsional / Deferred + status implementasi.**

## 02. Architecture

- [[01_System_Architecture|01. Arsitektur Sistem]] — arsitektur target, tanggung jawab per komponen, prinsip arsitektur, status implementasi.
- [[02_Data_Pipeline|02. Data Flow & Pipeline]] — alur deteksi, RAG, knowledge ingestion, training.
- [[03_Tech_Stack|03. Tech Stack & Deployment]] — matriks teknologi + status, containerization, keputusan terbuka.
- [[04_ML_Service|04. ML Service (Standalone)]] — batas tanggung jawab, kontrak API, readiness, multi-model.
- [[05_Integrations|05. Integrations]] — WAHA, ML Service, data store, threat intelligence eksternal.
- [[06_Optional_APK_Inspector|06. APK Inspector (Opsional / Future)]] — modul independen di luar MVP.

## 03. Database

- [[01_PostgreSQL_Schema|01. Skema PostgreSQL]] — domain data + status, ERD, DDL, catatan migrasi.
- [[02_VectorDB_Specifications|02. Konfigurasi Qdrant]] — collection, payload, hybrid search, batas peran.

## 04. AI / ML

- [[01_LLM_System_Prompt|01. LLM System Prompt & Few-Shot]] — persona, guardrails, contoh kasus.
- [[02_ML_Control_Center_Overview|02. AI/ML Control Center — Overview]] — struktur dan isi halaman Overview.
- [[03_Knowledge_Base|03. Knowledge Base]] — ingestion, retrieval, dan pemisahan tegas dari training.
- [[04_Datasets_and_Operator_Feedback|04. Dataset & Operator Feedback]] — human-in-the-loop, kurasi, validasi.
- [[05_Training_Jobs|05. Training Jobs]] — operasi asinkron terkontrol, konfigurasi, status job.
- [[06_Model_Evaluation|06. Model Evaluation]] — metrik, dataset evaluasi tetap, gerbang promosi.
- [[07_Model_Registry_and_Deployment|07. Model Registry & Deployment]] — versi, state, promosi eksplisit, rollback.
- [[08_Continuous_Improvement_Loop|08. Continuous Improvement Loop]] — siklus perbaikan terkontrol.

## 05. Audit (Historis)

- [[01_Documentation_Audit_Report|01. Documentation Audit Report]] — **historis**, audit vault versi lama.
- [[02_Architecture_Audit_ML_Decoupling|02. Architecture Audit — ML Decoupling]] — **historis**, analisis saat backend masih kosong.

## 06. Sprint Board

- [[TASKS|Sprint Kanban Board]] — papan task engineering.
- [[00_Sprint_1_Completion_Notes|Catatan Penyelesaian Sprint 1]] — **apa yang benar-benar jadi, apa yang belum bisa diverifikasi, dan kenapa.**
- [[Open_Decisions_Carried_Forward|Keputusan Terbuka yang Dibawa ke Sprint Berikutnya]]

## 07. How to Run

- [[01_Dev_Environtment|01. Development Environment]] — hybrid: infra via compose, app via CLI lokal.
- [[02_Prod_Environtment|02. Production Environment]] — deploy penuh via compose, pairing WAHA, backup, catatan keamanan.

## 08. Dashboard / Control Panel

- [[01_Control_Panel_Overview|01. Control Panel Overview]] — area fungsional, navigasi, aturan frontend.
- [[02_Command_Center|02. Command Center & Live Activity]]
- [[03_Threat_Monitoring|03. Threat Monitoring]]
- [[04_Message_Inspection|04. Message Inspection]]
- [[05_Incident_Management|05. Incident Management]]
- [[06_WhatsApp_Management|06. WhatsApp Management]]
- [[07_Users_and_Risk|07. Users & Risk Management]]
- [[08_Service_Health|08. Service Health]]

## 09. Security

- [[01_Threat_Model_and_Data_Protection|01. Threat Model & Data Protection]] — aset, aktor ancaman, kontrol, isu terbuka.
- [[02_Security_Policies|02. Security Policies]] — kondisi, aksi, urutan evaluasi, auditability.
- [[03_Detection_Rules|03. Detection Rules]] — rules deterministik, pelengkap ML.
- [[04_Alert_Center|04. Alert Center]] — severity, siklus hidup, sumber alert.
- [[05_Audit_Logs|05. Audit Logs]] — tindakan yang diaudit, sifat append-oriented.
- [[06_Platform_Security_Requirements|06. Platform Security Requirements]] — auth, RBAC, upload, rahasia, observability.

---

## Ringkasan Arsitektur

```text
                         JAWARA PLATFORM
                              │
                              ▼
                    ┌───────────────────┐
                    │   Next.js Web UI  │
                    │  Control Panel    │
                    └─────────┬─────────┘
                              │
                              ▼
                    ┌───────────────────┐
                    │   FastAPI Gateway │
                    │      API Layer    │
                    └─────────┬─────────┘
                              │
              ┌───────────────┼────────────────┐
              │               │                │
              ▼               ▼                ▼
        PostgreSQL          Redis            Qdrant
              │               │                │
              └───────────────┼────────────────┘
                              │
                              ▼
                    ┌───────────────────┐
                    │    ML Service     │
                    │    Standalone     │
                    └─────────┬─────────┘
                              │
                              ▼
                    ┌───────────────────┐
                    │   AI / ML Models  │
                    └───────────────────┘

                    WhatsApp Integration
                              │
                              ▼
                            WAHA
```

---

## Konvensi Dokumentasi

- Setiap fitur ditandai scope: **MVP**, **Post-MVP**, **Opsional / Future**, atau **Deferred**.
- Setiap fitur ditandai status implementasi: **Implemented**, **Partial**, atau **Planned**.
- Fitur yang direncanakan tidak pernah ditulis seolah sudah jadi.
- Dokumen historis diberi banner status dan tidak boleh dibaca sebagai arsitektur berlaku.
