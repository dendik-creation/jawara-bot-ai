# Catatan — Integrate VirusTotal

Task: [[Integrate VirusTotal]] · Indeks: [[00_Sprint_1_Completion_Notes]]

Kode: `backend/app/clients/virustotal.py` + `backend/app/pipeline/url_safety.py`

---

## 1. Pemetaan verdict adalah keputusan threshold, bukan terjemahan langsung

VirusTotal mengagregasi ±90 engine dan melaporkan **jumlah**, bukan verdict tunggal. Satu deteksi dari sembilan puluh sering kali false positive; dua sudah sinyal.

| Kondisi | `risk_level_enum` |
| :--- | :--- |
| `malicious >= VIRUSTOTAL_HIGH_THRESHOLD` (default 2) | `HIGH` |
| `malicious == 1` atau `suspicious >= 1` | `MEDIUM` |
| Semua bersih | `LOW` |
| HTTP 404 (URL belum pernah dianalisis) | `UNKNOWN` |
| Timeout / 429 / 401 / error | `UNKNOWN` + `available: false` |

404 sengaja **bukan** `LOW`. "VirusTotal belum pernah melihat URL ini" bukan pernyataan bahwa URL-nya bersih — dan link phishing baru justru selalu berada di kondisi itu.

Threshold-nya config, bukan konstanta, karena cut-off yang tepat bergantung pada berapa banyak kapasitas review operator yang tersedia.

---

## 2. Aturan penggabungan dua provider

Di `url_safety.py`, sengaja asimetris:

1. **Yang terburuk menang.** Link yang ditandai hanya oleh satu provider tetap muncul sebagai risiko tinggi. Cakupan kedua provider nyaris tidak beririsan — Safe Browsing tahu phishing yang baru dilaporkan, VirusTotal tahu apa yang sudah di-crawl engine-nya — jadi menuntut kesepakatan berarti membuang mayoritas true positive.
2. **`UNKNOWN` tidak pernah menurunkan risiko.** Provider yang timeout/kehabisan kuota/tidak punya key tidak berkontribusi apa pun; ia tidak bisa menarik `HIGH` menjadi `LOW`.
3. **Shortlink yang tidak bisa diresolusi = `MEDIUM`, bukan `LOW`.** Domain yang terlihat (`bit.ly`) bukan domain tujuan, jadi "tidak ada provider yang menandai" tidak mengatakan apa-apa tentang tujuannya.
4. Host berupa IP literal diperlakukan sama seperti poin 3.

Kedua provider dipanggil **konkuren** (`asyncio.gather`) supaya anggarannya keluar dari satu jendela `URL_SCAN_TIMEOUT_SECONDS`, bukan bertumpuk di dalam target 3 detik.

---

## 3. Yang tidak bisa diverifikasi

**`VIRUSTOTAL_API_KEY` kosong.** Sama seperti [[Integrate_Safe_Browsing]]: kriteria *"URL berbahaya yang ditandai minimal satu provider muncul sebagai high risk"* diuji terhadap respons ter-stub (`backend/tests/test_url_safety.py::test_flagged_by_one_provider_is_still_high_risk`), bukan terhadap API nyata.

### Cara menyelesaikannya

```bash
# .env
VIRUSTOTAL_API_KEY=<64-hex>
```

---

## 4. Penanganan kuota

Free tier: **4 request/menit, 500/hari**, dan v3 **tidak punya lookup batch** — satu request per URL. Ini yang membuat batas per pesan lebih penting di sini daripada di Safe Browsing.

Pengaman yang sudah ada:

1. Cache Redis per URL (`URL_SCAN_CACHE_TTL_SECONDS`).
2. `URL_SCAN_MAX_URLS` (default 5) per pesan.
3. Setelah satu HTTP 429, sisa URL dalam pesan yang sama **tidak dipanggil sama sekali** — langsung ditandai `quota_exceeded`. Limit VirusTotal berbasis rolling window; retry langsung dijamin gagal lagi.

Yang belum ada: throttle 4 request/menit lintas worker. Dengan `URL_SCAN_MAX_URLS=5`, satu pesan saja sudah bisa melampaui batas per menit. Sebelum trafik nyata, tambahkan token bucket di Redis atau turunkan batas per pesan ke 2.

---

## 5. Keputusan privasi: hanya lookup, tidak pernah submit

Endpoint `POST /urls` (mengirim URL untuk dipindai) **tidak dipakai**. Mengirimkannya berarti mempublikasikan tautan yang diteruskan pengguna ke pihak ketiga, dan model privasi di [[01_Threat_Model_and_Data_Protection]] tidak mengizinkannya. Konsekuensinya: URL yang belum pernah dilihat VirusTotal akan selamanya `UNKNOWN` dari sisi provider ini.

---

**Related:** [[05_Integrations]] · [[Integrate_Safe_Browsing]] · [[01_Threat_Model_and_Data_Protection]]
