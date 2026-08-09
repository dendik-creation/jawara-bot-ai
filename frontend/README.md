# JAWARA Control Panel

Next.js (App Router) + Tailwind + shadcn/ui. Operator-facing **Control &
Monitoring Center**, not an analytics dashboard — see
`obsidian-docs/Gemastik 2026 - Software Dev/08_Dashboard/01_Control_Panel_Overview.md`.

## Screens

| Route | Screen |
|---|---|
| `/login` | Operator sign-in (email + password) |
| `/` | Command Center — volume, severity, population, Live Activity, service health, recent items |
| `/system/service-health` | Basic per-service availability |

Everything except `/login` lives in the `(panel)` route group: signed in, inside
the sidebar shell.

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

It is inlined into the client bundle at build time. In Docker it arrives as a
**build arg**, not runtime environment — changing it means rebuilding the image,
not restarting the container.

There is no dashboard key any more. `NEXT_PUBLIC_DASHBOARD_KEY` was removed with
`DASHBOARD_API_KEY`: a secret compiled into a browser bundle is readable by
anyone who loads the page, so it was never a credential. Access is an operator
session token obtained at `/login`.

Create the first account on the gateway side:

```bash
cd backend
uv run python -m app.scripts.create_operator --email you@example.com --name "Nama"
```

## Rules this app follows

- **The gateway is the only backend.** No call from the browser to WAHA, Qdrant,
  Redis, PostgreSQL, or the ML Service. `lib/api.ts` is the only module that
  knows a URL.
- **The client-side guard is a redirect, not a security boundary.** The real one
  is `require_operator` on the gateway, which every screen's data passes
  through. `RequireAuth` only decides what to render while the session is
  checked. The token lives in `localStorage` behind `lib/session.ts` — one
  module knows the storage key, so moving to cookies later is one file.
- **Never show a fabricated number.** A metric with no data source renders
  "belum tersedia"; it never renders `0`. A zero is indistinguishable from a
  quiet day and will be read as one.
- **Never show message content.** The dashboard endpoints do not return
  `extracted_text`, and these screens display metadata and classification only.
- **Polling is temporary.** The live-activity transport (SSE / WebSocket /
  polling) is still an open decision, so the simplest option is used and marked
  as such in the UI. Replacing it means replacing `hooks/use-polling.ts`.
