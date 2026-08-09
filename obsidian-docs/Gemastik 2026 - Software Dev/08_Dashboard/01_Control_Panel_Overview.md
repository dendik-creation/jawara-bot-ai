# Control Panel — Overview & Navigation

Control Panel JAWARA adalah **Control & Monitoring Center** untuk operator keamanan, bukan sekadar dashboard analitik. Fungsinya: melihat apa yang terjadi, memahami kenapa sistem memutuskan sesuatu, dan mengambil tindakan.

> **Status:** Partial (2026-08-08). Shell navigasi di §2 sudah dibangun, dengan dua layar hidup: **Command Center** (termasuk Live Activity) dan **System → Service Health**. Entri navigasi yang layarnya belum ada dirender non-aktif dengan badge "belum tersedia" — bukan tautan ke halaman kosong, dan bukan disembunyikan.
>
> **Belum ada autentikasi operator maupun RBAC.** Sementara ini `DASHBOARD_API_KEY` mengunci endpoint Control Panel bila diisi. Itu mengautentikasi deployment, bukan orang; gateway tidak boleh diekspos ke internet sebelum Fase 2 ([[Implement_Command_Center_Dashboard]]).

---

## 1. Area Fungsional

```text
JAWARA
│
├── Command Center
├── Threat Monitoring
├── Message Inspection
├── Incident Management
├── WhatsApp Management
├── Users & Risk
├── Security
│   ├── Policies
│   ├── Detection Rules
│   ├── Alerts
│   └── Audit Logs
│
├── AI / ML
│   ├── Overview
│   ├── Knowledge Base
│   ├── Datasets
│   ├── Training Jobs
│   ├── Models
│   └── Evaluation
│
└── System
    └── Basic Service Health
```

---

## 2. Navigasi yang Diusulkan

```text
Command Center

Monitoring
├── Live Activity
├── Threats
├── Messages
└── Incidents

WhatsApp
├── Sessions
└── Devices

Users
├── Users
├── Risk Profiles
└── Blocklist

Security
├── Policies
├── Detection Rules
├── Alerts
└── Audit Logs

AI / ML
├── Overview
├── Knowledge Base
├── Datasets
├── Training Jobs
├── Models
└── Evaluation

System
└── Service Health
```

**Tidak ada** entri "Analytics" atau "Infrastructure Analytics" di navigasi MVP — keduanya Deferred ([[05_Product_Scope_and_Roadmap]] §6).

---

## 3. Peta Layar ke Dokumen

| Area navigasi | Dokumen |
| :--- | :--- |
| Command Center, Live Activity | [[02_Command_Center]] |
| Threats | [[03_Threat_Monitoring]] |
| Messages | [[04_Message_Inspection]] |
| Incidents | [[05_Incident_Management]] |
| WhatsApp Sessions & Devices | [[06_WhatsApp_Management]] |
| Users, Risk Profiles, Blocklist | [[07_Users_and_Risk]] |
| Security → Policies | [[02_Security_Policies]] |
| Security → Detection Rules | [[03_Detection_Rules]] |
| Security → Alerts | [[04_Alert_Center]] |
| Security → Audit Logs | [[05_Audit_Logs]] |
| AI / ML → Overview | [[02_ML_Control_Center_Overview]] |
| AI / ML → Knowledge Base | [[03_Knowledge_Base]] |
| AI / ML → Datasets | [[04_Datasets_and_Operator_Feedback]] |
| AI / ML → Training Jobs | [[05_Training_Jobs]] |
| AI / ML → Models | [[07_Model_Registry_and_Deployment]] |
| AI / ML → Evaluation | [[06_Model_Evaluation]] |
| System → Service Health | [[08_Service_Health]] |

---

## 4. Aturan Frontend

- Seluruh data dan aksi lewat FastAPI Gateway. Tidak ada panggilan langsung ke ML Service, WAHA, Qdrant, Redis, atau PostgreSQL dari browser.
- Navigasi sadar-role: item yang tidak diizinkan role pengguna tidak ditampilkan, **dan** tetap ditolak di sisi server. Menyembunyikan menu bukan kontrol akses ([[07_Users_and_Risk]]).
- Setiap aksi yang mengubah state keamanan (ubah policy, blokir user, restart sesi, promosi model) menghasilkan entri audit ([[05_Audit_Logs]]).

---

**Related:** [[01_System_Architecture]] · [[05_Product_Scope_and_Roadmap]] · [[02_Command_Center]] · [[06_Platform_Security_Requirements]]
