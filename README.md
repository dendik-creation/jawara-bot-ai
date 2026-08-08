# JAWARA — Jaringan Asisten WhatsApp Anti-Rekayasa & Ancaman

WhatsApp-native anti-fraud/anti-hoax assistant (Smart Family Guard). Self-hosted, containerized, built for Gemastik 2026 Software Development. Full product docs live in [`obsidian-docs/`](./obsidian-docs/Gemastik%202026%20-%20Software%20Dev/00_Index.md) — this file covers the monorepo/dev side only.

## Repository structure

Single Git repository, root as the only `.git`. Monorepo, not a multi-repo submodule setup.

```
/
├── backend/          # FastAPI gateway (webhook intake, auth, orchestration)
├── frontend/          # Next.js + shadcn/ui dashboard
├── obsidian-docs/      # Product/architecture docs (Obsidian vault)
├── docker-compose.yml  # Local/self-hosted service orchestration
├── .env.example
└── .gitignore
```

`backend/` currently has no ML inference code by design — see `obsidian-docs/.../05_Audit/02_Architecture_Audit_ML_Decoupling.md` for the planned `ml-service/` split (independent service, gateway calls it over REST via `backend/app/clients/ml_client.py`).

## Services (docker-compose.yml)

| Service | Role |
|---|---|
| `waha` | Self-hosted WhatsApp HTTP API engine — receives/sends WhatsApp messages |
| `api-gateway` | FastAPI backend — webhook intake, auth, orchestration |
| `celery-worker` | Async task processing (OCR, RAG, LLM calls, offloaded from the webhook path) |
| `postgres` | Primary relational store — message logs, fact knowledge metadata, subscriptions (security/AI-ML domains planned) |
| `qdrant` | Vector DB — knowledge chunks, semantic/RAG retrieval |
| `redis` | Celery broker + rate limiting + transient state |
| `frontend-dashboard` | Next.js Control Panel (scaffold only so far) |

## Development setup

**Backend** (`backend/`): Python 3.14+, dependency management not yet finalized between `pyproject.toml` (uv) and `requirements.txt` (pip) — pick one before adding app code (see audit report).

**Frontend** (`frontend/`): uses **bun**, not npm/yarn (lockfile is `bun.lock`).

```bash
cd frontend
bun install
bun run dev
```

## Docker usage

```bash
cp .env.example .env   # fill in real values — WAHA creds, Postgres creds
docker compose up -d --build
```

All services have health checks; `api-gateway` and `frontend-dashboard` wait on their dependencies via `condition: service_healthy`.

## Status

Documentation (`obsidian-docs/`) is ahead of code. What runs today: webhook intake with `X-Api-Key` auth, Redis rate limiting, Redis queue + Celery worker (pipeline stages still empty seams), PostgreSQL migrations, Qdrant collection bootstrap. What does not exist yet: `ml-service/`, the Control Panel screens, and every security/AI-ML domain table.

Feature scope (MVP / Post-MVP / Optional / Deferred) and per-feature implementation status live in `obsidian-docs/.../01_Overview/05_Product_Scope_and_Roadmap.md`. Open decisions: LLM provider, backend dependency toolchain (`uv` vs `pip`), and the retention policy for plaintext message content.
