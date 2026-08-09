# Autentikasi Operator — Catatan Implementasi

Indeks: [[00_Sprint_2_Completion_Notes]] · Tanggal: **2026-08-09**

Menutup item *Authentication (operator Control Panel)* di [[06_Platform_Security_Requirements]] §1 dan keputusan terbuka §3.2 di [[Open_Decisions_Carried_Forward]].

Scope yang diminta dan dikerjakan: **login email + password, tanpa RBAC**, dan `DASHBOARD_API_KEY` ditiadakan sepenuhnya.

---

## 1. Kenapa `DASHBOARD_API_KEY` dihapus, bukan dipertahankan sebagai lapis kedua

Tiga alasan, berurut dari yang paling merusak:

1. **Default-nya terbuka.** Kosong berarti seluruh endpoint Control Panel bisa diakses tanpa apa pun. Gerbang yang bisa dimatikan dengan mengosongkan satu variabel pada akhirnya akan dimatikan — dan justru di lingkungan yang paling mudah dilupakan.
2. **Ia mengautentikasi deployment, bukan orang.** Tidak ada jawaban untuk "siapa yang membuka layar ini", dan tidak ada cara mencabut akses satu orang.
3. **Sisi frontend-nya bukan rahasia sama sekali.** `NEXT_PUBLIC_DASHBOARD_KEY` di-inline ke bundle browser saat build; siapa pun yang membuka halaman bisa membacanya.

Mempertahankannya sebagai "lapis tambahan" hanya akan menambah satu variabel yang harus diputar dan satu jalur yang harus diuji, tanpa menambah jaminan apa pun di atas sesi operator.

---

## 2. Bentuk yang dipilih

| Keputusan | Pilihan | Alasan |
| :--- | :--- | :--- |
| Nama tabel | `operators`, bukan `users` | `user_hash` di schema ini sudah berarti pengguna WhatsApp yang anonim. Dua arti "user" dalam satu schema akan bertemu di satu query cepat atau lambat |
| Bentuk sesi | Row `operator_sessions` | JWT tidak bisa dicabut tanpa denylist, dan denylist adalah tabel sesi yang menyamar. Satu lookup terindeks per request membeli logout yang nyata |
| Yang disimpan | SHA-256 token, bukan tokennya | Dump database tidak membagikan sesi hidup |
| Hash token | SHA-256, bukan bcrypt | Token = 32 byte acak; tidak ada yang bisa ditebak. KDF lambat per request hanya menambah latensi |
| Hash password | bcrypt, cost dari `AUTH_BCRYPT_ROUNDS` | Pilihan konservatif, wheel tersedia di mana-mana, cost bisa dinaikkan tanpa mengubah kode |
| Umur sesi | 480 menit (8 jam) | Satu shift kerja. Cukup panjang supaya operator tidak mengetik ulang password di tengah insiden, cukup pendek supaya token curian mati di hari yang sama |
| Pembuatan akun | CLI `app.scripts.create_operator` | Ini konsol keamanan internal. Endpoint pendaftaran mandiri adalah permukaan serangan tanpa pengguna |

---

## 3. Detail keamanan yang tidak terlihat dari daftar endpoint

**Password panjang tidak dipotong diam-diam.** bcrypt mengabaikan byte ke-73 dan seterusnya; tanpa penanganan, dua passphrase panjang yang berbagi awalan menjadi password yang sama. Password di-SHA-256 lalu di-base64 (44 byte) sebelum masuk bcrypt — base64, bukan digest mentah, karena bcrypt juga berhenti di byte NUL pertama.

**Enumerasi akun ditutup dari dua sisi.** Pesan gagal login untuk password salah, email tidak dikenal, dan akun nonaktif identik. Selain itu email yang tidak ada tetap membayar satu verifikasi bcrypt (`dummy_verify`) dengan cost yang sama, dan akun nonaktif diperiksa **setelah** password — kalau tidak, keduanya akan menjawab jauh lebih cepat daripada akun aktif dan selisih waktunya jadi oracle.

**Rate limit dihitung sebelum password diperiksa.** 5 percobaan per (email, IP klien) per 5 menit, keyspace Redis terpisah dari rate limit webhook. Kalau dihitung setelah verifikasi, percobaan yang di-throttle tetap menjalankan bcrypt dan throttle-nya sendiri berubah jadi alat mengukur waktu hashing. Fail open bila Redis mati: operator terkunci saat Redis tumbang adalah pemadaman dashboard keamanan, sementara brute force tetap dibatasi bcrypt.

**Database mati menjawab 503, bukan 401.** Gate ini tidak pernah "degrade to available: false" seperti endpoint baca dashboard. Mengatakan "password salah" saat PostgreSQL yang tumbang akan mengirim operator memburu masalah yang tidak ada.

**Gate dipasang di level router.** `require_operator` menempel di `APIRouter(dependencies=[...])`, jadi endpoint Control Panel baru terlindungi karena sudah ada, bukan karena penulisnya ingat. Ada test yang menelusuri seluruh route di bawah prefix Control Panel dan gagal kalau salah satunya tidak membawa dependency itu.

---

## 4. Frontend

`/login` berdiri di luar route group `(panel)`; semua layar panel ada di dalamnya, di belakang `RequireAuth` + shell sidebar. `RequireAuth` tidak merender apa pun sampai token tersimpan diadu ke `GET /auth/me`, jadi pengunjung yang belum masuk tidak pernah melihat kerangka panel berkedip sebelum dialihkan.

`RequireAuth` adalah **pengalihan, bukan batas keamanan**. Batas yang sebenarnya `require_operator` di gateway, yang dilewati semua data layar ini. Panel yang di-bypass di browser tidak menghasilkan satu baris data pun.

Satu tempat memutuskan arti 401 (`lib/api.ts`), jadi sesi yang habis di tengah polling menjatuhkan operator ke `/login` sekali, bukan sekali per widget.

---

## 5. Risiko yang diketahui dan tidak ditutup

**Token ada di `localStorage`.** XSS di panel bisa membacanya. Mitigasi sekarang: expiry 8 jam dan pencabutan saat logout — itu mitigasi, bukan solusi. Cookie `httpOnly` menuntut gateway satu origin dengan panel, atau route handler Next.js yang mem-proxy setiap panggilan Control Panel. Keduanya perubahan yang lebih besar dari kebutuhan layar ini hari ini. Dicatat sebagai keputusan terbuka.

**Tidak ada 2FA, tidak ada kebijakan password** selain minimum 8 karakter. Minimum itu lantai, bukan kebijakan.

**Tidak ada audit trail aksi operator.** Yang tercatat baru jejak sesi: `operators.last_login_at`, plus user agent dan IP di `operator_sessions`. Siapa mengubah apa masih Planned ([[05_Audit_Logs]]).

**`operator_sessions` tumbuh satu row per login.** `purge_expired_sessions()` ada tapi belum dipanggil terjadwal.

---

## 6. Verifikasi

Unit + integration: 188 test lulus, termasuk 11 test integration terhadap PostgreSQL nyata (pencabutan, kedaluwarsa, penonaktifan akun, keunikan email case-insensitive, reset password).

Terhadap gateway hidup:

```text
POST /api/v1/auth/login          200, token 43 karakter, expires_at +8 jam
GET  /api/v1/auth/me             200 dengan token
GET  /api/v1/dashboard/summary   200 dengan token, 401 tanpa token
POST /api/v1/auth/logout         204, token yang sama sesudahnya 401
5x password salah                401,401,401,401,429
```

---

**Related:** [[06_Platform_Security_Requirements]] · [[01_Control_Panel_Overview]] · [[01_PostgreSQL_Schema]] · [[Implement_Command_Center_Dashboard]] · [[Open_Decisions_Carried_Forward]]
