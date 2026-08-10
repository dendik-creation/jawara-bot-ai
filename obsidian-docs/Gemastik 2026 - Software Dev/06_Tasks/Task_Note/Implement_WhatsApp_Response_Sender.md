# Catatan — Implement WhatsApp Response Sender

Task: [[Implement WhatsApp Response Sender]] · Indeks: [[00_Sprint_1_Completion_Notes]]

Kode: `backend/app/clients/waha_client.py` · Test: `backend/tests/test_waha_client.py`

---

## 1. Yang selesai

`POST /api/sendText` dengan payload `{session, chatId, text}` dan header `X-Api-Key`.

Kebijakan retry:

| Kegagalan | Perilaku |
| :--- | :--- |
| Timeout, connection error, HTTP 5xx | Retry sampai `WAHA_SEND_MAX_ATTEMPTS` (default 2), backoff `0.5s × percobaan` |
| HTTP 4xx | **Tidak** di-retry — `chatId` salah atau sesi berhenti akan gagal identik di percobaan kedua |
| Gagal permanen | `SendResult(delivered=False, error=...)` + log `ERROR`; **tidak** melempar exception |

Alasan tidak melempar: pipeline harus tetap menulis baris audit. Balasan yang tidak terkirim adalah fakta yang perlu dicatat, bukan alasan untuk membuang seluruh riwayat pemrosesan pesan itu.

---

## 2. ~~Yang tidak bisa diverifikasi~~ → **terverifikasi live 2026-08-09**

> **Pembaruan 2026-08-09.** Sesi WAHA `XL__087712032005` sudah ter-pairing dan berstatus `WORKING`. Pesan uji melewati seluruh pipeline dan **balasannya benar-benar terkirim ke WhatsApp**:
>
> ```json
> {"message":"pipeline complete","waha_message_id":"verify_wa_233039",
>  "intent":"HEALTH_HOAX","risk":"HIGH","similarity_score":0.9169,
>  "response_dispatched":true,"response_latency_ms":3571,
>  "logged":true,"degradations":[]}
> ```
>
> Kriteria *"Response delivered to the correct chatId"* ✅ terpenuhi. Detail lengkap: [[00_Sprint_2_Completion_Notes]] §3.
>
> Catatan yang tidak boleh hilang: **dua percobaan pertama tetap timeout** (2 × 5 detik) sebelum yang ketiga berhasil, padahal `POST /api/sendText` langsung ke WAHA dari host selesai dalam 0,11 detik. Biaya bangun sesi WhatsApp yang baru idle lebih besar dari `WAHA_SEND_TIMEOUT_SECONDS`. Lihat §3.

Catatan asli sprint sebelumnya, dipertahankan sebagai riwayat:

**Belum ada sesi WAHA yang di-pairing** di environment ini. Container `waha` sehat (`/ping` menjawab), tapi tidak ada perangkat WhatsApp yang tersambung.

Bukti dari uji end-to-end:

```text
waha send failed  attempt 1  error timeout
waha send failed  attempt 2  error timeout
waha send failed after retries, response not delivered  attempts 2
pipeline complete  response_dispatched false
                   degradations ["dispatch_failed:timeout"]
```

Jadi kriteria *"Response delivered to the correct chatId"* baru terbukti sampai batas: request terbentuk benar dan dikirim ke endpoint yang benar (diuji unit terhadap stub), retry berjalan, kegagalan tercatat. Yang belum: balasan benar-benar sampai ke WhatsApp.

Kriteria *"Delivery failure is retried at least once and logged if still failing"* ✅ justru terverifikasi live — karena kegagalannya nyata.

### Cara menyelesaikannya

1. Buka dashboard WAHA di `http://localhost:${WAHA_PORT}`, login dengan `WAHA_DASHBOARD_USERNAME` / `WAHA_DASHBOARD_PASSWORD`.
2. Start session `default`, scan QR.
3. Kirim pesan ke nomor tersebut, atau ulangi uji webhook dengan `chatId` nyata.

---

## 3. Latensi <3.0 detik: terukur, belum terpenuhi

Kriteria menyebut latensi end-to-end harus diukur dan dicatat terhadap target 3.0 detik. Pengukurannya ada: `response_latency_ms` dihitung dari `received_at` (dicap gateway saat enqueue) sampai setelah dispatch, ditulis ke `message_logs`, dan melampaui target memicu log `WARNING`.

Angka nyata dari uji end-to-end: **10.650 ms** — melampaui target, dan `WARNING`-nya memang muncul.

Penyebabnya bukan pipeline analisis. Rinciannya:

| Tahap | Perkiraan |
| :--- | :--- |
| Preprocessing + intent routing | <5 ms |
| RAG (`/v1/rag-query`, embedder hash) | ~40 ms |
| Generasi (`/v1/generate`, komposer template) | ~20 ms |
| **Dua percobaan kirim WAHA yang timeout** | **~10.500 ms** |

Artinya jalur analisis sudah jauh di bawah anggaran; yang membakar waktu adalah `WAHA_SEND_TIMEOUT_SECONDS=5` dikali dua percobaan pada sesi yang tidak ada.

Konsekuensi yang perlu diputuskan sebelum produksi: **timeout kirim 5 detik saja sudah melampaui seluruh anggaran 3 detik.** Pilihan yang masuk akal — turunkan `WAHA_SEND_TIMEOUT_SECONDS` ke ~2 detik, atau nyatakan bahwa target 3 detik diukur sampai *dispatch dimulai*, bukan sampai WAHA membalas. Keputusan ini belum diambil; lihat [[Open_Decisions_Carried_Forward]].

**Pembaruan 2026-08-09 — pengiriman yang berhasil pun masih di atas target.** Dengan sesi nyata dan dispatch benar-benar terkirim, `response_latency_ms` = **3.571 ms**, jadi `WARNING` tetap muncul. Rincian yang berubah dari tabel di atas: yang membakar waktu bukan lagi "sesi yang tidak ada", melainkan hop pertama ke sesi yang baru idle — percobaan berikutnya ke sesi yang sudah hangat selesai dalam ratusan milidetik.

Itu mematikan opsi "turunkan timeout ke ~2 detik": pesan pertama setelah idle akan selalu gagal terkirim. Opsi yang tersisa: definisikan ulang KPI sampai dispatch dimulai, atau hangatkan sesi secara berkala supaya biaya bangun tidak ditanggung pesan pengguna.

> **Pembaruan 2026-08-10 — akar masalah sebenarnya ditemukan, diperbaiki.** Diagnosis di atas ("sesi idle") ternyata cuma separuh benar. Log WAHA sendiri menunjukkan `"request aborted"` pada `responseTime: 5007` — WAHA **masih memproses** `/api/sendText` ketika klien (httpx) memutus koneksi tepat di detik ke-5. Bukan macet, cuma butuh waktu lebih lama dari yang diberi. Tes dengan timeout longgar (30 detik, 1 percobaan) membuktikan durasi asli: **7,6 detik** untuk kirim pertama ke grup/peserta `@lid` yang belum pernah di-resolve WAHA sebelumnya. Isolated script (tanpa beban webhook nyata) selalu selesai <50ms — sinyal bahwa lambatnya WAHA hanya muncul di bawah beban webhook sungguhan, bukan sesuatu yang bisa direproduksi lewat panggilan manual.
>
> Bug kedua yang ikut ketahuan: WAHA mengirim event `message` **dan** `message.any` untuk pesan masuk yang sama, dan gateway meng-enqueue keduanya sebagai job terpisah — setiap pesan diproses dua kali paralel, dua kirim balasan bersamaan ke chat yang sama, saling rebutan slot WEBJS yang serial per sesi. Diperbaiki dengan dedup `waha_message_id` di Redis sebelum enqueue (`backend/app/core/dedup.py`, TTL 600 detik, fail-open kalau Redis mati).
>
> Konsekuensinya, strategi "retry pendek berkali-kali" itu sendiri kontraproduktif: tiap abort di detik ke-5 membuang progres yang sudah dikerjakan WAHA, jadi 3× percobaan 5 detik (15 detik total) tetap gagal semua — bukan makin dekat ke sukses. Fix: `WAHA_SEND_TIMEOUT_SECONDS` 5→**15**, `WAHA_SEND_MAX_ATTEMPTS` kembali ke **2** (sekarang anggaran retry asli, bukan penambal timeout pendek).
>
> Terverifikasi live tiga kali berturut-turut di grup uji sungguhan: `response_dispatched: true`, `response_latency_ms` 7592 / 7519 / 7587, `degradations: []` pada kasus reply-to-bot. Detail commit: `141e1fd fix(pipeline): stop group replies from dropping under real WAHA load`. Keputusan di [[Open_Decisions_Carried_Forward]] §3.1 ditutup.

---

## 4. Efek samping yang sudah ditangani

Balasan yang dikirim bot kembali masuk sebagai event `message.any` dengan `fromMe: true`. Orchestrator membuangnya (`ignored_own_message`) — tanpa itu, bot akan menganalisis balasannya sendiri, tanpa henti.

---

**Related:** [[05_Integrations]] · [[04_How_it_Works]] · [[Create_Audit_Logging]] · [[Open_Decisions_Carried_Forward]]
