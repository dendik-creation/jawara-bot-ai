# Incident Management

> **Scope:** MVP · **Status:** Planned
> Korelasi incident otomatis lintas sinyal adalah **Post-MVP**. MVP: grouping yang dibuat/dikonfirmasi operator.

Incident mengelompokkan event keamanan yang saling terkait menjadi satu unit investigasi.

---

## 1. Isi Sebuah Incident

- Beberapa pesan
- Beberapa pengguna
- Beberapa indicator
- URL/domain terkait
- Kategori ancaman terkait
- Timeline
- Aksi operator
- Catatan investigasi

---

## 2. Incident Lifecycle

```text
OPEN
  ↓
INVESTIGATING
  ↓
CONTAINED
  ↓
RESOLVED
```

State terminal alternatif:

```text
FALSE_POSITIVE
```

| State | Arti |
| :--- | :--- |
| `OPEN` | Incident dibuat, belum ada yang menangani |
| `INVESTIGATING` | Operator sedang menelusuri |
| `CONTAINED` | Penyebaran dihentikan (blokir, policy diperketat), akar masalah belum tuntas |
| `RESOLVED` | Selesai ditangani |
| `FALSE_POSITIVE` | Terbukti bukan ancaman; pesan-pesan terkait layak masuk antrean feedback |

---

## 3. Contoh

```text
INC-2026-0001

Phishing Campaign
Severity: CRITICAL

Affected Users: 27
Messages: 143
Indicators: 4
```

---

## 4. Aksi pada Incident

| Aksi | Catatan |
| :--- | :--- |
| Assign | Tetapkan penanggung jawab |
| Tambah/lepas pesan atau user | Memperbaiki cakupan incident |
| Tambah catatan investigasi | Bagian dari timeline, tidak bisa dihapus diam-diam |
| Ubah severity | Tercatat di audit log dengan nilai lama dan baru |
| Escalate | Menaikkan alert terkait |
| Tutup (`RESOLVED` / `FALSE_POSITIVE`) | Wajib disertai alasan |

Semua aksi tercatat di [[05_Audit_Logs]].

---

## 5. Hubungan dengan Threat dan Alert

```text
Message  →  Threat  →  (opsional) Incident
                   ↘
                     Alert
```

- Satu Threat bisa berdiri sendiri tanpa Incident.
- Satu Incident selalu punya minimal satu Threat.
- Alert adalah notifikasi; Incident adalah unit kerja. Keduanya tidak saling menggantikan ([[04_Alert_Center]]).

---

**Related:** [[03_Threat_Monitoring]] · [[04_Message_Inspection]] · [[04_Alert_Center]] · [[07_Users_and_Risk]] · [[05_Product_Scope_and_Roadmap]]
