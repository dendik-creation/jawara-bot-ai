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

## 2. Yang tidak bisa diverifikasi: pengiriman ke sesi WhatsApp nyata

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

---

## 4. Efek samping yang sudah ditangani

Balasan yang dikirim bot kembali masuk sebagai event `message.any` dengan `fromMe: true`. Orchestrator membuangnya (`ignored_own_message`) — tanpa itu, bot akan menganalisis balasannya sendiri, tanpa henti.

---

**Related:** [[05_Integrations]] · [[04_How_it_Works]] · [[Create_Audit_Logging]] · [[Open_Decisions_Carried_Forward]]
