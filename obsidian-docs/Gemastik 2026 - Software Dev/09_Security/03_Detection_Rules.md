# Detection Rules

> **Scope:** MVP · **Status:** Planned

Detection Rules adalah mekanisme deteksi **deterministik**, dikelola terpisah dari ML inference.

---

## 1. Jenis Rule

| Jenis | Contoh |
| :--- | :--- |
| Keyword rule | Frasa modus penipuan yang berulang |
| Domain rule | Domain yang diketahui jahat atau mirip situs resmi |
| URL rule | Pola URL, shortener, redirect mencurigakan |
| Risk threshold | Batas skor yang memicu klasifikasi ancaman |
| Pattern detection | Pola struktural (nomor rekening + urgensi + tautan) |
| Repeated offender rule | Pengirim yang berulang kali memicu deteksi |
| Rate limiting | Volume pesan tidak wajar dari satu sumber |
| Allowlist / blocklist | Pengecualian dan pemblokiran eksplisit indicator |

---

## 2. Rules dan ML Saling Melengkapi

Ini bukan pilihan salah satu:

| | Detection Rules | ML Classification |
| :--- | :--- | :--- |
| Sifat | Deterministik | Probabilistik |
| Bisa dijelaskan | Ya, per rule | Sebatas confidence + indicator |
| Kecepatan perubahan | Instan (ubah data) | Butuh training + evaluasi + promosi |
| Kelemahan | Rapuh terhadap variasi bahasa | Bisa salah dengan yakin, sulit diaudit per kasus |
| Kekuatan | Presisi tinggi pada pola yang diketahui | Menangkap modus baru yang tidak tercover rule |

Keduanya menyuplai Risk Assessment. Security Policy yang memutuskan aksi ([[02_Security_Policies]]).

Konsekuensi penting: **rule bisa diubah tanpa retraining model**, dan **model bisa diperbarui tanpa menyentuh rule**. Kedua jalur perbaikan berjalan independen.

---

## 3. Siklus Hidup Rule

```text
DRAFT → ACTIVE → (DISABLED | ARCHIVED)
```

Setiap rule punya: nama, jenis, kondisi, bobot/severity, status, pembuat, waktu perubahan terakhir.

---

## 4. Yang Harus Bisa Dilihat Operator

- Rule mana yang cocok pada sebuah pesan ([[04_Message_Inspection]] — field *Applied detection rule*)
- Berapa kali sebuah rule terpicu dalam periode tertentu
- Berapa banyak yang berakhir ditandai false positive

Rule dengan false positive tinggi adalah kandidat perbaikan pertama — sinyal ini datang dari operator feedback ([[04_Datasets_and_Operator_Feedback]]).

---

## 5. Auditability

Perubahan rule adalah perubahan postur keamanan: tercatat siapa, kapan, dan isi perubahannya ([[05_Audit_Logs]]).

---

**Related:** [[02_Security_Policies]] · [[03_Threat_Monitoring]] · [[02_Data_Pipeline]] · [[02_ML_Control_Center_Overview]]
