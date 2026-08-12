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
| `frontend-dashboard` | Next.js Control Panel — operator login, Command Center, Service Health |

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

# Control Panel account — nothing can sign in until this exists. Reads
# OPERATOR_EMAIL / OPERATOR_NAME / OPERATOR_PASSWORD from .env; re-running is
# safe, an existing account is left untouched.
docker exec jawara-gateway python -m app.scripts.create_operator
```

All services have health checks; `api-gateway` and `frontend-dashboard` wait on their dependencies via `condition: service_healthy`.

The stack runs with **no third-party API keys at all**. Absent keys are a configuration state, not an error: threat-intel verdicts degrade to `UNKNOWN`, and the LLM falls back to a deterministic composer that still satisfies the four-section reply contract.

## Production / VPS deployment

Every service except `waha`'s dashboard port binds to `127.0.0.1` — Postgres, Redis, Qdrant, `api-gateway`, `ml-service`, and `frontend-dashboard` are reachable from the host machine (for debugging) but never the public internet, regardless of firewall. Redis in particular has **no authentication mechanism in this codebase at all**, so this binding is the only thing standing between it and the open internet if it were published.

This repo ships no reverse proxy or TLS termination — bring your own (e.g. join the frontend/api-gateway containers to an existing Nginx Proxy Manager network and point proxy hosts at `jawara-dashboard:3000` / `jawara-gateway:8000` by container name, over Docker's internal DNS, not a published host port).

Before exposing this publicly:
- Rotate every `changeme`/default-looking credential in `.env` — WAHA dashboard password, Postgres password, `ML_SERVICE_API_KEY`, `USER_HASH_SALT`, operator password.
- Set `CORS_ALLOW_ORIGINS` to the real frontend origin(s) and `NEXT_PUBLIC_API_URL` to the real API origin — the latter is baked in at Docker **build** time (a build arg, not just runtime env), so `frontend-dashboard` needs `docker compose up -d --build frontend-dashboard` after changing it, not just a restart.
- `./scripts/backup.sh` — Postgres dump + Qdrant snapshot to `backups/<timestamp>/` (gitignored). No scheduling built in; wire it into cron/systemd-timer yourself.

## Status

The detection pipeline runs end to end — webhook in, WhatsApp reply out, audit row written. Verified against the live stack: intent classification, RAG retrieval at 0.87 similarity against real Qdrant, risk assessment, response generation, and a `message_logs` row that survives webhook retries without duplicating.

Operator auth and the threat/alert/incident/detection-rule/policy/user/knowledge/dataset/training-job/model-evaluation domain tables all exist, with backend endpoints and a matching Control Panel page for each (`frontend/app/(panel)/`) — no mock data, every page is wired to a real endpoint.

The threat classifier (`ml-service/app/models/classifier.py`, TF-IDF + LogisticRegression) is real: `/v1/train`, `/v1/evaluate`, `/v1/classify` all run genuine training/scoring against a checksum-verified artifact, and `app.pipeline.orchestrator` calls it as an additive risk signal — but only once an operator has explicitly promoted a model to `PRODUCTION` on the Models page (never automatic, per `07_Model_Registry_and_Deployment.md` §3-4). No real labeled corpus exists yet — `app.scripts.seed_dataset_samples` seeds a synthetic Indonesian dataset good enough to prove the pipeline, not production-grade accuracy.

What does not exist yet: OCR, enforcement of security policies against live messages (CRUD/lifecycle exists; matching policies to messages is a separate follow-up — see `app.services.policies`), and operator RBAC (auth is email+password/bearer session only, every operator has equal access; roles are Phase 3).

Feature scope (MVP / Post-MVP / Optional / Deferred) and per-feature implementation status live in `obsidian-docs/.../01_Overview/05_Product_Scope_and_Roadmap.md`. Sprint 1 completion notes, including what could not be verified and why, are in `obsidian-docs/.../06_Tasks/Task_Note/`.

Open decisions: backend dependency toolchain (`uv` vs `pip`), live-activity transport, retention policy for plaintext message content, and the WAHA send timeout versus the 3-second end-to-end target. The LLM provider decision is closed — Anthropic Claude Haiku, with the contract kept provider-agnostic.
