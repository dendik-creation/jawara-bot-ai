# Alert Center

> **Scope:** MVP · **Status:** Planned

Pusat pengelolaan alert. Alert adalah **notifikasi yang butuh perhatian operator**, berbeda dari Threat (temuan) dan Incident (unit kerja investigasi).

---

## 1. Severity

| Severity | Arti |
| :--- | :--- |
| `LOW` | Informasional, tidak butuh tindakan segera |
| `MEDIUM` | Perlu ditinjau dalam waktu wajar |
| `HIGH` | Perlu ditangani segera |
| `CRITICAL` | Butuh respons langsung |

---

## 2. Kapabilitas

- Alert list
- Alert detail
- Acknowledge
- Assign
- Resolve
- Escalate
- Alert history

---

## 3. Contoh Alert

```text
CRITICAL
Phishing campaign detected

HIGH
Repeated malicious URL detection

HIGH
Abnormal message activity

MEDIUM
WhatsApp session disconnected

MEDIUM
ML Service unavailable
```

Dua contoh terakhir menunjukkan bahwa alert tidak hanya soal ancaman eksternal — kesehatan platform juga memicu alert ([[08_Service_Health]]).

---

## 4. Siklus Hidup Alert

```text
NEW → ACKNOWLEDGED → (RESOLVED | ESCALATED)
```

- `ACKNOWLEDGED` berarti ada yang melihat, bukan berarti selesai.
- `ESCALATED` biasanya berarti alert dinaikkan menjadi Incident ([[05_Incident_Management]]).
- `RESOLVED` wajib punya alasan singkat.

---

## 5. Sumber Alert

| Sumber | Contoh |
| :--- | :--- |
| Security policy dengan aksi `ALERT`/`ESCALATE` | Risk score tinggi pada kategori kritis |
| Threshold agregat | Lonjakan deteksi dari satu domain/pengirim |
| Kesehatan platform | Sesi WhatsApp terputus, ML Service tidak tersedia |
| Operasi AI/ML | Training job gagal, evaluasi model di bawah ambang |

---

## 6. Anti-Kebisingan

Alert yang terlalu berisik akan diabaikan, dan itu kegagalan keamanan. Minimal yang perlu ada: deduplikasi alert sejenis dalam jendela waktu, dan pengelompokan alert satu kampanye menjadi satu incident.

**Open question:** ambang deduplikasi dan jendela waktunya belum ditentukan.

---

**Related:** [[05_Incident_Management]] · [[02_Security_Policies]] · [[08_Service_Health]] · [[05_Audit_Logs]] · [[02_Command_Center]]
