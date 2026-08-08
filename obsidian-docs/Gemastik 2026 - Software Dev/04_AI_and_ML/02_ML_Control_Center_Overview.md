# AI / ML Control Center — Overview

> **Scope:** MVP · **Status:** Planned

Bagian AI/ML pada Control Panel adalah tempat operator melihat dan mengendalikan sisi kecerdasan JAWARA: model apa yang sedang melayani produksi, pengetahuan apa yang tersedia, dataset apa yang dipakai, dan apa yang sedang dilatih.

---

## 1. Struktur

```text
AI / ML
│
├── Overview
├── Knowledge Base
├── Datasets
├── Training Jobs
├── Models
└── Evaluation
```

| Sub-bagian | Dokumen |
| :--- | :--- |
| Overview | dokumen ini |
| Knowledge Base | [[03_Knowledge_Base]] |
| Datasets | [[04_Datasets_and_Operator_Feedback]] |
| Training Jobs | [[05_Training_Jobs]] |
| Models | [[07_Model_Registry_and_Deployment]] |
| Evaluation | [[06_Model_Evaluation]] |

---

## 2. Isi Halaman Overview

| Blok | Isi |
| :--- | :--- |
| Production model | Model yang sedang melayani |
| Model version | Versi model produksi |
| Model status | Status di registry |
| Inference availability | Apakah ML Service melayani inference sekarang |
| Recent inference volume | Volume inference terkini |
| Basic inference latency | Latensi inference dasar |
| Recent training jobs | Job terbaru dan statusnya |
| Candidate model | Kandidat yang menunggu validasi |
| Evaluation status | Hasil evaluasi terakhir |

Halaman ini **tidak** berkembang menjadi Infrastructure Analytics. Tren resource jangka panjang adalah Deferred ([[05_Product_Scope_and_Roadmap]] §6). Latensi yang ditampilkan di sini adalah angka operasional terkini, bukan time-series BI.

---

## 3. Dua Jalur Perbaikan yang Terpisah

Halaman Overview harus membuat perbedaan ini terlihat, karena inilah sumber kesalahpahaman paling umum:

```text
Knowledge Base                     Model Training
     │                                   │
     ▼                                   ▼
Parameter model TIDAK berubah      Parameter model BERUBAH
Efek langsung pada retrieval       Efek setelah promosi ke produksi
Dikelola operator kapan saja       Butuh dataset + evaluasi + validasi
```

Rincian: [[03_Knowledge_Base]] §5.

---

## 4. Batas Tanggung Jawab

- FastAPI Gateway **mengorkestrasi** operasi AI/ML: menerima permintaan dari Control Panel, memvalidasi, menyimpan metadata, mengantre pekerjaan.
- ML Service **mengeksekusi** pekerjaan ML: embedding, inference, training, evaluasi.
- Control Panel tidak pernah memanggil ML Service langsung.

Lihat [[04_ML_Service]].

---

**Related:** [[01_Control_Panel_Overview]] · [[04_ML_Service]] · [[03_Knowledge_Base]] · [[05_Training_Jobs]] · [[08_Continuous_Improvement_Loop]]
