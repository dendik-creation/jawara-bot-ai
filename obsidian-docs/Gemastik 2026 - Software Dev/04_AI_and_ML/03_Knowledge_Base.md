# Knowledge Base

> **Scope:** MVP (fitur besar) · **Status:** Partial — jalur `fact_items` → ML Service `/v1/kb/upsert` → Qdrant sudah jalan (manual lewat Control Panel, CSV import, dan CLI `app.scripts.ingest_knowledge`), dan sejak §8 ada ingestion otomatis terjadwal dari sumber cek fakta eksternal. Yang belum ada: pipeline upload dokumen mentah (parse/chunk) di §3.

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

## 8. Ingestion Otomatis dari Sumber Cek Fakta

Knowledge base tidak lagi hanya bisa diisi manual. Celery Beat menarik cek
fakta baru dari organisasi cek fakta eksternal secara berkala, lalu
mendorongnya lewat **jalur sinkronisasi yang sudah ada** — bukan jalur kedua.

```text
Celery Beat  (FACT_INGESTION_INTERVAL_MINUTES)
    ↓
task app.worker.tasks.ingest_fact_checks   (queue jawara.ingestion)
    ↓
Source Adapter        ← app/ingestion/ (satu modul per sumber)
    ↓
fact_items            ← PostgreSQL tetap sumber kebenaran
    ↓
services.knowledge.sync_fact_items  ← jalur sync yang sudah dipakai tombol "Sync"
    ↓
ML Service /v1/kb/upsert → Qdrant → RAG retrieval
```

### 8.1 Batas adapter

`app/ingestion/base.py` mendefinisikan satu antarmuka dengan dua panggilan:

| Panggilan | Biaya | Isi |
| :--- | :--- | :--- |
| `list_candidates()` | 1 request per run | entri feed/indeks: `external_id`, url, judul |
| `fetch_record(candidate)` | 1 request per artikel | artikel penuh, sudah dinormalisasi |

Pipeline membuang kandidat yang sudah tersimpan **di antara** dua panggilan
itu — itulah yang membuat run terjadwal yang tidak menemukan apa-apa hanya
berharga satu request HTTP. Semua urusan khas sumber (URL feed, kuirk HTML,
kosakata verdict) tinggal di balik batas ini; `services/fact_ingestion.py`
tidak tahu TurnBackHoax itu apa. Menambah CekFakta/Kompas/ANTARA/Tirto/AFP
nanti = satu modul baru + satu baris di `app/ingestion/registry.py`.

### 8.2 Sumber fase ini: TurnBackHoax / MAFINDO

Hasil pemeriksaan sumber (Agustus 2026):

- `robots.txt` = `Disallow:` (tidak ada larangan), tetapi crawl tetap dibatasi
  satu request feed per run + satu request per artikel yang benar-benar baru,
  dengan jeda `FACT_INGESTION_REQUEST_DELAY_SECONDS` antar request.
- Tidak ada API publik. Situs bukan WordPress lagi (`/wp-json` 404), tapi
  `/feed` menyajikan RSS 2.0 — dipilih daripada scraping indeks.
- Feed hanya membawa `title`, `link`, `guid`, `description`; **tidak ada**
  `pubDate`, kategori, atau paginasi (selalu 10 artikel terbaru).
- Halaman artikel membawa JSON-LD `ClaimReview` (verdict + tanggal) dan
  section `article-origin` / `article-explanation` / `article-factcheck`.

Karena feed hanya menyimpan 10 artikel, interval polling harus lebih rapat
daripada laju terbit sumber — default 60 menit untuk ±5-15 artikel/hari.

Pemetaan kosakata: `Salah`/`Penipuan`/`Fitnah`/`Disinformasi` → `HOAX`,
`Menyesatkan`/`Sebagian Benar`/`Parodi` → `MISLEADING`, `Benar` → `FACT`,
label tak dikenal → `UNVERIFIED` (tidak ditebak).

### 8.3 Deduplikasi dan idempotensi

Tiga kunci identitas, berurutan: `external_id` dari sumber → canonical URL
(query/fragment dibuang) → `content_fingerprint` (SHA-256 judul + klaim +
penjelasan + verdict). Jaminannya ada di database — unique index parsial
`(source_id, external_id)` — bukan pada pengecekan aplikasi, sehingga dua run
yang tumpang tindih pun tidak bisa menghasilkan duplikat.

Fingerprint sekaligus jadi detektor perubahan: `external_id` sama +
fingerprint beda = redaksi mengedit artikel → **UPDATE**, dan `synced_at`
dikosongkan supaya baris itu kembali antre untuk di-embed ulang.

Artikel yang sudah tersimpan dibaca ulang paling sering
`FACT_INGESTION_REFRESH_AFTER_HOURS` sekali dan hanya selama umurnya di bawah
`FACT_INGESTION_REFRESH_WINDOW_DAYS`, supaya "menangkap ralat" tidak berubah
jadi "mengunduh ulang arsip tiap jam".

### 8.4 Provenance dan kesegaran

Tiga stempel waktu yang sengaja dibedakan:

| Kolom | Artinya |
| :--- | :--- |
| `published_at` | kapan **sumber** menerbitkan cek fakta |
| `updated_at` | kapan baris ini terakhir berubah (trigger lama) |
| `ingested_at` | kapan kami menariknya |

Waktu ingestion tidak pernah ditulis ke `published_at` — ini prasyarat fase
temporal relevance nanti. `source_name`, `source_url`, `external_id`, dan
`published_at` ikut ke payload Qdrant, jadi LLM tetap bisa menyebut tautan
sumber aslinya lewat mekanisme evidence yang sudah ada.

### 8.5 Kegagalan dan observabilitas

Kegagalan per item tetap per item: satu artikel rusak dihitung dan dilewati,
sembilan lainnya tetap masuk. Hanya sumber yang tidak bisa dijangkau yang
menghentikan run — dan run-nya tetap ditutup dengan status + alasan.

Setiap run menulis satu baris `fact_ingestion_runs`
(`RUNNING`/`SUCCESS`/`PARTIAL`/`FAILED`, `fetched`, `created`, `updated`,
`duplicates`, `failed`, `synced`, `sync_failed`, `error`, `details`), dan
`fact_ingestion_cursors` menyimpan `last_external_id`, `last_published_at`,
`last_success_at`. Semua terbaca lewat:

- `GET /api/v1/knowledge/ingestion/status` — per sumber: run terakhir, sukses terakhir
- `GET /api/v1/knowledge/ingestion/runs` — riwayat run
- `POST /api/v1/knowledge/ingestion/run` — trigger manual (masuk audit log)
- blok `fact_ingestion` di `GET /api/v1/ai-ml/overview`

Retry: hanya kegagalan **sumber** yang retryable (timeout/429/5xx) yang
membuat task minta retry ke Celery; artikel yang malformed akan gagal sama
persis pada percobaan ulang, jadi tick terjadwal berikutnya sudah cukup.

### 8.6 Konfigurasi

`FACT_INGESTION_ENABLED`, `FACT_INGESTION_SOURCES`,
`FACT_INGESTION_INTERVAL_MINUTES`, `FACT_INGESTION_MAX_ITEMS`,
`FACT_INGESTION_REQUEST_DELAY_SECONDS`, `FACT_INGESTION_REFRESH_AFTER_HOURS`,
`FACT_INGESTION_REFRESH_WINDOW_DAYS`, `FACT_INGESTION_USER_AGENT`,
`FACT_INGESTION_AUTO_SYNC`, `TURNBACKHOAX_FEED_URL`. Tidak ada interval yang
di-hardcode; jadwal Beat dibangun dari konfigurasi saat startup, jadi
mengubahnya = restart container `celery-beat`, bukan ubah kode.

> **Catatan operasional:** hanya boleh ada **satu** proses `celery-beat`. Dua
> scheduler berarti tiap tick digandakan dan sumber dipoll dua kali lebih
> sering daripada yang dijanjikan.

## 9. Kualitas Retrieval: Ekstraksi Klaim dan Re-ranking

Ingestion (§8) menjawab "apakah isi knowledge base masih baru". Bagian ini
menjawab dua pertanyaan berikutnya: **apakah pencarian menemukannya**, dan
**mana yang dipilih** kalau yang ketemu lebih dari satu.

```text
pesan WhatsApp mentah
    ↓
/v1/extract-claim        ← kanonikalisasi jadi satu kalimat klaim
    ↓
/v1/rag-query
    ├── Qdrant search (threshold + filter kategori — kontrak lama, tak berubah)
    ├── overfetch top_k × 3
    └── re-ranking: similarity × reliability × recency  → potong ke top_k
    ↓
/v1/generate
```

### 9.1 Ekstraksi klaim

Pesan yang diteruskan bukan klaim: ia klaim yang dibungkus salam, emoji,
"copas dari grup sebelah", nomor HP, tautan, dan "TOLONG SEBARKAN!!!".
Knowledge base menyimpan pasangan `title + claim_text` yang sudah dikurasi.
Dua teks itu bisa membicarakan hoaks yang sama tapi ter-embed berjauhan —
itulah kenapa KB yang **berisi** jawabannya bisa mengembalikan nol hasil.

Dua ekstraktor, berurutan:

| Ekstraktor | Kapan dipakai |
| :--- | :--- |
| LLM (`/v1/extract-claim`) | provider LLM benar-benar terkonfigurasi (`auto`) atau dipaksa (`llm`) |
| Heuristik deterministik | provider offline, LLM gagal/timeout, atau output ditolak validasi |

Heuristik **bukan stub**: itu jalur yang jalan di CI, di demo offline, dan
setiap kali vendor bermasalah. Ia membuang emoji, salam, ajakan menyebar,
tautan, dan nomor telepon, lalu mengambil kalimat-kalimat awal.

Pengukuran nyata di stack ini (embedder `hash`, KB berisi 21 fakta):

| Query | Similarity terhadap artikel yang benar |
| :--- | :--- |
| pesan forward mentah (394 karakter) | 0.552 |
| hasil ekstraksi heuristik (190 karakter) | 0.615 |

Pesan pendek (< `CLAIM_EXTRACTION_MIN_INPUT_CHARS`, default 180) dilewatkan
apa adanya — "apakah benar vaksin mengandung chip?" **sudah** klaim, dan
menukarnya dengan satu panggilan LLM di dalam budget <3 detik itu pemborosan.

Keamanan: prompt ekstraksi justru bertugas mengembalikan teks pengguna, jadi
ia target injeksi yang lebih lunak daripada prompt persona. Mitigasinya dua —
blok pesan ditandai eksplisit sebagai DATA dengan larangan mengikuti instruksi
di dalamnya, dan output divalidasi (panjang, satu baris, bukan markdown).
Output yang ditolak jatuh ke heuristik; tidak pernah lolos ke embedder.

### 9.2 Skor reliabilitas sumber

`fact_sources.is_trusted` itu boolean, sedangkan ranking butuh gradien.
`reliability_score` ∈ [0,1] (default 0.80, migrasi 016) adalah gradien itu.
Ia **tidak pernah memfilter** — skor rendah menurunkan peringkat fakta sebuah
sumber, bukan menyembunyikannya.

Skor adalah penilaian manusia tentang penerbit, diubah lewat
`PATCH /api/v1/knowledge/sources/{id}` dan tercatat di `audit_log`.
Menurunkannya otomatis dari statistik hasil adalah fase lain — sengaja tidak
dipalsukan sekarang. Adapter ingestion hanya **menyemai** skor saat sumber
pertama kali dibuat (TurnBackHoax = 0.95, MAFINDO signatory IFCN); sesudah itu
skor milik operator dan tidak ditimpa redeploy.

> **Penting:** skor didenormalisasi ke dalam payload Qdrant tiap fakta, karena
> ml-service tidak punya database untuk join. Karena itu route PATCH
> me-*resync* fakta sumber tersebut secara default, dan mengembalikan
> `stale_in_qdrant` — jumlah fakta yang masih memegang skor lama. Perubahan
> skor tanpa resync tidak mengubah apa pun di retrieval.

### 9.3 Re-ranking

```text
final = similarity × reliability_factor × recency_factor

reliability_factor = 1 − w_rel    × (1 − reliability)
recency_factor     = 1 − w_recent × (1 − 0.5 ^ (umur_hari / half_life))
```

Sifat yang dijaga:

- Kedua faktor berada di `[1 − w, 1]`, jadi `w = 0` mematikan sinyal itu
  **persis**, dan re-ranking hanya bisa **menurunkan** skor — tidak pernah
  mengarang keyakinan yang tidak ditemukan embedder.
- **Keanggotaan tidak berubah**, hanya urutan dan pemotongan ke `top_k`.
  Threshold similarity tetap milik [[02_VectorDB_Specifications]]; membuang
  match karena skor hasil pembobotan kita sendiri turun akan diam-diam
  mengubah kontrak yang ditulis di dokumen lain.
- `score` yang masuk audit row tetap cosine similarity mentah. Angka turunan
  ikut sebagai `rerank_score`, `reliability`, `age_days`.
- Retrieval **overfetch** `top_k × 3` lalu dipotong; mengurutkan ulang tepat
  `top_k` kandidat tidak akan pernah bisa mempromosikan match keempat yang
  tepercaya di atas match ketiga yang rapuh.
- Metadata yang hilang bersikap netral, bukan curiga: fakta tanpa skor (semua
  yang ada sebelum migrasi 016) dan tanpa tanggal tidak kena penalti.
- Peluruhan pakai half-life, bukan tanggal kedaluwarsa — debunk lama atas
  hoaks yang berulang harus tetap bisa ditemukan.

Bukti dari stack yang jalan (satu fakta tiruan bersumber lemah dan usang
ditambahkan sementara, lalu dihapus):

```text
RAW SIMILARITY
  0.8243  [TEMP] sumber lemah (reliability 0.10, umur 400 hari)
  0.7285  [PENIPUAN] artikel MAFINDO yang benar
RE-RANKED
  0.7285 → 0.7138  [PENIPUAN] artikel MAFINDO   (rel 0.95, umur 0.3 hari)
  0.8243 → 0.4239  [TEMP] sumber lemah
```

### 9.4 Konfigurasi

`RAG_CLAIM_EXTRACTION_ENABLED` (gateway), `CLAIM_EXTRACTION_PROVIDER`,
`CLAIM_EXTRACTION_MIN_INPUT_CHARS`, `RAG_RERANK_ENABLED`,
`RAG_RELIABILITY_WEIGHT`, `RAG_RECENCY_WEIGHT`, `RAG_RECENCY_HALF_LIFE_DAYS`.
`{"rerank": false}` di payload `rag-query` mematikan re-ranking per request,
untuk memeriksa retrieval mentah tanpa redeploy.

---

**Related:** [[02_ML_Control_Center_Overview]] · [[02_VectorDB_Specifications]] · [[04_Datasets_and_Operator_Feedback]] · [[02_Data_Pipeline]] · [[06_Platform_Security_Requirements]]
