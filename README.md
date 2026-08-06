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
| `postgres` | Relational store — audit logs, fraud blacklist, subscriptions |
| `qdrant` | Vector DB — RAG fact-knowledge similarity search |
| `redis` | Celery broker + rate limiting |
| `frontend-dashboard` | Next.js analytics dashboard |

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

Documentation (`obsidian-docs/`) is ahead of code — backend/ML implementation has not started yet. See `obsidian-docs/.../05_Audit/` for the current architecture audit and open decisions (LLM provider, dependency toolchain, security/retention policy) that should be resolved before writing gateway or ML-service code.
