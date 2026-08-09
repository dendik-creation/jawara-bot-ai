# Command Center & Live Activity

> **Scope:** MVP · **Status:** Implemented (2026-08-08) — layar Command Center dan Live Activity berjalan, membaca data nyata lewat endpoint agregasi gateway. Blok yang sumber datanya belum ada (incidents, alerts) menyatakan dirinya belum tersedia, bukan menampilkan nol. Detail dan batasannya: [[Implement_Command_Center_Dashboard]].

Command Center adalah dashboard utama JAWARA. Fokusnya **visibilitas keamanan operasional**: apa yang sedang terjadi sekarang, seberapa parah, dan apakah sistemnya sendiri sehat.

Command Center **bukan** sistem analitik infrastruktur. Tren CPU/RAM/disk jangka panjang berada di luar scope ([[05_Product_Scope_and_Roadmap]] §6).

---

## 1. Kapabilitas

| Blok | Isi |
| :--- | :--- |
| Volume | Total pesan diproses, ancaman terdeteksi |
| Severity | Distribusi severity ancaman |
| Populasi | Active users, active WhatsApp sessions |
| Terkini | Recent threats, recent incidents, recent alerts, recent security events |
| Kesehatan | Status ML Service, status WhatsApp, basic service health |
| Realtime | Live activity feed |

---

## 2. Contoh Tampilan

```text
Command Center

Messages Processed       12,421
Threats Detected            843
Critical Threats             21
Active Users                391
Active WA Sessions            4

ML Service              HEALTHY
WhatsApp                HEALTHY
```

Angka di atas adalah ilustrasi format, bukan data nyata.

---

## 3. Live Activity

> **Scope:** MVP · **Status:** Planned

Feed event keamanan operasional secara realtime. Bukan log aplikasi mentah — hanya event yang berarti bagi operator.

```text
18:02:31
THREAT_DETECTED
Risk: HIGH
Type: Phishing
Action: BLOCKED

18:02:29
MESSAGE_ANALYZED
Risk: LOW
Action: ALLOWED
```

Tipe event yang ditampilkan:

| Event | Kapan muncul |
| :--- | :--- |
| `MESSAGE_ANALYZED` | Sebuah pesan selesai melewati pipeline analisis |
| `THREAT_DETECTED` | Klasifikasi menghasilkan ancaman di atas threshold |
| `ACTION_APPLIED` | Security policy menerapkan aksi (`WARN`/`BLOCK`/`ESCALATE`) |
| `INCIDENT_UPDATED` | Incident dibuat atau berubah state |
| `ALERT_RAISED` | Alert baru muncul |
| `SESSION_STATE_CHANGED` | Sesi WhatsApp connect/disconnect |

Batasan privasi: feed menampilkan metadata dan klasifikasi. Isi pesan hanya tampil sesuai kebijakan privasi yang berlaku di [[04_Message_Inspection]] dan [[01_Threat_Model_and_Data_Protection]].

---

## 4. Sumber Data

| Blok | Sumber | Endpoint |
| :--- | :--- | :--- |
| Volume, severity, populasi | PostgreSQL, agregasi oleh FastAPI Gateway (bukan service analitik terpisah) | `GET /api/v1/dashboard/summary` |
| Live activity | `message_logs` terbaru — metadata dan klasifikasi saja, tanpa isi pesan | `GET /api/v1/dashboard/activity` |
| Recent threats / incidents / alerts | PostgreSQL; incidents & alerts melaporkan `available: false` (tabelnya belum ada) | `GET /api/v1/dashboard/recent` |
| Service health | Probe konkuren enam service dari gateway ([[08_Service_Health]]) | `GET /api/v1/system/services` |
| Active WA sessions | Daftar sesi WAHA yang dinormalisasi gateway | `GET /api/v1/whatsapp/sessions` |

**Open question (masih terbuka):** transport untuk live feed belum ditentukan. Implementasi sementara memakai **polling** — pilihan paling sederhana yang tidak menuntut channel Redis pub/sub tambahan. Respons `/dashboard/activity` menyertakan `"transport": "polling"` dan UI menyebut intervalnya, supaya sifat sementaranya terlihat.

---

**Related:** [[01_Control_Panel_Overview]] · [[03_Threat_Monitoring]] · [[04_Alert_Center]] · [[08_Service_Health]] · [[05_Product_Scope_and_Roadmap]]
