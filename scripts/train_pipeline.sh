#!/bin/bash
# End-to-end threat-classifier training pipeline against datasets/indonesia_hoax_news/.
# 07_How_to_Run/03_How_To_Train_AI.md.
#
# Run on the VPS host, in the repo root, AFTER the DB bootstrap
# (02_Prod_Environtment.md §4b: migrate, qdrant_setup, seed_facts,
# ingest_knowledge, create_operator) has already run against a healthy stack.
#
# Reads OPERATOR_EMAIL/OPERATOR_PASSWORD straight from .env — never hardcode
# credentials in this file, it's committed to the repo.
#
# Usage: ./scripts/train_pipeline.sh [dataset-version]
# dataset-version defaults to 1. Bump it if a prior (name, version) pair got
# stuck REJECTED (e.g. a validation failure) and you need a clean retry —
# app.scripts.split_hoax_corpus is idempotent per (name, version), not a
# retry mechanism for a broken one.
set -e
cd "$(dirname "$0")/.."

API=http://127.0.0.1:8000
DS_VERSION="${1:-1}"

OPERATOR_EMAIL=$(grep -m1 '^OPERATOR_EMAIL=' .env | cut -d= -f2-)
OPERATOR_PASSWORD=$(grep -m1 '^OPERATOR_PASSWORD=' .env | cut -d= -f2-)
if [ -z "$OPERATOR_EMAIL" ] || [ -z "$OPERATOR_PASSWORD" ]; then
  echo "GAGAL: OPERATOR_EMAIL/OPERATOR_PASSWORD tidak ketemu di .env"
  exit 1
fi

echo "=== 1. split corpus indonesia_hoax_news -> dataset v$DS_VERSION (train/eval, disjoint) ==="
docker exec jawara-gateway python -m app.scripts.split_hoax_corpus --version "$DS_VERSION"

echo "=== 2. login operator ==="
TOKEN=$(curl -s -X POST "$API/api/v1/auth/login" -H "Content-Type: application/json" \
  -d "{\"email\":\"$OPERATOR_EMAIL\",\"password\":\"$OPERATOR_PASSWORD\"}" | jq -r '.access_token')
if [ -z "$TOKEN" ] || [ "$TOKEN" = "null" ]; then
  echo "GAGAL: token kosong. Cek OPERATOR_EMAIL/OPERATOR_PASSWORD di .env, atau create_operator belum dijalankan."
  exit 1
fi
echo "token ok"

echo "=== 3. ambil dataset id v$DS_VERSION ==="
TRAIN_DS=$(curl -s "$API/api/v1/datasets?status=DRAFT" -H "Authorization: Bearer $TOKEN" \
  | jq -r --argjson v "$DS_VERSION" '.items[] | select(.name=="indonesia-hoax-train" and .version==$v) | .id')
EVAL_DS=$(curl -s "$API/api/v1/datasets?status=DRAFT" -H "Authorization: Bearer $TOKEN" \
  | jq -r --argjson v "$DS_VERSION" '.items[] | select(.name=="indonesia-hoax-eval" and .version==$v) | .id')
if [ -z "$TRAIN_DS" ] || [ -z "$EVAL_DS" ]; then
  echo "GAGAL: dataset DRAFT v$DS_VERSION tidak ketemu."
  curl -s "$API/api/v1/datasets" -H "Authorization: Bearer $TOKEN" | jq '.items[] | {name, version, status}'
  exit 1
fi
echo "train=$TRAIN_DS eval=$EVAL_DS"

echo "=== 4. label_counts sebelum tambal FILE_APK ==="
curl -s "$API/api/v1/datasets/$TRAIN_DS" -H "Authorization: Bearer $TOKEN" | jq '.label_counts'
curl -s "$API/api/v1/datasets/$EVAL_DS" -H "Authorization: Bearer $TOKEN" | jq '.label_counts'

echo "=== 5. tambal FILE_APK (corpus asli nol untuk label ini — lihat import_hoax_corpus.py docstring) ==="
TRAIN_APK_COUNT=$(curl -s "$API/api/v1/datasets/$TRAIN_DS" -H "Authorization: Bearer $TOKEN" | jq '.label_counts.FILE_APK // 0')
if [ "$TRAIN_APK_COUNT" = "0" ]; then
  TRAIN_TEXTS=(
    "Kak, ini paket antum yang tertahan di gudang, cek resi disini ya kak, install dulu aplikasinya biar bisa lacak https://a.pack-cekresi.info/app.apk"
    "Selamat, undangan pernikahan digital sudah kami kirim, buka undangan.apk untuk lihat detail acara dan lokasi"
    "Assalamualaikum, ini surat tilang elektronik anda, mohon segera dibayar melalui aplikasi terlampir, install e-tilang.apk sebelum kena sanksi tambahan"
    "Info dari BPJS Kesehatan, kartu anda akan dinonaktifkan, silakan update data lewat aplikasi BPJS-Kesehatan-Update.apk yang kami lampirkan"
    "Kurir tidak bisa hubungi anda, paket dikembalikan jika tidak konfirmasi lewat aplikasi kurir resmi, install apk berikut untuk konfirmasi alamat"
    "Halo pak/bu, ini dari bank, ada kebijakan baru mengenai limit transfer, silakan install aplikasi resmi Livin-Update.apk untuk verifikasi ulang"
    "PLN informasikan tagihan listrik anda menunggak, cek dan bayar lewat aplikasi PLN-Mobile-Resmi.apk yang kami kirimkan"
    "Anda mendapat hadiah undian dari Telkomsel, klaim hadiah lewat aplikasi Telkomsel-Poin.apk, install sekarang sebelum kadaluarsa"
    "Ini dokumen resmi dari kantor pajak, mohon buka dan install aplikasi lampiran DJP-Online.apk untuk verifikasi NPWP anda"
    "Pesan dari kurir JNE, paket anda gagal diantar, silakan install aplikasi JNE-Express.apk untuk atur ulang jadwal pengiriman"
    "Berikut undangan resepsi pernikahan kami, mohon dibuka dengan aplikasi Undangan-Digital.apk yang sudah kami sertakan"
    "Petugas Dukcapil informasikan data KTP anda bermasalah, segera perbarui lewat aplikasi Dukcapil-Online.apk"
    "Selamat nomor anda terpilih menjadi pemenang doorprize, unduh dan install aplikasi Doorprize-Resmi.apk untuk klaim hadiah"
    "Ini surat panggilan dari kepolisian terkait pelanggaran lalu lintas, install aplikasi E-Tilang-Polri.apk untuk cek detail"
    "Mohon buka lampiran slip gaji bulan ini melalui aplikasi HR-Payroll.apk yang sudah kami kirimkan ke nomor anda"
    "Ada perubahan jadwal vaksinasi booster, silakan cek lewat aplikasi Vaksin-Update.apk yang terlampir di pesan ini"
    "Kartu keluarga anda perlu diperbarui, unduh formulir digital lewat aplikasi Kemendagri-Layanan.apk"
    "Rekening anda terindikasi kena pemblokiran otomatis, install aplikasi verifikasi Bank-Aman.apk untuk membuka blokir"
    "Tagihan BPJS Ketenagakerjaan anda menunggak, cek dan bayar via aplikasi BPJSTK-Mobile.apk yang kami lampirkan"
    "Ini invoice pembayaran belanja online anda, silakan konfirmasi lewat aplikasi Shopee-Invoice.apk terlampir"
  )
  EVAL_TEXTS=(
    "Paket kamu ditahan di gudang ekspedisi, install aplikasi lacak-paket.apk untuk ambil barangnya"
    "Surat pemberitahuan pajak kendaraan anda menunggak, buka aplikasi Samsat-Online.apk untuk cek dan bayar"
    "Info resmi dari kantor kelurahan, unduh aplikasi Bansos-2026.apk untuk verifikasi penerima bantuan"
    "Ini nota tagihan PDAM bulan ini, silakan install aplikasi PDAM-Pembayaran.apk untuk cek rincian"
    "Selamat anda dapat cashback dari e-wallet, klaim lewat aplikasi Cashback-Resmi.apk yang terlampir"
    "Dokumen resmi BPOM soal produk anda, mohon install aplikasi BPOM-Cek.apk untuk verifikasi izin edar"
    "Pesan dari operator seluler, kuota gratis anda menunggu klaim lewat aplikasi Kuota-Gratis.apk"
    "Ada surat panggilan sidang online, silakan buka lewat aplikasi E-Court.apk yang kami kirimkan"
    "Rincian gaji karyawan bulan ini ada di lampiran, buka dengan aplikasi Slip-Gaji.apk"
    "Info klaim asuransi kendaraan anda, install aplikasi Asuransi-Klaim.apk untuk proses cepat"
  )
  for t in "${TRAIN_TEXTS[@]}"; do
    curl -s -X POST "$API/api/v1/datasets/$TRAIN_DS/samples" -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
      -d "$(jq -n --arg text "$t" '{text: $text, label: "FILE_APK"}')" > /dev/null
  done
  for t in "${EVAL_TEXTS[@]}"; do
    curl -s -X POST "$API/api/v1/datasets/$EVAL_DS/samples" -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
      -d "$(jq -n --arg text "$t" '{text: $text, label: "FILE_APK"}')" > /dev/null
  done
  echo "FILE_APK ditambahkan: 20 train, 10 eval"
else
  echo "FILE_APK sudah ada ($TRAIN_APK_COUNT), skip"
fi

echo "=== 6. VALIDATE ==="
TRAIN_STATUS=$(curl -s -X PATCH "$API/api/v1/datasets/$TRAIN_DS" -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{"action":"VALIDATE"}' | tee /tmp/train_validate.json | jq -r '.status')
EVAL_STATUS=$(curl -s -X PATCH "$API/api/v1/datasets/$EVAL_DS" -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{"action":"VALIDATE"}' | tee /tmp/eval_validate.json | jq -r '.status')
echo "train dataset: $TRAIN_STATUS"
echo "eval dataset: $EVAL_STATUS"
if [ "$TRAIN_STATUS" != "VALIDATED" ] || [ "$EVAL_STATUS" != "VALIDATED" ]; then
  echo "GAGAL VALIDATE — alasan:"
  jq '.validation_notes' /tmp/train_validate.json /tmp/eval_validate.json
  exit 1
fi

echo "=== 7. training job ==="
JOB=$(curl -s -X POST "$API/api/v1/training-jobs" -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{\"dataset_id\":\"$TRAIN_DS\",\"base_model\":\"tfidf-logreg\"}" | jq -r '.id')
echo "job=$JOB"
while [ "$(curl -s "$API/api/v1/training-jobs/$JOB" -H "Authorization: Bearer $TOKEN" | jq -r '.status')" != "COMPLETED" ]; do
  printf '.'
  sleep 3
done
echo ""
echo "training COMPLETED"

echo "=== 8. evaluation ==="
EVAL=$(curl -s -X POST "$API/api/v1/model-evaluations" -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{\"training_job_id\":\"$JOB\",\"dataset_id\":\"$EVAL_DS\"}" | jq -r '.id')
while [ "$(curl -s "$API/api/v1/model-evaluations/$EVAL" -H "Authorization: Bearer $TOKEN" | jq -r '.status')" != "COMPLETED" ]; do
  printf '.'
  sleep 3
done
echo ""
echo "=== HASIL ==="
curl -s "$API/api/v1/model-evaluations/$EVAL" -H "Authorization: Bearer $TOKEN" | jq '.metrics'

MODEL_ID=$(curl -s "$API/api/v1/model-versions?status=CANDIDATE" -H "Authorization: Bearer $TOKEN" | jq -r '.items[0].id')
echo ""
echo "model version CANDIDATE: $MODEL_ID"
echo "Kalau accuracy >= 0.80, promote manual (sengaja tidak otomatis):"
echo "curl -s -X PATCH $API/api/v1/model-versions/$MODEL_ID -H \"Authorization: Bearer \$TOKEN\" -H \"Content-Type: application/json\" -d '{\"action\":\"VALIDATE\"}'"
echo "curl -s -X PATCH $API/api/v1/model-versions/$MODEL_ID -H \"Authorization: Bearer \$TOKEN\" -H \"Content-Type: application/json\" -d '{\"action\":\"PROMOTE\"}'"
