# Security Policies

> **Scope:** MVP · **Status:** Planned

Security Policy menentukan **bagaimana JAWARA merespons** ancaman yang terdeteksi. Policy adalah lapisan keputusan; deteksi hanya menyuplai sinyal.

---

## 1. Bentuk Policy

```text
IF suspicious_url = true
AND risk_score >= 0.85
THEN BLOCK
```

Struktur umum: kondisi (kombinasi sinyal) → aksi tunggal.

---

## 2. Aksi Policy

| Aksi | Efek |
| :--- | :--- |
| `ALLOW` | Pesan dilewatkan, tetap dicatat |
| `WARN` | Peringatan dikirim ke pengguna terkait |
| `BLOCK` | Pesan/pengirim diblokir sesuai konfigurasi |
| `ALERT` | Alert dibuat untuk operator ([[04_Alert_Center]]) |
| `ESCALATE` | Dinaikkan menjadi incident dan/atau severity lebih tinggi |

---

## 3. Yang Bisa Dikonfigurasi

- Risk threshold per kategori ancaman
- Policy URL/domain
- Policy keyword
- Policy khusus user tertentu
- Rate limit
- Respons otomatis
- Allowlist
- Blocklist

---

## 4. Urutan Evaluasi

Urutan menentukan hasil, jadi harus eksplisit:

```text
1. Allowlist        → cocok? ALLOW, evaluasi berhenti
2. Blocklist        → cocok? BLOCK, evaluasi berhenti
3. Policy user-spesifik
4. Policy kategori + threshold
5. Policy default    → aksi fallback bila tidak ada yang cocok
```

Bila beberapa policy pada tingkat yang sama cocok, aksi paling ketat menang (`BLOCK` > `ESCALATE` > `ALERT` > `WARN` > `ALLOW`).

**Open question:** apakah prioritas antar-policy dibuat eksplisit (field `priority`) atau implisit dari urutan di atas — belum diputuskan.

---

## 5. Policy vs Detection Rules

| | Security Policy | Detection Rule |
| :--- | :--- | :--- |
| Menjawab | "Kalau begini, lakukan apa?" | "Apakah ini mencurigakan?" |
| Output | Aksi | Sinyal/indicator |
| Konsumen | Pipeline aksi | Risk assessment |

Keduanya bisa memakai bahan yang mirip (keyword, domain), tapi perannya berbeda dan dikelola di layar terpisah ([[03_Detection_Rules]]).

---

## 6. Auditability

Policy adalah kontrol keamanan, jadi:

- Setiap perubahan policy tercatat: siapa, kapan, nilai lama, nilai baru.
- Setiap evaluasi yang menghasilkan aksi non-`ALLOW` tercatat bersama policy mana yang memicunya.
- Riwayat versi policy dapat ditelusuri.

Lihat [[05_Audit_Logs]].

---

**Related:** [[03_Detection_Rules]] · [[03_Threat_Monitoring]] · [[04_Alert_Center]] · [[02_Data_Pipeline]] · [[05_Audit_Logs]]
