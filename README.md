# JAWARA — Jaringan Asisten WhatsApp Anti-Rekayasa & Ancaman

WhatsApp-native anti-fraud/anti-hoax assistant (Smart Family Guard). Self-hosted, containerized, built for Gemastik 2026 Software Development. Full product docs live in [`obsidian-docs/`](./obsidian-docs/Gemastik%202026%20-%20Software%20Dev/00_Index.md) — this file covers the monorepo/dev side only.

## Repository structure

Single Git repository, root as the only `.git`. Monorepo, not a multi-repo submodule setup.

```
/
├── backend/            # FastAPI gateway + Celery worker (intake, rules, orchestration)
├── ml-service/         # Standalone inference service (embeddings, RAG, generation)
├── frontend/           # Next.js + shadcn/ui Control Panel
├── obsidian-docs/      # Product/architecture docs (Obsidian vault)
├── docker-compose.yml  # Local/self-hosted service orchestration
├── .env.example
└── .gitignore
```

`backend/` holds no inference code by design: embeddings, retrieval and generation live in `ml-service/`, and the gateway reaches it through exactly one module (`backend/app/clients/ml_client.py`). Rationale in `obsidian-docs/.../02_Architecture/04_ML_Service.md`.

## Services (docker-compose.yml)

| Service | Role |
|---|---|
| `waha` | Self-hosted WhatsApp HTTP API engine — receives/sends WhatsApp messages |
| `api-gateway` | FastAPI backend — webhook intake, auth, orchestration, Control Panel APIs |
| `celery-worker` | Async pipeline: preprocess → rules → verify → generate → dispatch → audit |
| `ml-service` | Inference: embeddings, RAG retrieval, LLM response generation, knowledge upsert |
| `postgres` | Primary relational store — message logs, fact knowledge, subscriptions |
| `qdrant` | Vector DB — knowledge embeddings, semantic/RAG retrieval |
| `redis` | Celery broker + rate limiting + threat-intel cache + transient state |
| `frontend-dashboard` | Next.js Control Panel — Command Center, Service Health |

`ml-service` is health-checked on **readiness** (`/v1/ready`, models loaded), not liveness — an orchestrator that routes traffic to a container still loading weights produces first requests that fail for no visible reason.

## Development setup

**Backend** (`backend/`) and **ML Service** (`ml-service/`): Python 3.14, managed by **uv** — `pyproject.toml` declares the dependencies, `uv.lock` pins them, and both Dockerfiles install from that same lock. There is no `requirements.txt`.

```bash
cd backend        # or ml-service
uv sync
uv run pytest -q
```

**Frontend** (`frontend/`): uses **bun**, not npm/yarn (lockfile is `bun.lock`).

```bash
cd frontend
bun install
bun run dev -- -p 3001   # 3000 collides with WAHA
```

## Docker usage

```bash
cp .env.example .env   # fill in real values — WAHA creds, Postgres creds, ML_SERVICE_API_KEY
docker compose up -d --build

docker exec jawara-gateway python -m app.db.migrate
docker exec jawara-gateway python -m app.vector.qdrant_setup
docker exec jawara-gateway python -m app.scripts.seed_facts
docker exec jawara-gateway python -m app.scripts.ingest_knowledge
```

All services have health checks; `api-gateway` and `frontend-dashboard` wait on their dependencies via `condition: service_healthy`.

The stack runs with **no third-party API keys at all**. Absent keys are a configuration state, not an error: threat-intel verdicts degrade to `UNKNOWN`, and the LLM falls back to a deterministic composer that still satisfies the four-section reply contract.

## Status

The detection pipeline runs end to end — webhook in, WhatsApp reply out, audit row written. Verified against the live stack: intent classification, RAG retrieval at 0.87 similarity against real Qdrant, risk assessment, response generation, and a `message_logs` row that survives webhook retries without duplicating.

What does not exist yet: a trained classification model (`/v1/classify` answers `model_not_available` and the pipeline falls back to deterministic Detection Rules), OCR, graded security policy actions, operator auth/RBAC, and every threat/incident/alert domain table.

Feature scope (MVP / Post-MVP / Optional / Deferred) and per-feature implementation status live in `obsidian-docs/.../01_Overview/05_Product_Scope_and_Roadmap.md`. Sprint 1 completion notes, including what could not be verified and why, are in `obsidian-docs/.../06_Tasks/Task_Note/`.

Open decisions: backend dependency toolchain (`uv` vs `pip`), live-activity transport, retention policy for plaintext message content, and the WAHA send timeout versus the 3-second end-to-end target. The LLM provider decision is closed — Anthropic Claude Haiku, with the contract kept provider-agnostic.
