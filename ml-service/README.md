# JAWARA ML Service

Standalone inference service. The gateway reaches it only through
`backend/app/clients/ml_client.py`; the frontend never reaches it at all.

Why it is separate, and what it is forbidden from doing, is settled in
`obsidian-docs/Gemastik 2026 - Software Dev/02_Architecture/04_ML_Service.md`.

## Layout

```
app/
  api/v1/endpoints/  health (liveness + readiness), inference, knowledge
  core/              config, structured errors, internal-key auth, JSON logging
  embeddings/        Embedder interface + hashing (offline) + OpenAI
  llm/               prompt assembly, output validator, providers
  models/registry.py name+version -> loaded instance, built once at startup
  rag/               Qdrant retrieval and upsert
  schemas/           the { request_id, payload, metadata } wire contract
prompts/
  system_prompt.txt  verbatim copy of the vault's system prompt
```

## Endpoints

| Endpoint | Status |
|---|---|
| `POST /v1/embed` | text → vectors |
| `POST /v1/rag-query` | embed + filtered similarity search, `unverified` below threshold |
| `POST /v1/generate` | four-section WhatsApp reply, validated before it is returned |
| `POST /v1/kb/upsert` | embed + store fact items (point id = `fact_items.id`) |
| `GET /v1/health` | liveness, unauthenticated (container healthcheck) |
| `GET /v1/ready` | readiness — models loaded **and** Qdrant reachable |
| `POST /v1/classify` | returns `model_not_available`; no classifier has been trained yet |
| `POST /v1/ocr`, `/v1/train`, `/v1/evaluate` | not implemented |

Every inference response carries `model_version`. Errors are
`{error_code, message, retryable}`, never a bare 500 — the gateway branches on
`retryable` to choose between retry and fallback.

## Providers

Both default to an offline implementation so the service runs with no API key,
no GPU, and no internet:

| Config | Default | Alternatives |
|---|---|---|
| `EMBEDDING_PROVIDER` | `hash` — deterministic, **lexical not semantic** | `openai` (`text-embedding-3-small`) |
| `LLM_PROVIDER` | `template` — deterministic composer | `anthropic` (chosen for production), `openai` |

A provider configured without its key does not crash startup: it falls back,
records why in `degraded_reasons`, and stays ready. A pipeline that cannot answer
at all is worse than one that answers from a template.

## Commands

```bash
uv sync                          # create/refresh .venv from uv.lock

uv run uvicorn app.main:app --reload --port 9000

uv run pytest -q -m "not integration"   # unit only
uv run pytest -q                        # + live Qdrant (skips if unreachable)
```

Integration tests create and drop their own throwaway collection; they never
write to `fact_knowledge_base`.

## Conventions

- **`uv` is the only dependency toolchain**, same as the gateway: `pyproject.toml`
  plus `uv.lock`, installed from the lock in the image.
- **Models load once per process, at startup.** That cost is the reason this
  service exists separately from the gateway.
- **Qdrant belongs to this service.** The gateway never computes or compares a
  vector.
- **The system prompt is a file, not an f-string.** A test parses the vault
  document and fails if the two copies drift.
- **Retrieved knowledge is data, not instruction.** It enters the prompt inside a
  labelled block with an explicit instruction not to obey it.
