# Cara Melatih Threat Classifier (dan Memverifikasi Akurasi Minimal 80%)

Model yang dipakai: TF-IDF (n-gram kata dan karakter) + `LogisticRegression`, kodenya ada di `ml-service/app/models/classifier.py`. Ada enam label: `HEALTH_HOAX`, `FINANCIAL_FRAUD`, `GENERAL_NEWS`, `PHISHING_LINK`, `FILE_APK`, `NOT_A_THREAT`.

Perlu diketahui dulu: tanpa model berstatus `PRODUCTION`, pipeline tetap berjalan normal lewat Detection Rules saja. Jadi melatih model ini **tidak wajib** supaya bot bisa berfungsi. Bagian ini murni untuk mengaktifkan sinyal ML tambahan.

**Yang menentukan akurasi di sini cuma satu hal: kualitas dan jumlah data berlabel.** Training job memang menerima field `epochs`/`learning_rate`/`batch_size`/`validation_split` di API-nya (lihat Appendix), tapi kenyataannya `classifier.train()` **tidak memakai field-field itu sama sekali**. `LogisticRegression` langsung di-fit apa adanya (`max_iter=1000`, `class_weight="balanced"` selalu aktif). Jadi jangan berharap akurasi naik lewat utak-atik hyperparameter, satu-satunya cara yang benar-benar berpengaruh adalah menambah dan memperbaiki data.

> [!warning] Knowledge Base itu berbeda dengan data training classifier
> Menu **AI / ML → Knowledge Base** (`/knowledge-base`, kodenya di `backend/app/services/knowledge.py`) memakai tabel `fact_items`, ini tabel yang sama sekali terpisah. Tabel ini dipakai untuk retrieval RAG lewat Qdrant, bukan input untuk `datasets`/`training_jobs` yang dibahas di dokumen ini. Fitur **Import CSV** di halaman itu (tombolnya ada di `KnowledgeBaseList`) meng-import fact item (klaim, penjelasan, verdict, sumber), bukan sample untuk training. Sampai saat ini, **tidak ada** endpoint atau tombol untuk import CSV khusus sample dataset classifier, baik lewat API maupun UI. Sample dataset cuma bisa ditambah satu per satu (lihat bagian 1 dan 1a). Jadi penempatan fitur Import CSV di Knowledge Base **sudah benar** kalau memang tujuannya untuk fact item. Tapi kalau tujuanmu menambah sample training secara massal, fitur itu memang belum ada sama sekali di codebase.

---

## 0. Prasyarat

- Stack sudah berjalan (cek dengan `docker compose ps`, semuanya harus `healthy`), minimal `api-gateway`, `celery-worker`, `ml-service`, `postgres`.
- Minimal punya satu akun operator (lihat [[01_Dev_Environtment]] bagian 4, atau [[02_Prod_Environtment]] bagian 4b). Semua endpoint di bawah ini butuh sesi login operator.
- Siapkan dua dataset yang **terpisah**, sama-sama berstatus VALIDATED, dan tidak boleh ada yang tumpang tindih (overlap): satu untuk **training**, satu lagi untuk **evaluasi** (disebut held-out, artinya model tidak pernah melihat data ini sama sekali saat training). Kalau akurasi dihitung dari dataset yang sama dengan yang dipakai training, hasilnya bohong, karena model cuma menghafal, bukan benar-benar belajar. Inilah alasan kenapa `model_evaluations.dataset_id` di skema database sengaja dibuat independen dari `training_jobs.dataset_id` (lihat [[06_Model_Evaluation]]).

Kalau cuma ingin coba cepat memakai data sintetis (untuk memastikan mekanismenya jalan, **bukan** untuk lulus target akurasi 80% yang sungguhan):

```bash
docker exec jawara-gateway python -m app.scripts.seed_dataset_samples
```

Perintah ini membuat dataset `core-detection-train` (240 sample) dan `core-detection-eval` (60 sample), keduanya langsung berstatus VALIDATED. Kalau kamu pakai ini, langsung lompat ke bagian 3.

---

## 1. Siapkan Dataset

Bisa lewat Control Panel (`/datasets`) atau langsung lewat API. Contoh lewat API, membuat dataset untuk training:

```bash
API=http://127.0.0.1:8000
TOKEN="<bearer token dari POST /api/v1/auth/login>"

curl -s -X POST $API/api/v1/datasets \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"name":"my-train-v1","version":1,"source":"CURATED","description":"training set asli"}'
# -> {"id": "<dataset_id>", "status": "DRAFT", ...}
```

Ulangi langkah yang sama untuk dataset evaluasi (`my-eval-v1`). Catat kedua `id`-nya, kamu akan butuh ini di langkah berikutnya.

Tambahkan sample satu per satu. Nilai `label` harus persis salah satu dari enam label di atas, huruf besar semua. Perlu hati-hati karena sistem tidak memvalidasi typo, jadi label yang salah ketik tetap akan lolos tanpa peringatan apa pun:

```bash
curl -s -X POST $API/api/v1/datasets/<dataset_id>/samples \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"text":"Selamat anda menang hadiah 50 juta, transfer biaya admin dulu","label":"FINANCIAL_FRAUD"}'
```

### 1a. Lewat Control Panel (UI), Bukan curl

Semua langkah di bagian 1 sampai 5 punya tampilan UI yang setara, ada di menu **AI / ML** (definisinya di `frontend/components/layout/navigation.ts`), dan sudah diverifikasi cocok dengan endpoint di atas:

- **Datasets** (`/datasets`), tombol **Buat Dataset** (isi nama, versi, sumber, deskripsi). Buka dataset-nya, lalu **Tambah sample manual** (isi teks dan label, satu per satu, sama seperti curl di bagian 1, tidak ada fitur bulk atau CSV di sini), lalu klik **Validasi**.
- **Training Jobs** (`/training-jobs`), tombol **Buat Job**. Dropdown dataset hanya menampilkan yang berstatus `VALIDATED` (jadi aturan di bagian 2 sudah dikunci lewat form). Field base model bisa diisi bebas, dan field epochs/learning-rate/batch-size/validation-split memang ada di form tapi diabaikan oleh backend (sesuai catatan di atas).
- **Evaluation** (`/evaluation`), tombol **Buat Evaluasi**. Dropdown training job hanya menampilkan yang `COMPLETED`, dropdown dataset uji hanya menampilkan yang `VALIDATED`. Ini cocok dengan aturan di bagian 3.
- **Models** (`/models`), buka model version berstatus `CANDIDATE`, lalu klik **Validasi**. Setelah statusnya `VALIDATED`, klik **Promosikan ke Production** (lihat bagian 5). Model version berstatus `ARCHIVED` punya tombol **Rollback (promosikan kembali)**, ini jalur rollback dari bagian 5 tanpa perlu curl sama sekali.

### Berapa Banyak Data yang Dibutuhkan, dan Seberapa Seimbang

- Minimal butuh **puluhan sample per label** supaya mulai terlihat berarti secara statistik. Makin banyak makin baik, terutama untuk label yang gampang tertukar satu sama lain, misalnya `PHISHING_LINK` dan `FINANCIAL_FRAUD` sama-sama sering menyebut kata "klik" atau "transfer".
- Jangan biarkan satu label mendominasi jauh lebih banyak dari yang lain. Setting `class_weight="balanced"` memang mengoreksi ketimpangan (skew) saat proses fit, tapi ia tidak bisa mengarang sinyal dari label yang cuma punya 3 contoh, sementara label lain punya 200.
- Pakai **variasi kalimat yang asli**, bukan satu kalimat yang di-copy-paste lalu diganti sedikit katanya. Data yang templated (seperti hasil `seed_dataset_samples.py`) gampang terpisah sempurna, sehingga akurasi evaluasinya jadi **menggembung, tidak realistis**. Ini karena TF-IDF menangkap pola template-nya, bukan makna kalimatnya. Kalau sumber datamu asli (pesan sungguhan, laporan operator lewat `/threats` dengan feedback `FALSE_POSITIVE`/`CONFIRM`), akurasi yang keluar baru bisa dipercaya.
- Data untuk evaluasi **tidak boleh** berupa parafrase atau variasi yang mirip dari data training. Kalau begitu, itu namanya data leakage (bocor), bukan pengukuran generalisasi yang sungguhan.

### Validasi Dataset

Setelah sample-nya cukup, jalankan `VALIDATE`. Perlu diingat, langkah ini akan mengunci dataset, kamu tidak bisa lagi menambah atau menghapus sample setelah ini:

```bash
curl -s -X PATCH $API/api/v1/datasets/<dataset_id> \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"action":"VALIDATE"}'
```

Ada dua pengecekan otomatis yang sifatnya mekanis saja (kodenya di `app/services/datasets.py`): **tidak boleh ada teks yang duplikat persis**, dan **tidak boleh ada pola nomor telepon mentah** (seperti `08xx...` atau `+62 8xx...`, ini demi menjaga privasi). Kalau gagal, status dataset akan jadi `REJECTED` disertai `validation_notes` yang berisi alasannya. Kalau lolos, statusnya jadi `VALIDATED`.

Perlu diketahui, **tidak ada pengecekan otomatis untuk label yang benar atau salah, atau untuk keseimbangan antar kelas**. Dua hal itu jadi tanggung jawab manusia, bukan sistem. Ulangi langkah yang sama untuk dataset evaluasi.

---

## 2. Training Job

```bash
curl -s -X POST $API/api/v1/training-jobs \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"dataset_id":"<train_dataset_id>","base_model":"tfidf-logreg"}'
# -> {"id": "<job_id>", "status": "QUEUED", ...}
```

Field `dataset_id` **wajib** memakai dataset yang sudah berstatus `VALIDATED` (lihat bagian 1), kalau tidak, request-nya akan ditolak. Field `base_model` boleh diisi string apa saja, nilainya cuma dicatat, tidak dibaca oleh kode (sampai saat ini, satu-satunya algoritma yang tersedia memang TF-IDF + LogisticRegression, apa pun nilai yang kamu isi). Field `epochs`/`learning_rate`/`batch_size`/`validation_split` boleh diisi, tapi akan diabaikan (lihat catatan di paragraf pembuka).

Pantau statusnya sampai `COMPLETED`:

```bash
watch -n 2 "curl -s $API/api/v1/training-jobs/<job_id> -H 'Authorization: Bearer $TOKEN' | jq '.status, .metrics, .generated_model_version'"
```

Urutan statusnya: `QUEUED` lalu `RUNNING` lalu `COMPLETED` (atau `FAILED` disertai `error_message`, kalau memang benar-benar gagal, bukan hasil yang dipalsukan). Untuk TF-IDF+LogisticRegression prosesnya cepat, hitungan detik, bukan menit, kecuali dataset-nya sangat besar.

> [!note] Status `EVALUATING` di enum tidak pernah dipakai
> Di skema database (`training_job_status_enum`) dan filter status di UI Training Jobs, ada status `EVALUATING` yang tercantum. Tapi kenyataannya `backend/app/services/training_jobs.py` cuma pernah menulis transisi `RUNNING` ke `COMPLETED`/`FAILED`. Tidak ada satu pun jalur kode yang berpindah ke status `EVALUATING`. Jadi jangan menunggu status itu muncul saat kamu polling.

Field `metrics.train_metrics.accuracy` yang muncul di sini **BUKAN** angka yang dipakai untuk mengukur target 80%. Ini adalah skor model terhadap data yang baru saja dipakai untuk melatihnya sendiri, jadi selalu terlihat optimis (biasanya mendekati 1.0). Abaikan angka ini untuk keputusan promosi. Angka yang sebenarnya dipakai ada di bagian 3.

Catat nilai `generated_model_version` (formatnya `clf-xxxxxxxxxxxx`), kamu akan butuh ini di langkah berikutnya.

---

## 3. Model Evaluation (Ini Angka yang Sebenarnya Dipakai)

```bash
curl -s -X POST $API/api/v1/model-evaluations \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"training_job_id":"<job_id>","dataset_id":"<eval_dataset_id>"}'
# -> {"id": "<evaluation_id>", "status": "QUEUED", ...}
```

Field `dataset_id` di sini **harus** memakai dataset evaluasi yang terpisah dari dataset training (lihat bagian 0). Sistem sebenarnya tidak memaksa secara teknis kalau kamu memakai dataset yang sama, tapi kalau kamu lakukan itu, angka hasilnya jadi tidak berarti apa-apa.

Pantau statusnya sampai `COMPLETED`:

```bash
curl -s $API/api/v1/model-evaluations/<evaluation_id> -H "Authorization: Bearer $TOKEN" | jq '.status, .metrics'
```

Contoh bentuk `metrics`:

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

**`metrics.accuracy` adalah angka yang dicek terhadap target 80%.** Ini adalah proporsi prediksi yang benar, dihitung dari seluruh `sample_count` di dataset evaluasi. Nilai `macro_avg.f1-score` (rata-rata tak berbobot antar label) lebih jujur kalau ada label yang jumlah datanya jauh lebih sedikit (under-represented), sementara `weighted_avg` cenderung condong ke label yang sample-nya banyak. Bagian `per_class` adalah tempat kamu bisa cari tahu label mana yang paling lemah, walaupun angka `accuracy` keseluruhan sudah lolos target (lihat bagian 4 kalau ada label yang jelek di sini).

Setiap evaluation yang selesai (`COMPLETED`) akan otomatis membuat satu baris baru di tabel `model_versions`, berstatus `CANDIDATE`, terhubung ke evaluation ini. Cek dengan:

```bash
curl -s "$API/api/v1/model-versions?status=CANDIDATE" -H "Authorization: Bearer $TOKEN" | jq '.items'
```

---

## 4. Kalau `accuracy` Masih di Bawah 0.80, Apa yang Perlu Diperbaiki

Urutan diagnosa, dari yang paling murah dulu:

1. **Baca bagian `per_class`.** Label mana yang nilai `recall` atau `f1-score`-nya jelek? Label itulah yang butuh data lebih banyak atau lebih beragam, bukan berarti semua label harus ditambah rata.
2. **Cek kemungkinan data leakage.** Kalau isi data eval-mu adalah variasi atau parafrase yang mirip dari data train, akurasinya akan terlihat tinggi tapi sebenarnya palsu. Sebaliknya, kalau data train dan eval sama-sama dibuat dari sumber sintetis yang sama (lihat bagian 1), akurasinya bisa jadi palsu ke arah **rendah maupun tinggi**, tergantung kebetulan tumpang tindih kosakatanya. Solusinya, ganti dengan data yang benar-benar independen satu sama lain.
3. **Cek kemungkinan label yang salah.** Tidak ada validasi otomatis untuk ini (lihat bagian 1), jadi kamu perlu membaca ulang sample yang labelnya terasa janggal secara manual. Perhatikan khususnya pasangan label yang gampang tertukar, misalnya `PHISHING_LINK` dengan `FINANCIAL_FRAUD`, atau `HEALTH_HOAX` dengan `GENERAL_NEWS` kalau topiknya soal kesehatan.
4. **Tambah volume data**, terutama untuk label yang lemah dari langkah 1. TF-IDF+LogisticRegression cukup cepat bereaksi terhadap tambahan data, jadi kamu tidak perlu sampai ratusan sample baru untuk mulai melihat pergerakan.
5. **Pakai sumber data asli**, bukan sintetis. Feedback operator (label `FALSE_POSITIVE`/`CONFIRM` dari menu `/threats`) mengalir ke tabel `operator_feedback`. Ini adalah jalur yang memang dimaksudkan untuk membangun dataset yang mencerminkan pesan sungguhan (lihat [[04_Datasets_and_Operator_Feedback]]).

Setelah datanya diperbaiki, **buat training job yang baru**. Job lama tidak bisa dipakai ulang, karena `training_jobs` memang dirancang sebagai record sekali jalan. Lakukan evaluasi baru juga dari dataset eval yang sama (ulangi bagian 2 dan 3). Ulangi proses ini sampai `accuracy` mencapai minimal 0.80 secara konsisten. Kalau ada elemen acak di data eval-mu, jalankan evaluasi lebih dari sekali untuk memastikan. Perlu dicatat, TF-IDF+LogisticRegression sendiri bersifat deterministic (hasilnya pasti sama) untuk data yang sama persis, jadi angkanya akan identik selama datanya tidak berubah.

---

## 5. Kalau `accuracy` Sudah Mencapai 0.80 atau Lebih, Saatnya Promosikan

Ada dua langkah, dan keduanya **dilakukan manusia secara eksplisit, dan tercatat di audit log**. Tidak ada model yang otomatis jadi produksi (lihat [[07_Model_Registry_and_Deployment]] bagian 3-4):

```bash
curl -s -X PATCH $API/api/v1/model-versions/<model_version_id> \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"action":"VALIDATE"}'

curl -s -X PATCH $API/api/v1/model-versions/<model_version_id> \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"action":"PROMOTE"}'
```

Ketika `PROMOTE` dijalankan, model `PRODUCTION` yang lama (kalau ada) akan otomatis dipindahkan statusnya jadi `ARCHIVE` dalam satu transaksi. Tidak akan pernah ada dua model `PRODUCTION` sekaligus, ini dijaga lewat constraint di level database (`idx_model_versions_single_production`).

Baru **setelah** `PROMOTE` ini dilakukan, `app.pipeline.orchestrator` mulai memanggil `/v1/classify` untuk setiap pesan WhatsApp yang masuk (hasilnya di-cache 30 detik di proses worker, lihat `_cached_production_model`). Sebelum ini, tidak ada perubahan perilaku sama sekali.

**Rollback:** model lama tidak pernah benar-benar dihapus, cuma dipindah statusnya jadi `ARCHIVED`. Kalau ternyata model baru performanya lebih buruk di produksi, kamu tinggal `PROMOTE` lagi model version yang lama. Ini operasi yang sama persis, dan tetap tercatat di audit log.

---

## Appendix: Skrip End-to-End (curl)

Urutan lengkap dari login sampai promote, bisa disalin dan diisi sesuai kebutuhanmu:

```bash
API=http://127.0.0.1:8000

TOKEN=$(curl -s -X POST $API/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"<email operator>","password":"<password operator>"}' | jq -r '.access_token')

TRAIN_DS=$(curl -s -X POST $API/api/v1/datasets -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"name":"my-train-v1","version":1,"source":"CURATED"}' | jq -r '.id')
EVAL_DS=$(curl -s -X POST $API/api/v1/datasets -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"name":"my-eval-v1","version":1,"source":"CURATED"}' | jq -r '.id')

# ... tambahkan sample ke $TRAIN_DS dan $EVAL_DS lewat POST .../samples (lihat bagian 1) ...

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
# Kalau hasilnya >= 0.80, lanjut ke VALIDATE + PROMOTE (bagian 5). Kalau masih < 0.80, ikuti bagian 4.
```

---

**Related:** [[05_Training_Jobs]] · [[06_Model_Evaluation]] · [[07_Model_Registry_and_Deployment]] · [[04_Datasets_and_Operator_Feedback]] · [[01_Dev_Environtment]] · [[02_Prod_Environtment]]
