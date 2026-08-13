# How to Train the Threat Classifier — and Verify ≥80% Accuracy

Model: TF-IDF (word + char n-gram) + `LogisticRegression`, `ml-service/app/models/classifier.py`. Enam label: `HEALTH_HOAX`, `FINANCIAL_FRAUD`, `GENERAL_NEWS`, `PHISHING_LINK`, `FILE_APK`, `NOT_A_THREAT`. Tanpa model `PRODUCTION`, pipeline jalan normal lewat Detection Rules saja — melatih model tidak wajib untuk bot berfungsi, ini murni untuk mengaktifkan sinyal ML tambahan.

**Yang menentukan akurasi di sini cuma satu hal: kualitas dan jumlah data berlabel.** Training job menerima field `epochs`/`learning_rate`/`batch_size`/`validation_split` di API-nya (§Appendix), tapi `classifier.train()` saat ini **tidak memakainya sama sekali** — `LogisticRegression` di-fit langsung (`max_iter=1000`, `class_weight="balanced"` tetap). Jangan berharap menaikkan akurasi lewat hyperparameter; satu-satunya tuas nyata adalah data.

> [!warning] Knowledge Base ≠ data training classifier
> Menu **AI / ML → Knowledge Base** (`/knowledge-base`, `backend/app/services/knowledge.py`) adalah tabel `fact_items` terpisah total — dipakai untuk retrieval RAG lewat Qdrant, bukan input `datasets`/`training_jobs` di dokumen ini. Fitur **Import CSV** di halaman itu (tombol di `KnowledgeBaseList`) meng-import fact item (klaim + penjelasan + verdict + sumber), bukan sample training. Tidak ada endpoint atau tombol CSV import untuk sample dataset classifier — baik lewat API maupun UI, sample dataset cuma bisa ditambah satu per satu (§1, §1a). Penempatan CSV import di Knowledge Base **sudah benar** kalau itu memang untuk fact item; kalau tujuannya menambah sample training massal, itu belum ada di codebase sama sekali.

---

## 0. Prasyarat

- Stack jalan (`docker compose ps` — semua `healthy`), minimal `api-gateway`, `celery-worker`, `ml-service`, `postgres`.
- Minimal satu akun operator ([[01_Dev_Environtment]] §4 / [[02_Prod_Environtment]] §4b) — semua endpoint di bawah butuh sesi operator.
- Dua dataset **terpisah**, VALIDATED, tanpa overlap: satu untuk **training**, satu untuk **evaluasi** (held-out — model tidak pernah melihatnya saat training). Akurasi yang dihitung dari dataset yang sama dipakai training itu bohong — model menghafal, bukan belajar. Ini alasan `model_evaluations.dataset_id` sengaja independen dari `training_jobs.dataset_id` di skema ([[06_Model_Evaluation]]).

Jalan cepat (data sintetis, buat coba mekanismenya jalan — **bukan** buat lulus target 80% yang berarti):

```bash
docker exec jawara-gateway python -m app.scripts.seed_dataset_samples
```

Buat `core-detection-train` (240 sample) + `core-detection-eval` (60 sample), keduanya langsung VALIDATED. Lompat ke §3.

---

## 1. Siapkan Dataset

Lewat Control Panel (`/datasets`) atau API langsung. Contoh API — buat dataset training:

```bash
API=http://127.0.0.1:8000
TOKEN="<bearer token dari POST /api/v1/auth/login>"

curl -s -X POST $API/api/v1/datasets \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"name":"my-train-v1","version":1,"source":"CURATED","description":"training set asli"}'
# -> {"id": "<dataset_id>", "status": "DRAFT", ...}
```

Ulangi untuk dataset eval (`my-eval-v1`). Catat kedua `id`-nya.

Tambah sample satu per satu (`label` salah satu dari 6 di atas — persis, huruf besar semua, typo tidak divalidasi jadi salah label lolos tanpa peringatan):

```bash
curl -s -X POST $API/api/v1/datasets/<dataset_id>/samples \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"text":"Selamat anda menang hadiah 50 juta, transfer biaya admin dulu","label":"FINANCIAL_FRAUD"}'
```

### 1a. Lewat Control Panel (UI), bukan curl

Semua langkah §1–§5 punya padanan UI di **AI / ML** (`frontend/components/layout/navigation.ts`), diverifikasi cocok dengan endpoint di atas:

- **Datasets** (`/datasets`) — tombol **Buat Dataset** (nama/versi/sumber/deskripsi), buka dataset → **Tambah sample manual** (teks + label, satu-satu, sama seperti curl §1 — tidak ada bulk/CSV di sini) → **Validasi**.
- **Training Jobs** (`/training-jobs`) — tombol **Buat Job**: dropdown dataset hanya menampilkan yang `VALIDATED` (mengunci aturan §2 di level form), field base model bebas teks, epochs/learning-rate/batch-size/validation-split ada di form tapi diabaikan backend (sama seperti dicatat di atas).
- **Evaluation** (`/evaluation`) — tombol **Buat Evaluasi**: dropdown training job hanya `COMPLETED`, dropdown dataset uji hanya `VALIDATED` — mencocokkan §3.
- **Models** (`/models`) — buka model version `CANDIDATE` → **Validasi**, lalu `VALIDATED` → **Promosikan ke Production** (§5). Versi `ARCHIVED` punya tombol **Rollback (promosikan kembali)** — ini jalur rollback §5 tanpa perlu curl.

### Berapa banyak, seberapa seimbang

- Minimal **puluhan sample per label** untuk mulai berarti secara statistik; makin banyak makin baik, terutama untuk label yang gampang tertukar (mis. `PHISHING_LINK` vs `FINANCIAL_FRAUD` — sama-sama sering menyebut "klik"/"transfer").
- Jangan biarkan satu label mendominasi jauh. `class_weight="balanced"` mengoreksi skew saat fit, tapi tidak bisa mengarang sinyal dari label yang cuma punya 3 contoh sementara yang lain punya 200.
- **Variasi kalimat asli**, bukan satu kalimat di-copy-paste dengan kata diganti sedikit. Data templated (seperti `seed_dataset_samples.py`) gampang memisah sempurna dan akurasi eval-nya **menggembung tidak realistis** — TF-IDF menangkap pola template, bukan makna. Kalau sumbernya real (pesan asli, laporan operator lewat `/threats` → `FALSE_POSITIVE`/`CONFIRM` feedback), akurasi yang keluar baru bisa dipercaya.
- Data eval **tidak boleh** parafrase/variasi dekat dari data train — itu bocor (leakage), bukan pengukuran generalisasi.

### Validasi dataset

Setelah sample cukup, jalankan `VALIDATE` (mengunci dataset — tidak bisa tambah/hapus sample lagi setelah ini):

```bash
curl -s -X PATCH $API/api/v1/datasets/<dataset_id> \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"action":"VALIDATE"}'
```

Dua cek otomatis, mekanis saja (`app/services/datasets.py`): **tidak ada teks duplikat persis**, dan **tidak ada pola nomor telepon mentah** (`08xx.../+62 8xx...` — pelanggaran privasi). Status jadi `REJECTED` (dengan `validation_notes` berisi alasan) kalau gagal, `VALIDATED` kalau lolos. **Tidak ada cek label benar/salah atau keseimbangan kelas** — itu tanggung jawab manusia, bukan sistem. Ulangi untuk dataset eval.

---

## 2. Training Job

```bash
curl -s -X POST $API/api/v1/training-jobs \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"dataset_id":"<train_dataset_id>","base_model":"tfidf-logreg"}'
# -> {"id": "<job_id>", "status": "QUEUED", ...}
```

`dataset_id` **wajib** berstatus `VALIDATED` (§1), kalau tidak request ditolak. `base_model` bebas string apa saja — dicatat, tidak dibaca kode (satu-satunya algoritma yang ada sekarang adalah TF-IDF + LogisticRegression, apa pun nilainya). Field `epochs`/`learning_rate`/`batch_size`/`validation_split` boleh diisi tapi diabaikan (lihat catatan di atas).

Pantau sampai `COMPLETED`:

```bash
watch -n 2 "curl -s $API/api/v1/training-jobs/<job_id> -H 'Authorization: Bearer $TOKEN' | jq '.status, .metrics, .generated_model_version'"
```

`QUEUED → RUNNING → COMPLETED` (atau `FAILED`, dengan `error_message` — genuinely gagal, bukan hasil dipalsukan). Cepat untuk TF-IDF+LogisticRegression (detik, bukan menit) kecuali dataset sangat besar.

> [!note] `EVALUATING` di enum status tidak pernah dipakai
> Skema (`training_job_status_enum`) dan filter status di UI Training Jobs mencantumkan `EVALUATING`, tapi `backend/app/services/training_jobs.py` cuma pernah menulis `RUNNING → COMPLETED`/`FAILED` — tidak ada transisi ke `EVALUATING` di mana pun. Jangan tunggu status itu muncul saat polling.

`metrics.train_metrics.accuracy` yang muncul di sini **BUKAN** ukuran yang dipakai untuk target 80% — itu skor model terhadap data yang baru saja dipakai melatihnya sendiri, selalu optimis (biasanya mendekati 1.0). Abaikan untuk keputusan promosi. Yang dipakai adalah §3.

Catat `generated_model_version` (`clf-xxxxxxxxxxxx`) — dipakai di langkah berikutnya.

---

## 3. Model Evaluation — ini angka yang dipakai

```bash
curl -s -X POST $API/api/v1/model-evaluations \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"training_job_id":"<job_id>","dataset_id":"<eval_dataset_id>"}'
# -> {"id": "<evaluation_id>", "status": "QUEUED", ...}
```

`dataset_id` di sini **harus** dataset eval yang terpisah dari training (§0) — sistem tidak memaksa beda dataset secara teknis, tapi memakai dataset training yang sama membuat angkanya tidak berarti.

Pantau sampai `COMPLETED`:

```bash
curl -s $API/api/v1/model-evaluations/<evaluation_id> -H "Authorization: Bearer $TOKEN" | jq '.status, .metrics'
```

Bentuk `metrics`:

```json
{
  "accuracy": 0.83,
  "sample_count": 60,
  "macro_avg": {"precision": 0.81, "recall": 0.80, "f1-score": 0.80, "support": 60.0},
  "weighted_avg": {"precision": 0.84, "recall": 0.83, "f1-score": 0.83, "support": 60.0},
  "per_class": {
    "HEALTH_HOAX": {"precision": 0.90, "recall": 1.00, "f1-score": 0.95, "support": 10.0},
    "FINANCIAL_FRAUD": {"precision": 0.60, "recall": 0.50, "f1-score": 0.55, "support": 10.0},
    "...": "..."
  }
}
```

**`metrics.accuracy` adalah angka yang dicek terhadap target 80%** — proporsi prediksi benar di seluruh `sample_count` dataset eval. `macro_avg.f1-score` (rata-rata tak berbobot antar label) lebih jujur kalau salah satu label under-represented; `weighted_avg` condong ke label yang sample-nya banyak. `per_class` adalah tempat mencari label mana yang lemah — lihat §4 kalau ada yang jelek di sini walau `accuracy` keseluruhan sudah lolos.

Job evaluation yang `COMPLETED` otomatis membuat satu `model_versions` row berstatus `CANDIDATE` (link ke evaluation ini) — cek:

```bash
curl -s "$API/api/v1/model-versions?status=CANDIDATE" -H "Authorization: Bearer $TOKEN" | jq '.items'
```

---

## 4. `accuracy < 0.80` — apa yang diperbaiki

Urutan diagnosa, paling murah dulu:

1. **Baca `per_class`.** Label mana yang `recall`/`f1-score`-nya jelek? Itu yang butuh data lebih banyak/lebih beragam — bukan semua label rata.
2. **Cek data leakage.** Kalau eval isinya variasi/parafrase dekat dari train, akurasi tinggi tapi palsu; kalau train dan eval sama-sama templated dari sumber sintetis yang sama (§1), akurasi bisa palsu ke arah **rendah maupun tinggi** tergantung kebetulan overlap kosakata. Ganti ke data yang benar-benar independen.
3. **Cek label salah.** Tidak ada validasi otomatis untuk ini (§1) — baca ulang sample yang label-nya janggal secara manual, terutama untuk pasangan label yang gampang tertukar (`PHISHING_LINK` vs `FINANCIAL_FRAUD`, `HEALTH_HOAX` vs `GENERAL_NEWS` kalau topiknya kesehatan).
4. **Tambah volume**, terutama untuk label lemah dari langkah 1. TF-IDF+LogisticRegression bereaksi cepat terhadap tambahan data — tidak perlu ratusan sample baru untuk melihat pergerakan.
5. **Sumber data asli**, bukan sintetis. Operator feedback (`FALSE_POSITIVE`/`CONFIRM` dari `/threats`) mengalir ke `operator_feedback` — itu jalur yang dimaksud untuk membangun dataset yang mencerminkan pesan nyata ([[04_Datasets_and_Operator_Feedback]]).

Setelah data diperbaiki: **buat training job baru** (job lama tidak bisa dipakai ulang — `training_jobs` adalah record sekali jalan) dari dataset train yang sudah di-update, lalu evaluation baru dari dataset eval yang sama (§2-§3). Ulangi sampai `accuracy` ≥ 0.80 secara konsisten (jalankan evaluasi lebih dari sekali kalau ada elemen acak di data eval-nya — TF-IDF+LogisticRegression sendiri deterministic untuk data yang sama, jadi angka akan identik persis selama datanya tidak berubah).

---

## 5. `accuracy ≥ 0.80` — promosikan

Dua langkah, keduanya **manusia, eksplisit, tercatat di audit log** — tidak ada model yang otomatis jadi produksi ([[07_Model_Registry_and_Deployment]] §3-4):

```bash
curl -s -X PATCH $API/api/v1/model-versions/<model_version_id> \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"action":"VALIDATE"}'

curl -s -X PATCH $API/api/v1/model-versions/<model_version_id> \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"action":"PROMOTE"}'
```

`PROMOTE` otomatis men-`ARCHIVE`-kan model `PRODUCTION` yang lama (kalau ada) dalam satu transaksi — tidak pernah dua model `PRODUCTION` sekaligus (`idx_model_versions_single_production`, DB-level constraint).

Baru **setelah** `PROMOTE` ini, `app.pipeline.orchestrator` mulai memanggil `/v1/classify` untuk pesan WhatsApp yang masuk (cache 30 detik di proses worker — lihat `_cached_production_model`). Sebelumnya, nol perubahan perilaku.

**Rollback:** model lama tidak pernah dihapus, cuma `ARCHIVED`. Kalau model baru ternyata lebih buruk di produksi, `PROMOTE` lagi model version yang lama — operasi yang sama, sama-sama tercatat di audit log.

---

## Appendix — skrip end-to-end (curl)

Urutan penuh dari login sampai promote, buat disalin dan diisi:

```bash
API=http://127.0.0.1:8000

TOKEN=$(curl -s -X POST $API/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"<email operator>","password":"<password operator>"}' | jq -r '.access_token')

TRAIN_DS=$(curl -s -X POST $API/api/v1/datasets -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"name":"my-train-v1","version":1,"source":"CURATED"}' | jq -r '.id')
EVAL_DS=$(curl -s -X POST $API/api/v1/datasets -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"name":"my-eval-v1","version":1,"source":"CURATED"}' | jq -r '.id')

# ... tambah sample ke $TRAIN_DS dan $EVAL_DS lewat POST .../samples (§1) ...

curl -s -X PATCH $API/api/v1/datasets/$TRAIN_DS -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{"action":"VALIDATE"}'
curl -s -X PATCH $API/api/v1/datasets/$EVAL_DS -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{"action":"VALIDATE"}'

JOB=$(curl -s -X POST $API/api/v1/training-jobs -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{\"dataset_id\":\"$TRAIN_DS\",\"base_model\":\"tfidf-logreg\"}" | jq -r '.id')

# poll sampai status COMPLETED
until [ "$(curl -s $API/api/v1/training-jobs/$JOB -H "Authorization: Bearer $TOKEN" | jq -r '.status')" = "COMPLETED" ]; do sleep 2; done

EVAL=$(curl -s -X POST $API/api/v1/model-evaluations -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{\"training_job_id\":\"$JOB\",\"dataset_id\":\"$EVAL_DS\"}" | jq -r '.id')

until [ "$(curl -s $API/api/v1/model-evaluations/$EVAL -H "Authorization: Bearer $TOKEN" | jq -r '.status')" = "COMPLETED" ]; do sleep 2; done

curl -s $API/api/v1/model-evaluations/$EVAL -H "Authorization: Bearer $TOKEN" | jq '.metrics.accuracy'
# >= 0.80? lanjut VALIDATE + PROMOTE (§5). < 0.80? §4.
```

---

**Related:** [[05_Training_Jobs]] · [[06_Model_Evaluation]] · [[07_Model_Registry_and_Deployment]] · [[04_Datasets_and_Operator_Feedback]] · [[01_Dev_Environtment]] · [[02_Prod_Environtment]]
