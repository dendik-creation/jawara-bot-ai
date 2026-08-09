# JAWARA Control Panel

Next.js (App Router) + Tailwind + shadcn/ui. Operator-facing **Control &
Monitoring Center**, not an analytics dashboard — see
`obsidian-docs/Gemastik 2026 - Software Dev/08_Dashboard/01_Control_Panel_Overview.md`.

## Screens

| Route | Screen |
|---|---|
| `/` | Command Center — volume, severity, population, Live Activity, service health, recent items |
| `/system/service-health` | Basic per-service availability |

Every other navigation entry is specified but not built. It renders as a disabled
row with a "belum tersedia" badge rather than a link to an empty page — a menu
that clicks through to nothing reads as broken software.

## Commands

```bash
bun install
bun dev -- -p 3001   # 3000 collides with WAHA's published port
bun run lint
bun run typecheck
bun run build
```

## Configuration

| Variable | Purpose |
|---|---|
| `NEXT_PUBLIC_API_URL` | FastAPI gateway base URL (default `http://localhost:8000`) |
| `NEXT_PUBLIC_DASHBOARD_KEY` | Sent as `X-Dashboard-Key` when the gateway requires it |

Both are inlined into the client bundle at build time. In Docker they arrive as
**build args**, not runtime environment — changing them means rebuilding the
image, not restarting the container.

## Rules this app follows

- **The gateway is the only backend.** No call from the browser to WAHA, Qdrant,
  Redis, PostgreSQL, or the ML Service. `lib/api.ts` is the only module that
  knows a URL.
- **Never show a fabricated number.** A metric with no data source renders
  "belum tersedia"; it never renders `0`. A zero is indistinguishable from a
  quiet day and will be read as one.
- **Never show message content.** The dashboard endpoints do not return
  `extracted_text`, and these screens display metadata and classification only.
- **Polling is temporary.** The live-activity transport (SSE / WebSocket /
  polling) is still an open decision, so the simplest option is used and marked
  as such in the UI. Replacing it means replacing `hooks/use-polling.ts`.
