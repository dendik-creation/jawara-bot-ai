# Model Evaluation

> **Scope:** MVP · **Status:** Implemented

Evaluasi adalah gerbang antara "model selesai dilatih" dan "model boleh melayani produksi".

---

## 1. Metrik

| Metrik | Kenapa penting untuk JAWARA |
| :--- | :--- |
| Accuracy | Gambaran umum, tapi menyesatkan bila kelas timpang |
| Precision | Precision rendah = banyak pesan aman diblokir, pengguna kehilangan kepercayaan |
| Recall | Recall rendah = ancaman lolos, kerugian nyata pada korban |
| F1 Score | Keseimbangan precision dan recall |
| Confusion Matrix | Menunjukkan kelas mana yang tertukar dengan kelas mana |
| False Positive Rate | Biaya operasional: setiap FP jadi pekerjaan operator |
| False Negative Rate | Biaya keamanan: setiap FN adalah korban potensial |

Untuk platform keamanan, FP dan FN tidak setara. Trade-off di antara keduanya adalah keputusan produk, bukan keputusan otomatis dari angka F1.

---

## 2. Dataset Evaluasi

Evaluasi dijalankan terhadap **dataset validasi/test yang tetap**, bukan sampel acak yang berubah tiap kali. Tanpa dataset tetap, perbandingan antar versi model tidak bermakna.

Persyaratan:

- Versi dataset evaluasi tercatat bersama hasilnya.
- Tidak ada kebocoran antara data latih dan data evaluasi ([[04_Datasets_and_Operator_Feedback]] §4).

---

## 3. Perbandingan Antar Versi

```text
                 v1.1      v1.2

Accuracy         91.8%     94.2%
Precision        92.1%     95.8%
Recall           90.7%     97.1%
F1               91.4%     96.4%
```

Angka di atas adalah ilustrasi format, bukan hasil pengukuran nyata. Belum ada model JAWARA yang dilatih atau dievaluasi.

---

## 4. Gerbang Promosi

> **Deployment ke produksi mensyaratkan evaluasi yang berhasil.**

Yang harus ditetapkan sebelum model pertama dipromosikan:

- Ambang minimum per metrik (khususnya recall dan false positive rate)
- Aturan "tidak boleh lebih buruk dari model produksi saat ini" pada metrik kunci
- Siapa yang berwenang menyetujui promosi ([[07_Users_and_Risk]])

**Open question:** nilai ambang belum ditentukan. KPI ≥95% akurasi di [[03_Pitching_Narrative]] adalah target produk, bukan gerbang rilis yang sudah diformalkan.

---

## 5. Setelah Produksi

Evaluasi tidak berhenti di rilis. Sinyal lanjutan datang dari operator feedback: tingkat false positive nyata, kategori yang paling sering dikoreksi, dan pesan yang lolos deteksi. Sinyal ini yang mengisi siklus perbaikan berikutnya ([[08_Continuous_Improvement_Loop]]).

---

**Related:** [[05_Training_Jobs]] · [[07_Model_Registry_and_Deployment]] · [[04_Datasets_and_Operator_Feedback]] · [[02_ML_Control_Center_Overview]]
