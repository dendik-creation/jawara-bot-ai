# Knowledge Base

> **Scope:** MVP (fitur besar) · **Status:** Planned — collection Qdrant `fact_knowledge_base` sudah dibuat oleh `backend/app/vector/qdrant_setup.py`, tapi pipeline ingestion belum ada.

Knowledge Base memungkinkan operator memberi pengetahuan kepada JAWARA **tanpa melatih ulang model**.

---

## 1. Pernyataan Utama

> **Meng-upload knowledge tidak me-retrain model ML.** Parameter model tidak berubah. Yang bertambah adalah materi yang bisa diambil (retrieved) saat inference.

Ini bukan detail teknis kecil — ini menentukan siapa boleh mengubah apa, seberapa cepat efeknya terasa, dan risiko apa yang menyertainya.

---

## 2. Sumber Knowledge

| Format | Contoh isi |
| :--- | :--- |
| PDF, DOCX, TXT, CSV | Dokumen apa pun yang bisa di-parse |
| Security guidelines | Panduan keamanan internal |
| Threat intelligence | Ringkasan modus dan indicator terbaru |
| Dokumentasi penipuan | Katalog modus scam |
| Dokumentasi phishing | Pola kampanye phishing |
| SOP | Prosedur penanganan operator |
| FAQ | Pertanyaan berulang |
| Contoh terkurasi | Kasus nyata yang sudah diverifikasi |
| Data keamanan terstruktur | Daftar domain, indicator, klasifikasi |

---

## 3. Pipeline Ingestion

```text
Dashboard
    ↓
FastAPI
    ↓
Document Ingestion
    ↓
Parsing
    ↓
Chunking
    ↓
Embedding
    ↓
Qdrant
```

Versi lengkap dengan gerbang validasi:

```text
Admin Upload
    ↓
FastAPI
    ↓
File Validation      ← tipe, ukuran, nama file
    ↓
Document Parsing
    ↓
Chunking
    ↓
Embedding Generation ← dijalankan ML Service
    ↓
Qdrant
    ↓
Knowledge Available for Retrieval
```

Pembagian kerja:

| Tahap | Pemilik |
| :--- | :--- |
| Upload, validasi, metadata, status | FastAPI Gateway (metadata di PostgreSQL) |
| Parsing & chunking | Gateway/worker atau ML Service, tergantung berat prosesnya (**belum diputuskan**) |
| Embedding generation | ML Service |
| Penyimpanan vektor | Qdrant |

---

## 4. Yang Didukung Knowledge Base

- Retrieval
- Semantic search
- RAG
- Contextual security intelligence

---

## 5. Knowledge vs Model Training

### Knowledge Base

```text
Document
    ↓
Parse
    ↓
Chunk
    ↓
Embedding
    ↓
Qdrant
    ↓
Retrieve relevant knowledge
    ↓
AI inference
```

**Parameter model tidak berubah.**

### Model Training

```text
Dataset
    ↓
Training Job
    ↓
ML Service
    ↓
Training
    ↓
Evaluation
    ↓
Model Artifact
    ↓
Model Registry
    ↓
Production
```

**Parameter model berubah.**

Lihat [[05_Training_Jobs]] dan [[07_Model_Registry_and_Deployment]].

---

## 6. Manajemen di Control Panel

Kapabilitas layar Knowledge Base:

- Daftar dokumen: nama, tipe, ukuran, pengunggah, waktu, status
- Status ingestion: `UPLOADED` → `VALIDATED` → `PARSED` → `INDEXED` → (`FAILED`)
- Jumlah chunk dan koleksi tujuan
- Pencarian dan pratinjau chunk
- Hapus / non-aktifkan dokumen (harus ikut menghapus vektornya, bukan hanya metadata)
- Re-index setelah pergantian model embedding

---

## 7. Risiko dan Kontrol

| Risiko | Kontrol |
| :--- | :--- |
| Dokumen berbahaya (parser exploit) | Validasi tipe/ukuran, parsing terisolasi ([[06_Platform_Security_Requirements]] §3) |
| Knowledge poisoning | Status review; dokumen baru tidak otomatis tepercaya |
| Prompt injection lewat isi dokumen | Konten retrieval diperlakukan sebagai data, bukan instruksi |
| Ganti model embedding | Dimensi vektor adalah config, bukan konstanta. Qdrant tidak bisa mengubah dimensi collection in-place — ganti model berarti buat ulang collection dan embed ulang seluruh knowledge base ([[02_VectorDB_Specifications]]) |
| Hapus dokumen tapi vektor tertinggal | Penghapusan harus transaksional antara metadata PostgreSQL dan payload Qdrant |

---

**Related:** [[02_ML_Control_Center_Overview]] · [[02_VectorDB_Specifications]] · [[04_Datasets_and_Operator_Feedback]] · [[02_Data_Pipeline]] · [[06_Platform_Security_Requirements]]
