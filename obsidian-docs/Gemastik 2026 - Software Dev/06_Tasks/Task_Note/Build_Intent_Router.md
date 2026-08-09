# Catatan — Build Intent Router

Task: [[Build Intent Router]] · Indeks: [[00_Sprint_1_Completion_Notes]]

Kode: `backend/app/pipeline/intent_router.py` + `categories.py` · Test: `backend/tests/test_intent_router.py`

---

## 1. Router ini adalah Detection Rules, bukan model

[[01_System_Architecture]] §5 memisahkan dua mekanisme yang saling melengkapi: Detection Rules yang deterministik, dan ML classification yang probabilistik. Router ini adalah yang pertama — skoring keyword + indikator, bisa dijelaskan, bisa diubah operator tanpa retraining, murah untuk dijalankan pada setiap pesan.

Yang kedua (`POST /v1/classify` dengan confidence dan `model_version`) ada kontraknya di ML Service, tapi **belum ada modelnya**. Endpoint-nya menjawab error terstruktur `model_not_available`, dan gateway sudah tahu artinya: jatuh ke jalur rules-only dan tandai `ml_unavailable` ([[02_Data_Pipeline]] §6). Itu bukan stub yang berbohong; itu kontrak yang jujur mengatakan belum siap.

---

## 2. Confidence adalah *pangsa*, bukan probabilitas

Skor tiap kategori dijumlahkan dari bobot frasa dan indikator struktural (ada URL, shortlink, host IP, link yang di-defang, lampiran `.apk`, bentuk pertanyaan). Confidence = skor pemenang ÷ total skor.

Efeknya: pesan yang skor tinggi untuk dua kategori sekaligus dilaporkan **ambigu**, bukan sebagai kemenangan meyakinkan bagi yang kebetulan unggul tipis.

Dua ambang, keduanya config:

| Setting | Default | Arti |
| :--- | :--- | :--- |
| `INTENT_MIN_SCORE` | 1.5 | bukti minimum absolut; di bawah ini confidence dilaporkan `0.0` |
| `INTENT_CONFIDENCE_THRESHOLD` | 0.45 | seberapa dominan pemenang harus unggul |

Dibedakan dengan sengaja: "bukti terlalu sedikit" dan "terlalu banyak ambiguitas" adalah dua kegagalan berbeda, dan melaporkan confidence `1.0` untuk pesan yang hanya memicu satu keyword lemah akan menyesatkan pembaca log.

Nilai default 0.45 dipilih karena lebih ketat dari itu membuat kasus few-shot #5 di [[01_LLM_System_Prompt]] ("Apakah benar Puskesmas membuka vaksinasi flu gratis minggu depan?") jatuh ke UNKNOWN — pesan itu memang memicu `GENERAL_NEWS` dan `HEALTH_HOAX` sekaligus.

---

## 3. Cakupan kategori

| Kategori | Engine | Status |
| :--- | :--- | :--- |
| `HEALTH_HOAX` | `text_verification` | ✅ jalan |
| `GENERAL_NEWS` | `text_verification` | ✅ jalan |
| `PHISHING_LINK` | `url_safety` | ✅ jalan |
| `FILE_APK` | `apk_warning` | ✅ deteksi + peringatan, **tanpa** analisis statik |
| `FINANCIAL_FRAUD` | `unsupported` | ⚠️ diklasifikasi, tidak diverifikasi |

`FILE_APK` masuk meski task menyebut "3 kategori dalam scope", karena catatan scope di task itu sendiri menyatakan routing `FILE_APK` tetap MVP dan hanya analisis isi APK yang Opsional/Future ([[06_Optional_APK_Inspector]]).

`FINANCIAL_FRAUD` **tidak** dipetakan diam-diam ke engine lain. Ia mengembalikan `unsupported`, worker mencatat `engine_unsupported:FINANCIAL_FRAUD`, dan pengguna tetap mendapat balasan generik. Engine-nya butuh CekRekening.id / tabel `fraud_blacklists`, keduanya Post-MVP ([[05_Product_Scope_and_Roadmap]] §4).

Menambah engine nanti = satu baris di dict `ROUTES`. Ada test yang gagal kalau ada kategori `category_enum` tanpa route.

---

## 4. Anti-drift kode ↔ schema

Kriteria penerimaan "Category output values match `category_enum` exactly" ditegakkan mesin, bukan disiplin: `tests/test_intent_router.py` mem-parse `001_init_schema.sql` dan membandingkan anggota enum SQL dengan `Category` di Python. Menambah kategori di satu sisi saja membuat test merah sebelum ketidakcocokannya sampai ke `INSERT`.

Hal yang sama dilakukan untuk `risk_level_enum`.

---

## 5. Keputusan terbuka yang tetap terbuka

[[01_PostgreSQL_Schema]] §0 mencatat bahwa kategori ancaman Control Panel (Phishing, Scam, Social Engineering, Malicious Link, Impersonation, Spam, Other) belum dipetakan ke `category_enum`. Sprint ini **tidak** memutuskannya — router tetap memakai `category_enum` generasi pertama.

Tiga opsi yang masih berdiri: perluas enum, ganti dengan tabel referensi, atau pertahankan dua level (intent pipeline vs kategori ancaman). Lihat [[Open_Decisions_Carried_Forward]].

---

**Related:** [[03_Detection_Rules]] · [[01_PostgreSQL_Schema]] · [[02_Data_Pipeline]] · [[04_ML_Service]]
