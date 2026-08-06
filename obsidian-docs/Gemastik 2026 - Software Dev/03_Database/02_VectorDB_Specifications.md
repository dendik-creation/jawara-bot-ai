# Vector Database Schema & Config (Qdrant)

Knowledge base menyimpan *vector embedding* dari dokumen klaim dan fakta terverifikasi di dalam **Vector Database (Qdrant)** untuk mendukung proses **Semantic Search RAG**.

---

## 1. Collection Configuration

| Property | Configuration Value | Keterangan / Justifikasi |
| :--- | :--- | :--- |
| **Collection Name** | `fact_knowledge_base` | Koleksi utama penyimpanan embedding fakta. |
| **Distance Metric** | `Cosine` | Mengukur sudut kemiripan semantik antar vektor teks. |
| **Vector Dimension** | `1536` | Disesuaikan dengan model `text-embedding-3-small` OpenAI (atau `768` untuk `IndoBERT`). |
| **HNSW Index M** | `16` | Jumlah koneksi max per node pada grafik HNSW. |
| **HNSW Index ef_construct** | `100` | Kedalaman pencarian grafik saat pembuatan indeks. |
| **On-Disk Payload** | `true` | Menyimpan payload data di disk untuk menghemat RAM. |

---

## 2. Complete Payload Schema (JSON)

```json
{
  "id": "c39a04f2-5b9e-4a6c-9407-1d82136e0510",
  "vector": [
    0.0124,
    -0.0451,
    0.0892,
    "..."
  ],
  "payload": {
    "fact_item_id": "c39a04f2-5b9e-4a6c-9407-1d82136e0510",
    "category": "HEALTH_HOAX",
    "title": "Klaim Daun Kitolod Menyembuhkan Katarak Tanpa Operasi",
    "claim_text": "Beredar pesan bahwa air rebusan atau perasan daun kitolod dapat menyembuhkan katarak dan membersihkan mata tanpa perlu operasi.",
    "fact_explanation": "Kementerian Kesehatan RI dan Perhimpunan Dokter Spesialis Mata Indonesia (PERDAMI) menegaskan bahwa penggunaan air ramuan daun liar pada mata berisiko tinggi menyebabkan iritasi, infeksi bakteri, hingga kebutaan permanen. Katarak hanya dapat ditangani melalui tindakan medis katarak oleh dokter spesialis.",
    "verdict": "HOAX",
    "source_name": "Kementerian Kesehatan RI & TurnBackHoax",
    "source_url": "https://turnbackhoax.id/2026/01/10/hoax-kitolod-katarak/",
    "is_active": true,
    "updated_at": "2026-03-15T10:00:00Z"
  }
}
```

---

## 3. Strategi Hybrid Search & Payload Filtering

Untuk memastikan pencarian yang presisi, RAG JAWARA (Jaringan Asisten WhatsApp Anti-Rekayasa & Ancaman) menerapkan **Hybrid Search** (pencarian vektor dikombinasikan dengan penyaringan metadata):

```python
# Contoh Query Retrieval Qdrant di Python (LlamaIndex / Qdrant Client)
from qdrant_client import QdrantClient
from qdrant_client.http import models

client = QdrantClient(host="localhost", port=6333)

# Lakukan similarity search dengan filter kategori
search_result = client.search(
    collection_name="fact_knowledge_base",
    query_vector=user_embedding_vector,
    query_filter=models.Filter(
        must=[
            models.FieldCondition(
                key="category",
                match=models.MatchValue(value="HEALTH_HOAX")
            ),
            models.FieldCondition(
                key="is_active",
                match=models.MatchValue(value=True)
            )
        ]
    ),
    limit=3, # Top-K=3
    score_threshold=0.80 # Similarity threshold minimum 80%
)
```

---

## 4. RAG Retrieval Pipeline Diagram

```mermaid
flowchart LR
    Q[User Input Text] --> E[Embedding Model]
    E --> V[Vector Embedding 1536-dim]
    V --> QDB[(Qdrant Vector DB)]

    QDB -->|Cos Similarity >= 0.80| TOPK[Top-K Fact Contexts]
    TOPK --> PROMPT[System Prompt Assembler]
    PROMPT --> LLM[LLM Generator]
    LLM --> OUT[WhatsApp Markdown Output]
```

---

**Related:** [[02_Data_Pipeline]] · [[01_PostgreSQL_Schema]] · [[01_LLM_System_Prompt]]