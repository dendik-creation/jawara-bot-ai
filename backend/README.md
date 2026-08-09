# JAWARA Backend — FastAPI Gateway + Celery Worker

Two processes, one image: the gateway (`app.main:app`) acks WAHA webhooks in
<200ms, the worker (`app.worker`) does everything slow. Full docs live in
`obsidian-docs/Gemastik 2026 - Software Dev/`; run instructions in `07_How_to_Run`.

## Layout

```
app/
  api/v1/endpoints/   webhook, health, Control Panel read APIs
  clients/            ml_client, safe_browsing, virustotal, waha_client
  core/               config, auth, logging, rate limiter, redis client, cache, hashing
  db/                 SQL migrations + runner
  pipeline/           normalizer, url_extractor, intent_router, url_safety, orchestrator
  schemas/            pydantic models (webhook payload, queue envelope)
  scripts/            seed_facts, ingest_knowledge
  services/           queue producer, message_log (audit), dashboard, health probes
  vector/             Qdrant collection setup
  worker/             celery app + tasks
```

`pipeline/orchestrator.py` owns the ordering of the whole message flow —
preprocess, classify, verify, assess risk, generate, dispatch, audit. Each stage
owns its own logic and is allowed to degrade; the orchestrator records what
degraded rather than failing the job.

## Commands

```bash
pip install -r requirements-dev.txt

python -m app.db.migrate                    # apply Postgres schema (idempotent)
python -m app.vector.qdrant_setup           # create Qdrant collection (idempotent)
python -m app.scripts.seed_facts            # demo fact_items from the vault examples
python -m app.scripts.ingest_knowledge      # embed them into Qdrant via ML Service

uvicorn app.main:app --reload --port 8000   # gateway
celery -A app.worker worker --loglevel=info # worker (add --pool=solo on Windows)

pytest -q -m "not integration"              # unit tests only
pytest -q                                   # + integration (needs live infra)
```

Integration tests skip themselves when Postgres/Redis/Qdrant are unreachable, so
`pytest -q` stays green without infra — it does not hide real failures.

## Conventions

- **Config comes from env vars only** (`app/core/config.py`); no literals in code.
  The repo-root `.env` is read by absolute path, so a process started from
  `backend/` sees exactly what Compose sees. Connection strings left unset are
  derived from their components (`POSTGRES_*`, `REDIS_PORT`, `ML_SERVICE_PORT`)
  against `localhost`; real env vars still win, which is how Compose injects
  in-network hostnames.
- **Logs are JSON, one object per line.** Pass context via `extra=`, never string
  interpolation — `waha_message_id` is the correlation ID from webhook through
  queue to worker.
- **The gateway never imports worker task functions.** Jobs are dispatched by name
  (`celery_app.send_task`) so ML dependencies stay out of the request path.
- **Nothing slow goes in the webhook handler.** OCR/RAG/LLM work belongs in the
  worker; the ack budget is 200ms.
- **No inference code lives here.** Embeddings, retrieval and generation belong to
  `ml-service/`, reached only through `app/clients/ml_client.py`. No other module
  may know its URL or payload shape.
- **Degrade, don't fail.** A missing threat-intel key, an unreachable ML Service,
  or an undeliverable reply each produce a recorded degradation and a written
  audit row — not an exception. `UNKNOWN` is a verdict, and it never renders as
  "safe".
- **The pipeline is not retried.** Celery's retry would re-run generation and
  dispatch, so a job that already replied would reply twice. Only a malformed
  envelope and genuinely unexpected exceptions reach the retry policy.
