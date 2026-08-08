# Audit Logs

> **Scope:** MVP · **Status:** Planned — tabel audit aksi operator belum ada. Yang sudah ada di schema adalah `message_logs` (jejak pemrosesan pesan), bukan jejak aksi administratif.

Audit log mencatat **tindakan sensitif** di platform: siapa melakukan apa, terhadap apa, kapan, dan hasilnya.

---

## 1. Informasi Wajib per Entri

| Field | Keterangan |
| :--- | :--- |
| Actor | Siapa yang melakukan (user platform atau sistem) |
| Action | Tindakan yang dilakukan |
| Target | Objek yang terkena (policy, user, sesi, model, dataset) |
| Timestamp | Waktu kejadian |
| Result | `SUCCESS` / `FAILED` / `DENIED` |
| Metadata relevan | Nilai lama vs baru, alasan, ID terkait |
| Sumber request | IP/user agent/correlation ID, bila relevan |

---

## 2. Contoh

```text
ADMIN
Changed detection policy
SUCCESS

SECURITY_ANALYST
Marked message as false positive
SUCCESS

OPERATOR
Restarted WhatsApp session
SUCCESS
```

---

## 3. Tindakan yang Wajib Diaudit

| Domain | Tindakan |
| :--- | :--- |
| Akses | Login, logout, login gagal, perubahan role |
| Keamanan | Ubah security policy, ubah detection rule, ubah allowlist/blocklist |
| Threat/Incident | Aksi threat, perubahan state incident, penutupan sebagai false positive |
| Pengguna | Blokir/buka blokir end user, perubahan user platform |
| WhatsApp | Connect, disconnect, restart sesi |
| Data sensitif | Melihat isi pesan penuh (bila kebijakan privasi mengharuskannya) |
| AI/ML | Upload knowledge, hapus knowledge, validasi dataset, mulai/batalkan training job, promosi model ke produksi, arsip model |

---

## 4. Sifat Append-Oriented

- Entri audit **tidak boleh** di-update atau dihapus lewat jalur aplikasi.
- Tidak ada endpoint edit/delete audit di API.
- Hak tulis ke tabel audit dibatasi; hak baca mengikuti RBAC ([[07_Users_and_Risk]]).
- Retensi audit log dipisahkan dari retensi isi pesan — audit boleh bertahan lebih lama justru karena tidak menyimpan isi percakapan.

**Open question:** durasi retensi audit dan mekanisme perlindungan tulis (constraint DB, role DB terpisah, atau keduanya) belum diputuskan.

---

## 5. Hubungan dengan `message_logs`

| | `message_logs` | Audit log |
| :--- | :--- | :--- |
| Mencatat | Pemrosesan pesan oleh sistem | Tindakan manusia/administratif |
| Aktor | Pipeline | Operator platform |
| Berisi isi pesan | Ya (`extracted_text`, plaintext, retensi belum ditetapkan) | Tidak |

Keduanya dibutuhkan dan tidak saling menggantikan. Lihat [[01_PostgreSQL_Schema]] dan [[01_Threat_Model_and_Data_Protection]].

---

**Related:** [[02_Security_Policies]] · [[07_Users_and_Risk]] · [[01_Threat_Model_and_Data_Protection]] · [[01_PostgreSQL_Schema]] · [[06_Platform_Security_Requirements]]
