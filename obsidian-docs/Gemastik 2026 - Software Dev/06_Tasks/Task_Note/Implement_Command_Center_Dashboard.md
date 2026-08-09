# Catatan — Implement Command Center Dashboard

Task: [[Implement Command Center Dashboard]] · Indeks: [[00_Sprint_1_Completion_Notes]]

Kode: `frontend/` (shell + Command Center + Service Health) dan `backend/app/api/v1/endpoints/dashboard.py` + `backend/app/services/dashboard.py`

---

## 1. Dependensi yang task-nya belum ada, dibuat sekalian

Task ini mencantumkan dependensi *"Endpoint agregasi di gateway (belum ada task-nya)"*. Endpoint itu dibuat sebagai bagian dari task ini:

| Endpoint | Isi |
| :--- | :--- |
| `GET /api/v1/dashboard/summary` | messages processed, threats detected, critical threats, active users, rata-rata latensi, breakdown severity & intent |
| `GET /api/v1/dashboard/activity` | Live Activity — metadata dan klasifikasi saja |
| `GET /api/v1/dashboard/recent` | recent threats + blok incidents/alerts yang menyatakan dirinya belum tersedia |
| `GET /api/v1/system/services` | probe 6 service secara konkuren |
| `GET /api/v1/whatsapp/sessions` | daftar sesi WAHA yang sudah dinormalisasi |

Agregasi dilakukan gateway langsung dari PostgreSQL. Tidak ada Analytics Service — itu **Deferred** ([[05_Product_Scope_and_Roadmap]] §6).

---

## 2. Kriteria penerimaan

| Kriteria | Status |
| :--- | :--- |
| Hanya data agregat/anonim, tidak pernah `extracted_text` mentah | ✅ kolom itu tidak di-`SELECT` di mana pun dalam `services/dashboard.py`; ada test yang memastikan responsnya tidak memuat string tersebut |
| Tidak ada panggilan browser langsung ke WAHA/Qdrant/Redis/PostgreSQL/ML Service | ✅ `lib/api.ts` hanya mengenal `NEXT_PUBLIC_API_URL` |
| Metrik tanpa data ditampilkan "belum tersedia", bukan angka palsu | ✅ `StatTile` merender "belum tersedia" untuk `null`, tidak pernah `0` |
| Layout responsif desktop & tablet | ✅ grid `sm/lg/xl`, sidebar jadi menu di bawah `lg` |
| Tidak ada entri navigasi "Analytics" / "Infrastructure Analytics" | ✅ |

Terverifikasi dengan data nyata: setelah dua pesan uji, `summary` mengembalikan `messages_processed 1 → 2`, `critical_threats 1`, `intent_breakdown {"HEALTH_HOAX": 1}`.

---

## 3. Layar yang belum dibangun ditampilkan, bukan disembunyikan

Navigasi memuat seluruh area fungsional dari [[01_Control_Panel_Overview]] §2. Item yang layarnya belum ada dirender sebagai baris non-aktif dengan badge **"belum tersedia"**, bukan tautan ke halaman kosong.

Alasannya sama dengan alasan `StatTile` menolak menampilkan `0`: menu yang mengklik ke halaman kosong membuat orang mengira fiturnya rusak; menu yang jujur mengatakan belum ada memberi peta produk yang benar.

Blok Recent Incidents dan Recent Alerts memakai prinsip yang sama — gateway mengembalikan `available: false` dengan alasan `incidents_table_not_implemented`, bukan array kosong. Array kosong akan dibaca sebagai "hari ini aman".

---

## 4. ~~Yang belum aman: tidak ada auth operator~~ → **ditutup 2026-08-09**

> **Pembaruan 2026-08-09.** Autentikasi operator sudah ada: login email + password, sesi server-side 8 jam, dan `require_operator` menjaga seluruh router Control Panel. `DASHBOARD_API_KEY` beserta `NEXT_PUBLIC_DASHBOARD_KEY` **dihapus** dari kode, compose, dan `.env.example` — bagian di bawah ini tinggal riwayat. Yang masih Planned: **RBAC**. Detail: [[Implement_Operator_Auth]].

**Ini celah yang paling perlu diketahui dari task ini.** Autentikasi operator dan RBAC berstatus Planned (Fase 2), dan task ini tidak mencakupnya.

Sementara ini ada `DASHBOARD_API_KEY`: kalau diisi, semua endpoint Control Panel menuntut header `X-Dashboard-Key`; kalau kosong (default), endpoint terbuka.

Batasan yang harus dipahami:

- Ini mengautentikasi **deployment**, bukan **orang**. Tidak ada identitas per-pengguna, tidak ada role, tidak ada expiry.
- Karena frontend adalah aplikasi browser, key-nya ikut ter-bundle ke klien. Ia mencegah pemindaian internet acak, bukan penyerang yang menargetkan.
- Kelas kredensial ini tidak boleh dicampur dengan token sesi operator nanti ([[06_Platform_Security_Requirements]] §1) — model ancamannya berbeda.

Untuk self-hosted di jaringan internal, cukup. Untuk produksi, **tidak**. Jangan ekspos gateway ke internet sebelum Fase 2.

CORS sudah dikunci ke daftar origin eksplisit (`CORS_ALLOW_ORIGINS`), bukan wildcard.

---

## 5. Live Activity: polling, dan itu sementara

Transport live feed (SSE / WebSocket / polling) masih keputusan terbuka ([[02_Command_Center]] §4). Diambil opsi paling sederhana yang tidak menuntut channel Redis pub/sub tambahan: polling 10 detik untuk activity, 15 detik untuk metrik dan service health.

Responsnya menyertakan `"transport": "polling"` dan UI menyebutkan intervalnya, supaya sifat sementaranya terlihat, bukan tersembunyi. Menggantinya nanti berarti mengganti `hooks/use-polling.ts`, bukan layar-layarnya.

---

## 6. Catatan build yang sempat salah

`NEXT_PUBLIC_*` di-inline ke bundle klien saat `next build`. Sebelumnya compose hanya mengoper `NEXT_PUBLIC_API_URL` sebagai `environment:` runtime — yang tidak pernah sampai ke browser, sehingga dashboard di Docker akan memanggil default compile-time. Diperbaiki: nilai itu kini dioper sebagai **build arg** di `docker-compose.yml` dan `frontend/Dockerfile`.

---

**Related:** [[02_Command_Center]] · [[01_Control_Panel_Overview]] · [[08_Service_Health]] · [[07_Users_and_Risk]]
