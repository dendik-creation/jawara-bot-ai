# Users & Risk Management

> **Scope:** MVP · **Status:** Planned — belum ada tabel users/roles maupun kode auth di repo.

Dua populasi berbeda dikelola di sini, dan dokumentasi harus tidak mencampurnya:

| Populasi | Siapa | Dikelola untuk |
| :--- | :--- | :--- |
| **Operator platform** | Pengguna Control Panel | Autentikasi, RBAC, audit |
| **WhatsApp end user** | Pengirim/penerima pesan yang dianalisis | Risk profile, blocklist, riwayat ancaman |

---

## 1. Kapabilitas (WhatsApp end user)

- User list
- User status
- User activity
- Threat history
- Risk profile
- Threat frequency
- Security status
- Block / unblock

Identitas end user disimpan dalam bentuk `user_hash` (SHA-256 bersalt), bukan nomor telepon mentah ([[01_Threat_Model_and_Data_Protection]]).

### Risk profile

Skor risiko per user diturunkan dari frekuensi ancaman, severity tertinggi, kategori dominan, dan riwayat aksi (mis. sudah pernah diblokir). Formula spesifik **belum diputuskan** — yang sudah ditetapkan adalah bahwa skor ini turunan data, bukan input manual.

---

## 2. RBAC (operator platform)

Role awal:

| Role | Cakupan |
| :--- | :--- |
| `SUPER_ADMIN` | Semua, termasuk manajemen role dan promosi model ke produksi |
| `ADMIN` | Manajemen user platform, policy, detection rules, sesi WhatsApp |
| `SECURITY_ANALYST` | Investigasi threat/incident, aksi keamanan, operator feedback |
| `OPERATOR` | Operasi harian: sesi WhatsApp, acknowledge alert, tindakan dasar |
| `VIEWER` | Baca-saja |

### Batas otorisasi yang diharapkan

| Kemampuan | SUPER_ADMIN | ADMIN | SECURITY_ANALYST | OPERATOR | VIEWER |
| :--- | :---: | :---: | :---: | :---: | :---: |
| Lihat dashboard & threat | ✔ | ✔ | ✔ | ✔ | ✔ |
| Lihat isi pesan penuh | ✔ | ✔ | ✔ | — | — |
| Aksi threat (allow/warn/block/escalate) | ✔ | ✔ | ✔ | — | — |
| Kelola incident | ✔ | ✔ | ✔ | — | — |
| Acknowledge / assign alert | ✔ | ✔ | ✔ | ✔ | — |
| Kelola sesi WhatsApp | ✔ | ✔ | — | ✔ | — |
| Ubah security policy / detection rules | ✔ | ✔ | — | — | — |
| Upload Knowledge Base | ✔ | ✔ | ✔ | — | — |
| Kelola dataset & mulai training job | ✔ | ✔ | ✔ | — | — |
| Promosikan model ke produksi | ✔ | — | — | — | — |
| Kelola user & role platform | ✔ | ✔ | — | — | — |
| Lihat audit log | ✔ | ✔ | ✔ | — | — |

Tabel ini adalah **usulan**, bukan implementasi. Penegakannya wajib di sisi server; menyembunyikan menu di frontend bukan kontrol akses.

---

## 3. Blocklist

Blocklist end user adalah keputusan keamanan: perlu alasan, punya jejak audit, dan bisa dicabut. Blocklist berbasis indicator (domain/URL) dikelola terpisah di [[03_Detection_Rules]].

---

**Related:** [[01_Control_Panel_Overview]] · [[06_Platform_Security_Requirements]] · [[05_Audit_Logs]] · [[03_Threat_Monitoring]] · [[01_Threat_Model_and_Data_Protection]]
