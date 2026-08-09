# Implement Command Center Dashboard

## Status

Done

## Priority

Medium

## Sprint

Sprint 1

## Deadline

2026-08-10

## Scope

MVP — Command Center + Live Activity ([[05_Product_Scope_and_Roadmap]])

## Description

Bangun shell Control Panel (Next.js App Router + shadcn/ui) dengan layar **Command Center**: metrik keamanan operasional, ringkasan terkini, dan status service dasar. Ini adalah *Control & Monitoring Center*, bukan dashboard analitik.

## Background

Sebelumnya task ini bernama "Implement Basic Analytics Dashboard" dengan sasaran message volume / intent breakdown / latency. Sasarannya diubah agar sejalan dengan scope produk: yang dibutuhkan operator adalah visibilitas keamanan, bukan analitik. Analytics Service tersendiri dan Infrastructure Analytics **Deferred** ([[05_Product_Scope_and_Roadmap]] §6).

## Deliverables

- Scaffold Control Panel + shell navigasi sesuai [[01_Control_Panel_Overview]]
- Layar Command Center: messages processed, threats detected, critical threats, active users, active WA sessions
- Ringkasan terkini: recent threats / incidents / alerts (kosong-state yang jujur bila datanya belum ada)
- Basic service health: FastAPI, ML Service, WAHA, PostgreSQL, Redis, Qdrant ([[08_Service_Health]])
- Seluruh data diambil lewat FastAPI Gateway, bukan langsung ke datastore mana pun

## Dependencies

- [[Create Audit Logging]]
- Endpoint agregasi di gateway (belum ada task-nya)

## Acceptance Criteria

- Dashboard hanya membaca data agregat/anonim, tidak pernah `extracted_text` mentah
- Tidak ada panggilan langsung dari browser ke WAHA / Qdrant / Redis / PostgreSQL / ML Service
- Metrik yang datanya belum tersedia ditampilkan sebagai kosong/belum tersedia, bukan angka palsu
- Layout responsif di desktop dan tablet
- Tidak ada entri navigasi "Analytics" atau "Infrastructure Analytics"

## Related Documentation

- [[02_Command_Center]]
- [[01_Control_Panel_Overview]]
- [[08_Service_Health]]
- [[05_Product_Scope_and_Roadmap]]

## Notes

Heatmap spasial B2G adalah **Post-MVP** — schema belum punya field wilayah dan keputusan privasinya belum diambil. Transport live activity feed (SSE/WebSocket/polling) juga belum diputuskan; kalau task ini dikerjakan sebelum keputusan itu, mulai dengan polling dan tandai sebagai sementara.

## Implementation (2026-08-08)

Gateway: `GET /api/v1/dashboard/{summary,activity,recent}`, `GET /api/v1/system/services`, `GET /api/v1/whatsapp/sessions` (`backend/app/services/dashboard.py`). Agregasi langsung dari PostgreSQL — tanpa Analytics Service.

Frontend: shell navigasi sesuai [[01_Control_Panel_Overview]] §2 (tanpa entri Analytics), layar Command Center, layar Service Health, polling lewat `hooks/use-polling.ts`.

`extracted_text` tidak pernah di-`SELECT`. Metrik tanpa data dirender "belum tersedia", bukan `0`. Incidents dan alerts melaporkan `available: false` dengan alasannya.

Celah yang harus diketahui: **belum ada auth operator/RBAC** — hanya `DASHBOARD_API_KEY` sebagai tambalan. Jangan ekspos gateway ke internet sebelum Fase 2. Detail: [[Implement_Command_Center_Dashboard]].

> **Pembaruan 2026-08-09:** auth operator sudah ada dan `DASHBOARD_API_KEY` dihapus ([[Implement_Operator_Auth]]). RBAC tetap belum ada.
