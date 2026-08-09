# Catatan — Integrate Safe Browsing

Task: [[Integrate Safe Browsing]] · Indeks: [[00_Sprint_1_Completion_Notes]]

Kode: `backend/app/clients/safe_browsing.py` · Test: `backend/tests/test_url_safety.py`

---

## 1. Yang selesai

Client Google Safe Browsing v4 (`threatMatches:find`), satu panggilan HTTP untuk sekumpulan URL sekaligus. Verdict dipetakan ke `risk_level_enum`:

| Kondisi | `risk_level_enum` |
| :--- | :--- |
| URL cocok dengan salah satu threat type | `HIGH` |
| Respons `matches` kosong (Safe Browsing menjawab, tidak menemukan apa-apa) | `LOW` |
| Timeout / kuota habis / key tidak ada / error | `UNKNOWN` + `available: false` |

Semua threat type Safe Browsing (`MALWARE`, `SOCIAL_ENGINEERING`, `UNWANTED_SOFTWARE`, `POTENTIALLY_HARMFUL_APPLICATION`) dipetakan ke `HIGH` karena API-nya memang tidak menyatakan derajat.

Kriteria "API key sourced from env, never logged" ditegakkan oleh test: key dikirim sebagai query param `key=`, tidak pernah masuk body, dan pesan exception di-scrub sebelum di-log (`_scrub` memotong string di `?`).

---

## 2. Yang tidak bisa diverifikasi

**`GOOGLE_SAFE_BROWSING_API_KEY` kosong.** Kriteria penerimaan *"Known-malicious test URL is flagged as high risk"* diverifikasi terhadap **respons ter-stub**, bukan terhadap API Google yang sesungguhnya.

Yang sudah pasti benar tanpa key: bentuk request, pemetaan verdict, penanganan timeout/429/4xx/5xx, dan perilaku cache.

Yang belum terbukti: bahwa request kita diterima Google sebagaimana adanya (bentuk `client.clientId`, format URL yang mereka harapkan).

### Cara menyelesaikannya

```bash
# .env
GOOGLE_SAFE_BROWSING_API_KEY=AIza...
```

Uji dengan URL uji resmi Google (`http://testsafebrowsing.appspot.com/s/phishing.html`), kirim lewat webhook, lalu periksa `risk_score` di `message_logs`.

Tanpa key, pipeline **tidak gagal** — indicator ditandai `UNKNOWN` dan deteksi berjalan dengan sinyal yang tersisa, persis seperti yang diminta [[05_Integrations]] §4. Terbukti live: pesan phishing uji tercatat sebagai `PHISHING_LINK` dengan `risk UNKNOWN` dan degradasi `url_intel_unavailable`.

---

## 3. Penanganan kuota (diminta task: "document quota handling before production traffic")

Lookup API gratis: ±10.000 request/hari.

Tiga pengaman, semuanya sudah ada di kode:

1. **Cache Redis** per URL, TTL `URL_SCAN_CACHE_TTL_SECONDS` (default 3600 detik). Satu pesan berantai yang sama beredar puluhan kali; tanpa cache, tiap kemunculan jadi satu request.
2. **Batas URL per pesan** `URL_SCAN_MAX_URLS` (default 5). Pesan spam berisi 40 link tidak bisa menghabiskan kuota harian sendirian.
3. **HTTP 429 tidak di-retry.** Provider ditandai tidak tersedia untuk pesan itu. Retry ke tembok kuota hanya memperdalam lubangnya.

Yang **belum** ada dan perlu sebelum trafik nyata: penghitung kuota harian lintas proses (mis. counter Redis dengan reset tengah malam) supaya operator bisa melihat sisa kuota sebelum kehabisan, bukan sesudah.

---

## 4. Verdict gabungan

Penggabungan dengan VirusTotal ada di `backend/app/pipeline/url_safety.py`, bukan di client ini. Lihat [[Integrate_VirusTotal]].

---

**Related:** [[05_Integrations]] · [[02_Data_Pipeline]] · [[Integrate_VirusTotal]]
