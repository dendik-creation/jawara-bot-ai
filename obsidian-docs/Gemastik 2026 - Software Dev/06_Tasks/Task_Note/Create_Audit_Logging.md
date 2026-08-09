# Catatan — Create Audit Logging

Task: [[Create Audit Logging]] · Indeks: [[00_Sprint_1_Completion_Notes]]

Kode: `backend/app/services/message_log.py` · Test: `backend/tests/test_message_log.py`

---

## 1. Terverifikasi terhadap database nyata

Tidak hanya unit test — test integrasi menulis ke PostgreSQL yang hidup, dan uji end-to-end menghasilkan baris nyata:

```text
waha_message_id | chat_type | input_type | detected_intent | risk_score | sim    | latency_ms
e2e_test_001    | PERSONAL  | TEXT       | HEALTH_HOAX     | HIGH       | 0.8707 | 10650
e2e_test_002    | GROUP     | URL_LINK   | PHISHING_LINK   | UNKNOWN    | NULL   | 10575
```

Ketiga kriteria penerimaan:

| Kriteria | Status |
| :--- | :--- |
| Setiap balasan yang diproses punya baris `message_logs` | ✅ |
| `waha_message_id` UNIQUE mencegah pencatatan ganda saat webhook retry | ✅ — kiriman ulang menghasilkan `logged: false`, jumlah baris tetap |
| Field sesuai schema (intent, risk, matched fact, similarity, latency) | ✅ |

`user_hash` adalah SHA-256 bersalt sepanjang 64 karakter; nomor WhatsApp mentah tidak pernah masuk database. Baris `user_subscriptions` di-upsert lebih dulu karena `message_logs.user_hash` adalah foreign key ke sana — tanpa itu, pesan dari chat yang belum pernah dikenal akan gagal insert.

---

## 2. Keputusan: kegagalan tulis audit tidak memicu retry Celery

Kalau PostgreSQL mati saat baris audit hendak ditulis, kegagalannya dicatat (`audit_write_failed`) dan task tetap dianggap sukses.

Alasannya: retry Celery akan mengulang **seluruh** pipeline, termasuk generasi dan pengiriman. Pengguna sudah menerima balasannya; retry akan mengirimkan balasan kedua. Antara "kehilangan satu baris audit" dan "mengirim pesan dobel ke lansia yang sedang panik", yang pertama jauh lebih murah.

Konsekuensinya jujur dan perlu dicatat: **saat PostgreSQL down, baris audit untuk pesan itu hilang permanen.** Kalau ini tidak dapat diterima nanti, solusinya bukan retry melainkan memisahkan penulisan audit ke task Celery tersendiri yang idempoten.

---

## 3. Isu privasi yang masih terbuka

`message_logs.extracted_text` menyimpan isi pesan dalam **plaintext** tanpa retention policy — temuan prioritas tinggi #1 di [[01_Documentation_Audit_Report]]. Task ini menyatakan retention di luar scope, dan memang tidak dikerjakan.

Yang ditambahkan sebagai mitigasi sementara: flag `LOG_MESSAGE_CONTENT` (default `true`). Set `false` dan jejak audit tetap lengkap — intent, risiko, similarity, latensi — tanpa menyimpan apa yang pengguna tulis. Ini bukan pengganti retention policy; ini saklar supaya deployment yang peduli punya pilihan hari ini.

Yang masih harus diputuskan: berapa lama `extracted_text` boleh disimpan, siapa yang boleh membacanya, dan bagaimana penghapusannya dijalankan. Lihat [[Open_Decisions_Carried_Forward]].

---

## 4. Yang tidak termasuk task ini

`message_logs` adalah jejak **pesan**, berbeda dari audit **aksi operator** ([[05_Audit_Logs]]) yang tabelnya belum ada. Jangan tertukar: yang satu mencatat apa yang diputuskan sistem terhadap sebuah pesan, yang lain mencatat apa yang dilakukan manusia terhadap sistem.

---

**Related:** [[01_PostgreSQL_Schema]] · [[05_Audit_Logs]] · [[01_Threat_Model_and_Data_Protection]] · [[Implement_WhatsApp_Response_Sender]]
