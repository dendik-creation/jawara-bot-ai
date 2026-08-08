# Service Health

> **Scope:** MVP · **Status:** Partial — `GET /health` gateway sudah melaporkan ketersediaan PostgreSQL dan Redis.

Halaman System → Service Health menampilkan **ketersediaan dasar** setiap service. Tidak lebih.

---

## 1. Yang Dipantau

```text
FastAPI       ● HEALTHY
ML Service    ● HEALTHY
WAHA          ● HEALTHY
PostgreSQL    ● HEALTHY
Redis         ● HEALTHY
Qdrant        ● HEALTHY
```

| Service | Cara cek | Status sekarang |
| :--- | :--- | :--- |
| FastAPI Gateway | proses melayani `GET /health` | Implemented |
| PostgreSQL | probe koneksi dari gateway | Implemented |
| Redis | probe `PING` dari gateway | Implemented |
| Qdrant | endpoint healthz / collection info | Planned |
| WAHA | status engine + status sesi | Planned |
| ML Service | readiness (model sudah dimuat), bukan sekadar liveness | Planned |

Contoh respons gateway saat ini:

```json
{"status":"ok","dependencies":{"database":true,"redis":true}}
```

Saat ada dependency yang gagal, `status` menjadi `degraded`.

---

## 2. Yang **Bukan** Bagian Ini

Berikut ini **Deferred** dan tidak boleh masuk halaman ini atau navigasi MVP ([[05_Product_Scope_and_Roadmap]] §6):

- Analitik CPU jangka panjang
- Analitik RAM jangka panjang
- Tren penggunaan disk
- BI performa infrastruktur
- Analytics Service tersendiri
- Analisis tren infrastruktur lanjutan
- BI operasional lanjutan

Pembedanya sederhana: halaman ini menjawab "apakah service-nya jalan sekarang", bukan "bagaimana tren resource-nya sebulan terakhir".

---

## 3. Liveness vs Readiness

Untuk ML Service, keduanya harus dibedakan: proses yang sudah hidup tapi belum selesai memuat model **tidak** boleh dilaporkan HEALTHY, karena orchestrator akan mengirim trafik ke container yang belum siap ([[04_ML_Service]] §6).

---

## 4. Kaitan dengan Alert

Service yang turun memicu alert, bukan hanya perubahan warna di halaman ini:

| Kondisi | Alert |
| :--- | :--- |
| ML Service tidak tersedia | `MEDIUM` |
| Sesi WhatsApp terputus | `MEDIUM` |
| PostgreSQL / Redis tidak tersedia | `HIGH` |

Lihat [[04_Alert_Center]].

---

**Related:** [[01_Control_Panel_Overview]] · [[02_Command_Center]] · [[04_ML_Service]] · [[02_Prod_Environtment]] · [[05_Product_Scope_and_Roadmap]]
