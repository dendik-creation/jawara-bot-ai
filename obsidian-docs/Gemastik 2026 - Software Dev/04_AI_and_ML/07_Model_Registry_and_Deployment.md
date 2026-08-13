# Model Registry & Deployment Lifecycle

> **Scope:** MVP · **Status:** Implemented

Registry adalah catatan resmi setiap model: versinya, asalnya, hasil evaluasinya, dan statusnya.

---

## 1. Versi Model

```text
JAWARA-v1.0
JAWARA-v1.1
JAWARA-v1.2
```

Setiap versi menyimpan minimal: artefak model, dataset + versi dataset yang melatihnya, konfigurasi training, hasil evaluasi, job yang menghasilkannya, dan waktu pembuatan.

---

## 2. State Model

```text
CANDIDATE → VALIDATED → PRODUCTION → ARCHIVED
```

| State | Arti |
| :--- | :--- |
| `CANDIDATE` | Baru dihasilkan training job, belum divalidasi |
| `VALIDATED` | Lolos evaluasi dan tinjauan, layak dipromosikan |
| `PRODUCTION` | Sedang melayani inference |
| `ARCHIVED` | Tidak dipakai lagi, tetap disimpan untuk penelusuran |

---

## 3. Alur Deployment

```text
Training
    ↓
Evaluation
    ↓
Candidate
    ↓
Validation
    ↓
Production
```

### Dua aturan yang tidak bisa ditawar

1. **Model baru tidak otomatis menjadi model produksi.**
2. **Promosi ke produksi harus eksplisit dan terkontrol** — tindakan manusia, oleh role yang berwenang, tercatat di audit log.

---

## 4. Kenapa Promosi Manual

Model deteksi keamanan yang berubah otomatis berarti perilaku pemblokiran berubah tanpa ada yang menyetujuinya. Konsekuensinya nyata: pesan sah diblokir massal, atau ancaman lolos, tanpa jejak keputusan siapa pun.

---

## 5. Rollback

Model produksi sebelumnya tetap `ARCHIVED`, bukan dihapus. Rollback adalah mempromosikan kembali versi lama — operasi yang sama-sama eksplisit dan sama-sama diaudit.

Karena setiap hasil inference menyimpan `model_version` ([[04_ML_Service]]), dampak sebuah versi bisa ditelusuri mundur setelah rollback.

---

## 6. Yang Ditampilkan di Layar Models

- Daftar versi model dan state-nya
- Model produksi saat ini
- Kandidat yang menunggu validasi
- Ringkasan metrik evaluasi per versi ([[06_Model_Evaluation]])
- Asal-usul: training job, dataset, versi dataset
- Aksi: validate, promote to production, archive, rollback

Setiap aksi di atas adalah entri audit ([[05_Audit_Logs]]).

---

## 7. Integritas Artefak

Artefak model diverifikasi sebelum dimuat (checksum + asal yang diketahui). Artefak yang tidak dikenal registry tidak boleh dimuat oleh ML Service ([[06_Platform_Security_Requirements]] §4).

---

**Related:** [[06_Model_Evaluation]] · [[05_Training_Jobs]] · [[04_ML_Service]] · [[08_Continuous_Improvement_Loop]] · [[05_Audit_Logs]]
