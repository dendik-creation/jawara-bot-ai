# Catatan — Build Text Verification Pipeline

Task: [[Build Text Verification Pipeline]] · Indeks: [[00_Sprint_1_Completion_Notes]]

---

## 1. Di mana kodenya berada, dan kenapa bukan di gateway

Task menyebut "embedding client wrapper" dan "retrieval function" tanpa menyebut service-nya. [[04_ML_Service]] §5 menjawabnya: embedding dan similarity search adalah pekerjaan inference-adjacent, jadi akses Qdrant untuk retrieval berada **di belakang ML Service**, dan gateway tidak pernah menghitung atau membandingkan vektor.

Pembagiannya jadi:

| Bagian | Lokasi |
| :--- | :--- |
| Embedding client (provider-agnostic) | `ml-service/app/embeddings/` |
| Retrieval terfilter ke Qdrant | `ml-service/app/rag/qdrant_repo.py` |
| Endpoint `POST /v1/rag-query` | `ml-service/app/api/v1/endpoints/inference.py` |
| Script ingestion `fact_items` | `backend/app/scripts/ingest_knowledge.py` (orkestrasi) → `POST /v1/kb/upsert` (embedding + tulis) |
| Pemanggil dari worker | `backend/app/clients/ml_client.py` |

Ingestion tetap diorkestrasi gateway karena gateway yang memiliki `fact_items` di PostgreSQL — tapi embedding-nya tidak dihitung di sana.

---

## 2. Kontrak retrieval yang benar-benar berjalan

Terverifikasi live terhadap Qdrant nyata:

```text
top_k = 3
score_threshold = 0.80
filter: category = <intent> AND is_active = true
vector: 1536-dim, cosine
```

Nilai-nilai ini datang dari config (`RAG_TOP_K`, `RAG_SCORE_THRESHOLD`, `EMBEDDING_DIM`), bukan literal di call site. Test integrasi `ml-service/tests/test_rag_integration.py` membuktikan filternya benar-benar menyaring: dari tiga point bertopik sama, hanya yang `HEALTH_HOAX` **dan** `is_active=true` yang kembali.

Di bawah threshold, hasilnya `matches: []` + `unverified: true`. Bukan "match terdekat". Ini kriteria penerimaan yang paling mudah dilanggar tanpa sadar dan paling mahal akibatnya: satu match lemah yang lolos akan dipakai LLM untuk menulis jawaban percaya diri tentang fakta yang salah.

---

## 3. Batasan yang harus diketahui: embedder default bersifat leksikal

`EMBEDDING_PROVIDER=hash` (default) memakai `hash-embed-v0` — bag-of-ngram yang di-hash ke 1536 dimensi lalu dinormalisasi L2. Deterministik, tanpa API key, jalan offline.

**Ia bukan model semantik.** Cosine similarity di atasnya mengukur kemiripan *leksikal*.

Pengukuran nyata:

| Pasangan teks | Cosine |
| :--- | :--- |
| Klaim vs klaim nyaris identik | 0.87 (lolos threshold 0.80) |
| Klaim vs parafrase longgar | ~0.59 (tidak lolos) |
| Klaim vs topik tak berhubungan | ~0.00 |

Artinya, dengan embedder default, threshold 0.80 yang terdokumentasi berperilaku **lebih ketat** daripada nanti dengan `text-embedding-3-small`: pesan yang menceritakan ulang klaim dengan kata-kata sendiri akan dijawab "belum terverifikasi", bukan dicocokkan.

Itu mode gagal yang benar (jujur daripada percaya diri dan salah), tapi tetap sebuah keterbatasan.

### Cara menyelesaikannya

```bash
# .env
EMBEDDING_PROVIDER=openai
OPENAI_API_KEY=sk-...
```

Dimensi tetap 1536, jadi collection tidak perlu dibuat ulang. **Kalau pindah ke IndoBERT (768), collection wajib dibuat ulang dan seluruh knowledge base di-embed ulang** — Qdrant tidak bisa mengubah dimensi collection secara in-place ([[02_VectorDB_Specifications]] §5).

---

## 4. Data seed

Knowledge base kosong tidak bisa membuktikan apa-apa, jadi ditambahkan `backend/app/scripts/seed_facts.py` berisi empat fakta dari contoh few-shot di [[01_LLM_System_Prompt]] (kitolod, vaksinasi gratis, bansos palsu, modus APK). Ini **data demo**, bukan kurasi nyata — Knowledge Base operator masih Planned ([[03_Knowledge_Base]]).

```bash
python -m app.scripts.seed_facts        # isi fact_sources + fact_items
python -m app.scripts.ingest_knowledge  # embed ke Qdrant lewat ML Service
```

---

## 5. Yang ditunda

Fallback ke Postgres full-text saat Qdrant mati **tidak** dikerjakan; task menandainya "defer unless time allows". Perilaku sekarang: `/v1/rag-query` menjawab `retrieval_unavailable` (retryable), worker menandai degradasi, dan balasan tetap dibuat tanpa konteks knowledge.

---

**Related:** [[02_VectorDB_Specifications]] · [[04_ML_Service]] · [[03_Knowledge_Base]] · [[Generate_LLM_Responses]]
