# Sprint 2 — Catatan Penyelesaian

Tanggal eksekusi: **2026-08-09**. Lanjutan dari [[00_Sprint_1_Completion_Notes]].

Empat pekerjaan: menutup hutang konfigurasi Sprint 1, autentikasi operator, penyatuan toolchain Python, dan menyelesaikan verifikasi live yang tertinggal.

---

## 1. Ringkasan Status

| Pekerjaan | Hasil | Verifikasi | Catatan |
| :--- | :--- | :--- | :--- |
| Derivasi connection URL dari `.env` root | Selesai | ✅ 154 test | Proses lokal tidak lagi jatuh ke placeholder `postgres:postgres@localhost` / `http://ml-service:9000` |
| Autentikasi operator (email + password) | Selesai | ✅ live gateway + 11 test integration | [[Implement_Operator_Auth]] |
| Toolchain Python → `uv` saja | Selesai | ✅ 154 + 69 test, kedua image build | [[Open_Decisions_Carried_Forward]] §1b |
| Verifikasi dispatch WhatsApp | Selesai | ✅ pesan nyata terkirim | §3 di bawah |
| Verifikasi Safe Browsing / VirusTotal | **Tidak bisa** | ⚠️ tanpa API key | §4 |

---

## 2. Apa yang Berubah di Repo

**Backend:**

```
app/db/migrations/002_operator_auth.sql   operators + operator_sessions
app/core/passwords.py                     bcrypt + fold SHA-256, dummy_verify
app/core/security.py                      require_operator (gate sesi) + verify_api_key
app/services/auth.py                      akun, sesi, pencabutan, purge
app/api/v1/endpoints/auth.py              login / logout / me
app/schemas/auth.py                       kontrak wire
app/scripts/create_operator.py            pembuatan akun out-of-band
```

`app/api/v1/endpoints/dashboard.py` kehilangan gerbang `X-Dashboard-Key`-nya; gantinya `require_operator` di level router.

**Frontend:** `/login`, route group `(panel)`, `AuthProvider`, `RequireAuth`, `lib/session.ts`, shell sidebar shadcn/ui (sidebar, input, label, alert, dropdown-menu, tooltip, sheet, skeleton, separator, avatar).

**Toolchain:** `requirements.txt` / `requirements-dev.txt` dihapus di `backend/` dan `ml-service/`; keduanya kini `pyproject.toml` + `uv.lock`, base image `python:3.14-slim`, install lewat `uv sync --locked --no-dev`.

**Konfigurasi:** `DASHBOARD_API_KEY` dan `NEXT_PUBLIC_DASHBOARD_KEY` hilang dari `.env.example`, `docker-compose.yml`, dan `frontend/Dockerfile`. Masuk: `AUTH_SESSION_TTL_MINUTES`, `AUTH_BCRYPT_ROUNDS`, `AUTH_LOGIN_MAX_ATTEMPTS`, `AUTH_LOGIN_WINDOW_SECONDS`.

---

## 3. Verifikasi Dispatch WhatsApp — akhirnya live

Sprint 1 menutup [[Implement_WhatsApp_Response_Sender]] sebagai "selesai (kode)" karena tidak ada sesi WAHA yang ter-pairing. Sekarang ada: sesi `XL__087712032005`, status `WORKING`.

Pesan uji dikirim ke webhook dengan session dan `chatId` sesi itu sendiri:

```json
{"message":"pipeline complete","waha_message_id":"verify_wa_233039",
 "intent":"HEALTH_HOAX","engine":"text_verification","risk":"HIGH",
 "match_count":1,"similarity_score":0.9169,
 "response_dispatched":true,"response_latency_ms":3571,
 "logged":true,"degradations":[]}
```

`degradations: []` — untuk pertama kalinya seluruh jalur berjalan penuh, termasuk hop terakhir. Balasan WhatsApp benar-benar diterima di nomor tujuan, dan baris auditnya ada di `message_logs`.

**Dua percobaan pertama gagal dengan `dispatch_failed:timeout`**, dua kali 5 detik, sebelum percobaan ketiga berhasil dalam 3,5 detik. Panggilan `POST /api/sendText` langsung ke WAHA dari host selesai dalam 0,11 detik, dan `WahaClient` yang sama dipanggil dari skrip terpisah berhasil dalam 0,29 detik — jadi kodenya tidak salah dan WAHA tidak lambat secara umum. Yang paling cocok dengan data: hop pertama ke sesi WhatsApp yang baru saja idle mahal (WAHA membangunkan koneksi engine-nya), dan anggaran 5 detik ada di bawah biaya itu.

Ini bukti langsung untuk keputusan terbuka §3.1 di [[Open_Decisions_Carried_Forward]]: bahkan pada percobaan yang **berhasil**, latensi end-to-end 3.571 ms melewati target 3.000 ms. Menurunkan `WAHA_SEND_TIMEOUT_SECONDS` ke 2 detik seperti opsi 1 di sana akan membuat pesan pertama setelah idle **selalu** gagal terkirim.

---

## 4. Yang Tetap Tidak Bisa Diverifikasi

| Item | Alasan | Perilaku yang teramati |
| :--- | :--- | :--- |
| Google Safe Browsing | `GOOGLE_SAFE_BROWSING_API_KEY` kosong | Provider nonaktif; verdict URL `UNKNOWN` + degradasi `url_intel_unavailable` |
| VirusTotal | `VIRUSTOTAL_API_KEY` kosong | Sama |
| Generasi LLM nyata | `LLM_PROVIDER=template`, `ANTHROPIC_API_KEY` kosong | Balasan disusun composer deterministik; kontrak empat bagian tetap dipenuhi |

Ketiganya adalah **keadaan konfigurasi, bukan bug**: tanpa penyedia, sistem berkata "tidak tahu", bukan "aman". Kodenya sudah ada dan punya test unit; yang belum ada adalah bukti terhadap layanan sungguhan.

---

## 5. Yang Tidak Dikerjakan

| Item | Alasan |
| :--- | :--- |
| RBAC | Diminta eksplisit untuk **tidak** dikerjakan. Fase 3 ([[07_Users_and_Risk]]) |
| Endpoint pendaftaran mandiri | Konsol internal; akun dibuat lewat CLI |
| 2FA, kebijakan password, reset lewat email | Belum ada layar manajemen akun sama sekali |
| Audit trail aksi operator | Tabelnya belum ada ([[05_Audit_Logs]]) |
| Pemanggilan `purge_expired_sessions` terjadwal | Fungsinya ada, penjadwalnya belum |
| Threat Monitoring / Message Inspection | Layar Fase 2 berikutnya, di luar scope sprint ini |

---

**Related:** [[TASKS]] · [[Implement_Operator_Auth]] · [[Open_Decisions_Carried_Forward]] · [[05_Product_Scope_and_Roadmap]] · [[00_Sprint_1_Completion_Notes]]
