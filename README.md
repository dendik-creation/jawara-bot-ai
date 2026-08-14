# JAWARA: Jaringan Asisten WhatsApp Anti-Rekayasa & Ancaman

WhatsApp-native anti-fraud/anti-hoax assistant (Smart Family Guard). Self-hosted, containerized, built for Gemastik 2026 Software Development. Full product docs live in [`obsidian-docs/`](./obsidian-docs/Gemastik%202026%20-%20Software%20Dev/00_Index.md); this file covers the monorepo/dev side only.

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
| `waha` | Self-hosted WhatsApp HTTP API engine, receives/sends WhatsApp messages |
| `api-gateway` | FastAPI backend: webhook intake, auth, orchestration, Control Panel APIs |
| `celery-worker` | Async pipeline: preprocess, rules, verify, generate, dispatch, audit |
| `ml-service` | Inference: embeddings, RAG retrieval, LLM response generation, knowledge upsert |
| `postgres` | Primary relational store: message logs, fact knowledge, subscriptions |
| `qdrant` | Vector DB: knowledge embeddings, semantic/RAG retrieval |
| `redis` | Celery broker + rate limiting + threat-intel cache + transient state |
| `frontend-dashboard` | Next.js Control Panel: operator login, Command Center, Service Health |

`ml-service` is health-checked on **readiness** (`/v1/ready`, models loaded), not liveness. An orchestrator that routes traffic to a container still loading weights produces first requests that fail for no visible reason.

## Setup

Full, step-by-step setup guides live in [`obsidian-docs/.../07_How_to_Run/`](./obsidian-docs/Gemastik%202026%20-%20Software%20Dev/07_How_to_Run/). This section only orients you toward the right guide, follow the linked doc for actual commands, troubleshooting, and env var reference.

### Local development (hybrid: infra in Docker, app on CLI)

Infra (WAHA, Postgres, Redis, Qdrant, ml-service) runs in Docker Compose; backend (FastAPI) and frontend (Next.js) run directly on your machine for hot-reload.

- **Backend** (`backend/`) and **ML Service** (`ml-service/`): Python 3.14, managed by **uv** (`pyproject.toml` + `uv.lock`, no `requirements.txt`).
- **Frontend** (`frontend/`): uses **bun**, not npm/yarn (lockfile is `bun.lock`).

Full guide, including `.env` setup, database bootstrap, Celery worker, and troubleshooting: [`01_Dev_Environtment.md`](./obsidian-docs/Gemastik%202026%20-%20Software%20Dev/07_How_to_Run/01_Dev_Environtment.md).

### Full stack via Docker Compose (production / VPS deployment)

All 9 services run as containers, orchestrated by the root `docker-compose.yml`. Every service except WAHA's pairing port binds to `127.0.0.1` only, nothing is public by default, and this repo ships no reverse proxy or TLS termination of its own (bring your own).

Full guide, including credential rotation, bootstrap, backups, and security notes: [`02_Prod_Environtment.md`](./obsidian-docs/Gemastik%202026%20-%20Software%20Dev/07_How_to_Run/02_Prod_Environtment.md).

### Training the threat classifier (optional)

The bot works without this: Detection Rules alone cover the pipeline. Training only adds an extra ML risk signal, and only after a model is explicitly promoted to `PRODUCTION`.

Full guide, including dataset prep and the ≥80% accuracy workflow: [`03_How_To_Train_AI.md`](./obsidian-docs/Gemastik%202026%20-%20Software%20Dev/07_How_to_Run/03_How_To_Train_AI.md).

## Status

**Working end to end:** webhook in, intent classification, RAG retrieval (0.87 similarity against real Qdrant), risk assessment, response generation, WhatsApp reply out, audit row written (survives webhook retries without duplicating).

**Fully wired, no mock data:** operator auth, and all Control Panel domains (threats, alerts, incidents, detection rules, policies, users, knowledge base, datasets, training jobs, model evaluation). Every page in `frontend/app/(panel)/` calls a real backend endpoint.

**Threat classifier is real but optional:** TF-IDF + LogisticRegression (`ml-service/app/models/classifier.py`). Training, evaluation, and classification all run for real against a checksum-verified model artifact. It only affects live traffic after an operator explicitly promotes a model to `PRODUCTION` (never automatic). No real labeled corpus exists yet, `app.scripts.seed_dataset_samples` only seeds a synthetic dataset good enough to prove the pipeline works, not production accuracy.

**Not built yet:** OCR, enforcement of security policies against live messages (the CRUD/lifecycle exists, matching policies to messages is a separate follow-up), and operator RBAC (every operator currently has equal access, roles are Phase 3).

**Still undecided:** backend dependency toolchain (`uv` vs `pip`), live-activity transport, retention policy for plaintext message content, and the WAHA send timeout versus the 3-second end-to-end target. LLM provider is decided: Anthropic Claude Haiku, contract kept provider-agnostic.

Details: feature scope and per-feature status in `obsidian-docs/.../01_Overview/05_Product_Scope_and_Roadmap.md`; Sprint 1 completion notes in `obsidian-docs/.../06_Tasks/Task_Note/`.

## License

JAWARA's own code is [MIT-licensed](./LICENSE). Third-party dependency, container
image, and API license inventory — including flagged items like Redis's post-7.4
relicensing — lives in [`docs/licenses/THIRD_PARTY_LICENSES.md`](./docs/licenses/THIRD_PARTY_LICENSES.md).
