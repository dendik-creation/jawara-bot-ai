# JAWARA Backend — FastAPI Gateway + Celery Worker

Two processes, one image: the gateway (`app.main:app`) acks WAHA webhooks in
<200ms, the worker (`app.worker`) does everything slow. Full docs live in
`obsidian-docs/Gemastik 2026 - Software Dev/`; run instructions in `07_How_to_Run`.

## Layout

```
app/
  api/v1/endpoints/   webhook + health routes
  core/               config, auth, logging, rate limiter, redis client, hashing
  db/                 SQL migrations + runner
  schemas/            pydantic models (webhook payload, queue envelope)
  services/           queue producer, health probes
  vector/             Qdrant collection setup
  worker/             celery app + tasks
```

## Commands

```bash
pip install -r requirements-dev.txt

python -m app.db.migrate                    # apply Postgres schema (idempotent)
python -m app.vector.qdrant_setup           # create Qdrant collection (idempotent)

uvicorn app.main:app --reload --port 8000   # gateway
celery -A app.worker worker --loglevel=info # worker (add --pool=solo on Windows)

pytest -q -m "not integration"              # unit tests only
pytest -q                                   # + integration (needs live infra)
```

Integration tests skip themselves when Postgres/Redis/Qdrant are unreachable, so
`pytest -q` stays green without infra — it does not hide real failures.

## Conventions

- **Config comes from env vars only** (`app/core/config.py`); no literals in code.
- **Logs are JSON, one object per line.** Pass context via `extra=`, never string
  interpolation — `waha_message_id` is the correlation ID from webhook through
  queue to worker.
- **The gateway never imports worker task functions.** Jobs are dispatched by name
  (`celery_app.send_task`) so ML dependencies stay out of the request path.
- **Nothing slow goes in the webhook handler.** OCR/RAG/LLM work belongs in the
  worker; the ack budget is 200ms.
