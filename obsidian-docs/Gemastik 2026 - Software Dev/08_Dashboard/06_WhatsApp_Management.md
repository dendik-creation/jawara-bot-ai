# WhatsApp Management

> **Scope:** MVP · **Status:** Partial — container WAHA berjalan dan event `session.status` sudah diterima gateway; UI manajemen sesi belum ada.

Layar untuk mengelola sesi WhatsApp yang dipakai JAWARA.

---

## 1. Kapabilitas

- Session list
- Session status
- Connection state
- Device information
- QR pairing (bila didukung engine)
- Connect
- Disconnect
- Restart / reconnect
- Session health
- Session activity

---

## 2. Aturan Batas

```text
Control Panel  →  FastAPI  →  WAHA        ✔
Control Panel  →  WAHA                    ✘
```

- Semua operasi sesi lewat FastAPI Gateway.
- Internal WAHA tidak diekspos ke frontend: bentuk payload WAHA dinormalkan oleh gateway, dashboard WAHA tidak di-embed, kredensial WAHA tidak pernah sampai ke browser.
- Aksi connect/disconnect/restart adalah operasi sensitif — wajib RBAC dan wajib tercatat di audit log ([[05_Audit_Logs]]).

---

## 3. Session State

| State | Arti |
| :--- | :--- |
| `STARTING` | Sesi sedang dijalankan |
| `SCAN_QR` | Menunggu pairing QR |
| `CONNECTED` | Terhubung ke WhatsApp |
| `DISCONNECTED` | Terputus |
| `FAILED` | Gagal, butuh intervensi operator |

Penamaan final mengikuti state yang benar-benar dikirim engine WAHA; gateway memetakannya ke set di atas agar UI tidak bergantung pada detail engine.

---

## 4. Efek Operasional

- Sesi terputus memicu alert severity `MEDIUM` ([[04_Alert_Center]]).
- Status sesi tampil di Command Center sebagai bagian "WhatsApp status" ([[02_Command_Center]]).
- Sesi tersimpan di named volume `waha_sessions`; restart container tidak meminta scan QR ulang ([[02_Prod_Environtment]]).

---

**Related:** [[05_Integrations]] · [[01_Control_Panel_Overview]] · [[08_Service_Health]] · [[02_Prod_Environtment]]
