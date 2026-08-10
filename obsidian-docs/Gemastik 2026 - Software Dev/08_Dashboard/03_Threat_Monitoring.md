# Threat Monitoring

> **Scope:** MVP · **Status:** Planned

Layar tempat operator memantau seluruh ancaman yang terdeteksi platform.

---

## 1. Kapabilitas

- Threat timeline
- Threat severity
- Threat category
- Detection status
- Action taken
- Related message
- Related user
- Related indicators
- Threat history
- Threat filtering
- Threat search

---

## 2. Kategori Ancaman Awal

| Kategori | Contoh |
| :--- | :--- |
| Phishing | Tautan tiruan situs bank / portal bansos |
| Scam | Undian palsu, salah transfer, pinjaman ilegal |
| Social Engineering | Manipulasi berbasis relasi/urgensi ("ini Om, tolong transfer dulu") |
| Malicious Link | URL dengan reputasi buruk atau redirect mencurigakan |
| Impersonation | Mengaku sebagai instansi, bank, atau anggota keluarga |
| Spam | Broadcast massal tanpa muatan penipuan langsung |
| Other Suspicious Activity | Terdeteksi anomali tapi tidak masuk kategori di atas |

Kategori bersifat *extensible* — penambahan kategori adalah perubahan data + rule, bukan perubahan arsitektur.

> Kategori historis pipeline (`HEALTH_HOAX`, `FINANCIAL_FRAUD`, `GENERAL_NEWS`, `PHISHING_LINK`, `FILE_APK`) masih hidup di enum `category_enum` PostgreSQL. Pemetaan ke kategori ancaman di atas **sudah dipetakan** 2026-08-10 — dua level, bukan penggabungan enum. Detail: [[Open_Decisions_Carried_Forward]] §2.4.

---

## 3. Threat Lifecycle

```text
DETECTED
    ↓
ANALYZED
    ↓
ACTIONED
    ↓
RESOLVED
```

| State | Arti |
| :--- | :--- |
| `DETECTED` | Sinyal awal masuk (rules dan/atau ML menandai) |
| `ANALYZED` | Klasifikasi, risk score, dan indicator lengkap |
| `ACTIONED` | Security policy sudah menerapkan aksi |
| `RESOLVED` | Operator menutup ancaman (benar-benar ditangani atau ditandai false positive) |

---

## 4. Aksi Operator

| Aksi | Efek |
| :--- | :--- |
| Allow | Pesan dilewatkan; ancaman ditutup sebagai tidak berbahaya |
| Warn | Peringatan dikirim ke pengguna terkait |
| Block | Pesan/pengirim diblokir sesuai policy |
| Escalate | Dinaikkan menjadi incident dan/atau alert severity lebih tinggi |
| Confirm threat | Konfirmasi klasifikasi AI benar → masuk antrean feedback |
| Mark false positive | Koreksi klasifikasi AI → masuk antrean feedback |

Dua aksi terakhir adalah pintu masuk Human-in-the-Loop. Keduanya **tidak** langsung mengubah model — hanya menghasilkan record feedback yang harus divalidasi dulu ([[04_Datasets_and_Operator_Feedback]]).

Setiap aksi operator tercatat di audit log ([[05_Audit_Logs]]).

---

## 5. Filter & Pencarian

Minimal: rentang waktu, severity, kategori, state, aksi yang diambil, user terkait, indicator (domain/URL/nomor), dan versi model yang mengklasifikasi.

---

**Related:** [[01_Control_Panel_Overview]] · [[04_Message_Inspection]] · [[05_Incident_Management]] · [[02_Security_Policies]] · [[03_Detection_Rules]]
