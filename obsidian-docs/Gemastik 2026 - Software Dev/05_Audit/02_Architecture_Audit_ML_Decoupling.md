# Architecture Audit — ML Service Decoupling

> **Status: Historis.** Audit ini adalah rekaman analisis **saat backend masih kosong** (satu file Python, tanpa route, tanpa worker). Kondisi itu sudah berubah: gateway kini punya webhook intake, auth, rate limiter, queue, worker, migrasi PostgreSQL, dan bootstrap Qdrant.
>
> **Arsitektur yang berlaku sekarang ada di [[01_System_Architecture]] dan [[04_ML_Service]]** — dokumen ini tidak boleh dibaca sebagai deskripsi keadaan terkini.
>
> Yang tetap berlaku dari audit ini: rekomendasi pemisahan ML Service, kontrak REST gateway↔ML (§12), kepemilikan Qdrant oleh ML Service (§8), dan pembedaan readiness vs liveness (§13) — semuanya sudah dipindahkan ke [[04_ML_Service]] sebagai dokumen aktif.
>
> Yang sudah usang di dokumen ini: klaim "backend has no code" (§0, §1, §3), rename `cucudigital-*` (sudah selesai), dan urutan build §19 langkah 1–6 yang sebagian sudah dikerjakan.

> Scope: full repo (`backend/`, `frontend/`, `docker-compose.yml`, `obsidian-docs/`). Audit only — no source restructuring applied. Exception: `frontend/Dockerfile` switched npm to bun per explicit request (mechanical, zero risk, not part of the architecture migration itself).

---

## 0. Ground Truth Check (read this first)

Docs (`02_Architecture/*`) describe a 4-layer system: WAHA to FastAPI Gateway to Celery/Redis to Qdrant/Postgres, with OCR, RAG, LLM, VirusTotal, CekRekening all living **inside** the FastAPI/Celery process. Code does not match docs:

- `backend/src/backend/__init__.py` is the only Python file in the repo. No `app/`, no `main.py`, no routes, no models, no Celery task, no ML code at all.
- `backend/Dockerfile` runs `uvicorn app.main:app` — that module does not exist. Image does not build a working container today.
- `backend/requirements.txt` (fastapi, uvicorn, celery, redis) and `backend/pyproject.toml` (`dependencies = []`, uv-based) are two disconnected dependency systems; neither lists qdrant-client, llama-index, easyocr, or an LLM SDK, despite docs mandating all four.
- `frontend/` is an unmodified `create-next-app` + shadcn scaffold (`app/page.tsx`, `app/layout.tsx`, one `button.tsx` component). No dashboard, no API calls, no data fetching.
- `docker-compose.yml` matches docs for infra shape (waha, api-gateway, celery-worker, postgres, qdrant, redis, frontend-dashboard); container/network/DB naming was still `cucudigital-*` at audit time despite the project rename to jawara recorded in `.agents/project/overview.md` — fixed this pass (see §12), noted here for traceability.

**Consequence for this audit:** there is no existing ML inference logic to "pull out" of the backend — because there is no backend. This changes the nature of the migration from *refactor-in-place* to *greenfield build with the target shape decided up front*. That is the good news: this is the cheapest possible time to enforce the gateway/ML-service boundary, because there is no working code that has to be safely split without downtime. Treat the "migration roadmap" below as a **build order**, not a lift-and-shift.

---

## 1. Current Architecture Assessment

| Dimension | State |
|---|---|
| Backend | Empty skeleton. Two conflicting dependency manifests. Dockerfile references nonexistent module. |
| Frontend | Default Next.js 16.2.6 + React 19.2.4 scaffold (docs claim Next 14 — stale). shadcn/base-ui wired, one button component. |
| ML/AI | Exists only as prose in `obsidian-docs`. Zero code. |
| Data layer | Postgres 16 + Qdrant declared in compose; no schema migration tooling present (no alembic, no init SQL) despite `03_Database/01_PostgreSQL_Schema.md` defining `fact_items`, `message_logs`, `user_subscriptions`, `fraud_blacklists`. |
| Messaging | WAHA container wired correctly in compose with health check and webhook URL env pointing at gateway. |
| Orchestration | Docker Compose only. No k8s, no CI/CD, no IaC. |
| Docs | Strong — better than the code. Prior audit (`01_Documentation_Audit_Report.md`) already flagged privacy/retention contradiction and missing Security doc as **High**. Still open. |

## 2. Strengths

- Documentation set is coherent: problem to DB enum to LLM few-shot traceability chain is real (confirmed by prior audit, spot-checked here).
- `docker-compose.yml` already has health checks, `depends_on: condition: service_healthy`, and `restart: always` on every service — most greenfield repos skip this. Good baseline to extend, not replace.
- Tech choice (FastAPI async, Redis/Celery for offload, Qdrant for vectors) is sound for the stated < 200ms webhook-ack requirement.
- Project structure decision (asking for `clients/ml_client.py` boundary) is being made **before** any ML code is written — best possible timing, zero migration debt to pay later.

## 3. Weaknesses / Technical Debt

1. Backend has no code. Blocks everything else in this audit from being verified against reality rather than docs.
2. Two dependency systems in backend (`requirements.txt` vs `pyproject.toml`) will drift the moment someone edits only one.
3. `backend/Dockerfile` uses `pip install -r requirements.txt`; `pyproject.toml` declares `uv_build` as build backend. Pick one toolchain (recommend `uv` end to end — faster, lockfile, matches `pyproject.toml` already present).
4. `frontend/Dockerfile` was multi-stage-less and used npm against a `bun.lock` lockfile that npm cannot read correctly — bun and npm resolve dependency trees differently, so the image was silently ignoring the committed lockfile. Fixed this pass (see §12).
5. Container/DB naming (`cucudigital-*`) not migrated after project rename to jawara — fixed this pass.
6. LLM provider undecided in docs (OpenAI vs Claude) with no fallback/selection logic specified — this directly blocks writing `ml_client.py` cleanly, since the client contract shouldn't leak provider identity to the gateway.
7. No tests directory anywhere in the repo.
8. No CI config (no `.github/workflows`, no equivalent).
9. `.env.example` covers WAHA/Postgres/frontend vars only — missing `QDRANT_*`, `REDIS_URL`, any LLM API key, any future ML-service URL/key.

## 4. Risks

- **Building ML logic straight into FastAPI routes** (the natural first-draft instinct once someone starts implementing `02_Data_Pipeline.md`) is the single biggest risk — it is exactly the outcome this audit exists to prevent, and there's no code yet to stop it happening on day one of implementation.
- **Model loading cost inside request path**: OCR (EasyOCR/Tesseract) and embedding models are heavy to load. If loaded inside gateway workers, every uvicorn worker process pays that memory/startup cost, and it scales with gateway replica count instead of ML replica count.
- **Undocumented APK detection mechanism** (flagged in prior audit) — if implemented ad hoc inside the gateway later, it becomes another ML-shaped responsibility the gateway wasn't supposed to own.
- **Plaintext `message_logs.extracted_text` with no retention policy** (prior audit, still open, High) — becomes materially worse once an independent ML service also touches/logs the same payload; retention policy must be decided before, not after, splitting services.

## 5. Scalability Concerns

- Celery worker and API gateway currently share one Docker image/build (`build: ./backend` for both `api-gateway` and `celery-worker` in compose) — acceptable at current scale, but conflates "gateway autoscaling" with "worker autoscaling" needs, which differ (gateway scales on connection count, ML/worker scales on CPU/GPU-bound inference).
- No mechanism today for scaling OCR/RAG/LLM independently of webhook intake — necessary the moment traffic grows, and the entire point of this audit's requested change.
- Qdrant and Postgres are single-instance, no replica/backup config — fine for hackathon/demo stage (this is a Gemastik 2026 competition submission per `.agents/project/overview.md`), flag as pre-production gap, not a defect at current stage.

## 6. Security Concerns

- No auth code exists (docs mention "API Key Verification & Auth" as a gateway box, nothing implemented).
- `WAHA_API_KEY`, `POSTGRES_PASSWORD`, etc. flow through plain env vars in compose — acceptable for self-hosted/demo, but no secrets manager, no `.env` gitignore verification done here (check before committing real credentials).
- No CORS configuration visible (frontend not yet making requests, so nothing to misconfigure yet — but must be decided before frontend-to-gateway calls exist).
- No rate-limiting code despite being a named gateway responsibility in docs and in the target architecture request.
- Internal service-to-service auth (gateway to future ML service) is undecided — must be designed now, see §9.

## 7. Performance Concerns

- Cannot benchmark — no running code. Documented targets (`<200ms` webhook ack, `<3s` end-to-end) are reasonable given async offload design, contingent on ML inference not blocking the gateway event loop.
- Biggest latent bottleneck once built: synchronous model inference (OCR, embedding, LLM call) executed inside a Celery task that also holds a DB connection — should pipeline as: fetch/prepare (gateway/worker) to infer (ML service, stateless call) to persist (worker) rather than one monolithic task function.

## 8. Recommended Architecture

Adopt exactly the target diagram in the request, with one addition: keep Celery/Redis as the **gateway-side** async layer (webhook offload, DB writes, orchestration retries) — do not merge Celery into the ML service. The ML service should be a plain stateless HTTP (see §9) service with its own process model (e.g. Uvicorn/Gunicorn workers sized to GPU/CPU count), not a Celery consumer. This keeps "orchestration state" (retries, queue depth, dead-letter) owned by the gateway, and "inference" owned by the ML service — matches the responsibility split requested.

```
WhatsApp --> WAHA --> FastAPI Gateway --> Celery/Redis (orchestration only)
                          |                      |
                          v                      v
                     Postgres              ml_client.py --HTTP--> ML Service (stateless)
                                                                        |
                                                                        v
                                                                  Qdrant (owned by ML service,
                                                                  NOT gateway — see note)
```

**Note on Qdrant ownership:** current docs put Qdrant under the gateway's data layer. Once RAG retrieval is ML-service logic (embedding + similarity search are inference-adjacent, not business logic), Qdrant access should move behind the ML service too — the gateway should never compute or compare embeddings directly. Postgres (audit logs, fraud blacklist, subscriptions) stays gateway-owned, since that's business/relational data, not model state.

## 9. Communication Between Services

| Option | Latency | Complexity | Maintainability | Scalability | Fit for JAWARA |
|---|---|---|---|---|---|
| **REST (HTTP/JSON)** | Low-medium (~ms serialization overhead) | Low — FastAPI on both ends, shared Pydantic schemas possible | High — human-debuggable, curl-able, OpenAPI docs for free | Good — stateless, horizontally scalable behind any LB | **Best fit.** Team already all-in on FastAPI; no new protocol to learn under competition time pressure. |
| gRPC | Lowest, best for high-QPS/streaming | High — protobuf schema management, codegen toolchain, harder to debug ad hoc | Medium — great once mature, steep setup cost now | Excellent at scale | Overkill pre-launch. Revisit only if inference QPS or payload size (e.g. streaming image frames) becomes the actual bottleneck. |
| Async Queue (Celery/Redis to ML) | Higher (queue hop + poll/callback) | Medium | Medium — good for fire-and-forget, awkward for request/response the LLM answer flow needs synchronously | Good for burst absorption | Wrong shape here: the gateway needs a **synchronous answer** from ML (classification, RAG context, LLM text) to build the WhatsApp reply. Queueing adds a round-trip without solving a real problem — Celery already provides the async offload *from WAHA*, a second async hop to ML is redundant. |
| Message Broker (Kafka/RabbitMQ, pub/sub) | Higher, decoupled | High — new infra component, ops burden | Good for many-consumer fan-out | Excellent for event streams | Not justified — JAWARA has one producer (gateway) and one consumer (ML service) per request, not a fan-out/event-sourcing need. |

**Recommendation:** REST (JSON) now, gateway to ML, synchronous, timeout-bounded, called from inside the existing Celery task (so WAHA webhook ack stays instant, but the ML call itself is a plain blocking-with-timeout HTTP request from the worker's perspective). Re-evaluate gRPC only if profiling shows serialization/latency dominating once real traffic exists — do not pre-optimize for it now.

## 10. Docker Architecture

Compose already has the right shape (waha, gateway, worker, postgres, redis, qdrant, frontend). To reach target:

- Add `ml-service` as its own `build: ./ml-service` entry, own healthcheck, own restart policy — independently deployable, independently scalable (`docker compose up --scale ml-service=N`).
- Add `nginx` only when TLS termination / single public entrypoint is actually needed (production deploy) — not required for local/demo compose, skip until then rather than adding unused complexity now.
- Naming: `cucudigital-*` containers/network/`POSTGRES_DB` renamed to `jawara-*` this pass (`docker-compose.yml`, `.env.example`, `03_Tech_Stack.md` example block) for consistency with the renamed project.
- `ml-service` healthcheck must check model-loaded readiness, not just process-up (see §12, readiness vs liveness).
- Secrets: current `.env` pattern is fine for compose-level self-hosting; if this moves to a shared/production host, move secrets to Docker secrets or an external vault — flag as pre-production, not urgent now.

## 11. Future Scalability

| Concern | Readiness today | What's needed |
|---|---|---|
| Multiple ML models | Not applicable — no models yet | Design `ml-service/app/models/` + a model registry pattern from day one so "second model" is a config entry, not a rewrite |
| Model versioning | None | Version in API path (`/v1/predict`) or request header from the start — cheap now, expensive to retrofit |
| GPU inference | Compose has no GPU device reservation | Add `deploy.resources.reservations.devices` (compose) or plan direct k8s GPU scheduling when that migration happens |
| Horizontal scaling | Compose supports `--scale` today for stateless services once ml-service exists | Ensure ml-service is stateless (no local model-write state, no session affinity) — required by ML-service responsibilities already stated in the request |
| Kubernetes migration | None yet, not needed at current (competition/demo) stage | Defer — compose is correct for this project's current size; don't add k8s manifests speculatively |
| CI/CD | None | Minimum viable: GitHub Actions running lint + tests + docker build on PR. Currently nothing to test, so land this alongside the first real backend code, not before |
| Independent deployment | Blocked until ml-service is its own image/repo-or-directory with its own Dockerfile | Directory split proposed in §13 achieves this |
| Canary / Blue-Green | Not applicable pre-launch | Revisit once there's a production traffic pattern to protect |

## 12. API Contract (Gateway to ML Service)

Recommend a small, versioned surface rather than the four generic verbs listed in the request — map each to an actual JAWARA use case instead of a generic ML buzzword surface:

- `POST /v1/classify` — intent routing (`HEALTH_HOAX`, `FINANCIAL_FRAUD`, `GENERAL_NEWS`, `PHISHING_LINK`, `FILE_APK`)
- `POST /v1/ocr` — image/flyer text extraction
- `POST /v1/embed` — text to vector (used internally by RAG retrieval, and by gateway only if it ever needs a raw embedding outside RAG)
- `POST /v1/rag-query` — embed + Qdrant similarity search + fact context, returned as one call (keeps Qdrant access inside ml-service, per §8 note)
- `POST /v1/generate` — LLM response generation given assembled context

**Request/response schema:** every endpoint takes `{ request_id, payload, metadata }` and returns `{ request_id, result, confidence, model_version, latency_ms }` — `request_id` doubles as the correlation ID threaded from the original WAHA webhook through Celery through ML service through Postgres audit log (see §15).

**Versioning:** URL path versioning (`/v1/...`). Bump path on breaking schema change; keep `model_version` in the response body for non-breaking model swaps.

**Error handling:** ML service returns structured errors (`{ error_code, message, retryable: bool }`), not bare HTTP 500s — lets the gateway decide retry vs fallback-template (per the existing documented LLM-timeout fallback strategy) programmatically instead of by status-code guessing.

**Timeout strategy:** gateway sets a hard timeout per endpoint (`generate` needs more budget than `classify`), aligned to the documented 3s end-to-end target minus WAHA/network overhead — budget roughly: classify 300ms, ocr 800ms, rag-query 500ms, generate 1500ms, leaving headroom.

**Retry strategy:** retry only idempotent, side-effect-free calls (classify, embed, rag-query) with capped exponential backoff (e.g. 2 attempts, 100ms/400ms); never blind-retry `generate` (cost + non-idempotent LLM billing) — on failure there, fall straight to the documented static-template fallback.

## 13. Reliability

None of the following exist yet — all net-new for both gateway and ml-service:

- **Request timeout**: per-endpoint budgets, see §12.
- **Circuit breaker**: trip on ml-service error-rate threshold so gateway short-circuits straight to fallback template during an ML outage instead of queuing failed calls behind a dead service.
- **Retry + exponential backoff**: see §12, idempotent endpoints only.
- **Idempotency**: `request_id` must be safe to retry/replay — ml-service should treat identical `request_id` as a cache hit where cheap to do so (e.g. classify result), not a new inference.
- **Graceful degradation**: already documented at the pipeline level (Qdrant down to Postgres full-text fallback, LLM timeout to static template) — extend the same philosophy to "ml-service entirely unreachable" as its own explicit fallback path, not just "LLM timeout."
- **Health/readiness/liveness**: gateway's current healthcheck (`GET /health`) is liveness-only. ml-service needs a **readiness** check that fails until models are loaded into memory — a liveness-only check would let the orchestrator route traffic to a container that's up but hasn't finished loading EasyOCR/embedding weights, causing cold-request failures right after container start.

## 14. Security Review

- **Service-to-service auth (gateway to ml-service):** since both live on the same Docker network and ml-service should never be internet-exposed, a shared internal API key (env-injected, checked via FastAPI dependency) is sufficient — mTLS is disproportionate complexity for a single-network internal call at this project's scale; revisit only at Kubernetes-multi-namespace stage.
- **JWT vs API Keys (external, frontend to gateway):** JWT for the B2G dashboard's authenticated sessions (per-user identity, expiry); a separate long-lived API key class for WAHA-to-gateway webhook auth (already the documented `X-Api-Key` pattern) — don't conflate the two; they have different threat models (session hijack vs webhook spoofing).
- **Secret management:** current `.env` is fine for the compose/self-hosted deployment target explicitly chosen in docs (`03_Tech_Stack.md` frames self-hosting as a cost/privacy feature, not incidental) — don't over-engineer with Vault/KMS unless deployment target changes.
- **CORS:** lock to the known dashboard origin(s) once frontend makes real requests; never wildcard given this handles fraud/health data.
- **Rate limiting:** implement the already-documented Redis rate limiter at the gateway before any public webhook exposure — currently a documented box with zero code, and it's the only thing standing between an exposed webhook and abuse once WAHA is internet-reachable.
- **Input validation:** Pydantic schemas at every gateway boundary (webhook payload, dashboard API) and every ml-service endpoint — validate file uploads (APK/image) for size and mime-type before they reach OCR/APK-inspection code, not after.
- Carries forward from the prior documentation audit (`01_Documentation_Audit_Report.md`, still open, **High**): no retention/deletion policy for plaintext `message_logs.extracted_text`. This is a security/privacy decision that should be made before ml-service exists, since it will also handle and potentially log the same payload.

## 15. Observability

Nothing exists today. Recommended minimum viable stack, not the full request list (Prometheus/Grafana/OTel are real asks but oversized for pre-launch):

- Structured JSON logging (Python `structlog` or stdlib `logging` with a JSON formatter) in both gateway and ml-service, from day one of writing code — retrofitting log structure later is pure toil.
- `request_id`/correlation ID (same one from §12) threaded through every log line across WAHA-webhook to gateway to Celery to ml-service to Postgres audit row — this is the single highest-leverage observability investment for a multi-hop async pipeline like this one, and costs almost nothing to add now vs a lot to add later.
- Defer Prometheus/Grafana/OpenTelemetry distributed tracing until there's a second environment (staging/prod) worth monitoring continuously — for a competition-stage single-demo deployment, structured logs + correlation IDs cover debugging needs without the ops overhead of running a metrics stack.

## 16. Documentation Review

- README files at repo root and in `frontend/` are essentially empty; `backend/README.md` is completely empty. Given how strong `obsidian-docs/` is, the code-level READMEs should at minimum point there and state prerequisites/run commands — currently a new contributor has nothing to start from at the code level.
- `obsidian-docs` architecture docs will need updating the moment ml-service is introduced (new diagram box, new compose service, new API contract) — treat `02_Architecture/01_System_Architecture.md` and `02_Data_Pipeline.md` as living docs to update in the same PR as the first ml-service code, not after.
- Missing Security doc and Deployment doc, already flagged High/Medium in the prior audit — both become more urgent once a second network-exposed-ish service (ml-service) exists.
- No developer onboarding doc anywhere (how to run compose locally, seed Postgres, get a WAHA session working) — worth writing once there's actually code to onboard onto.

## 17. Performance Bottleneck Summary

- Model loading overhead: load once per ml-service process at startup (module-level, not per-request) — obvious but worth stating as a hard requirement in the ml-service's own README/CLAUDE.md once it exists, since "load model per request" is the single most common ML-service performance bug.
- Blocking I/O: OCR and LLM calls are inherently blocking/CPU-or-network-bound — run them in ml-service's own worker processes (Gunicorn+Uvicorn workers, sized to CPU/GPU count), not inside the gateway's async event loop, which is exactly what moving them out of the gateway achieves.
- Large payload transfer: images sent gateway to ml-service for OCR should go as multipart/binary, not base64-in-JSON (33% size inflation, plus JSON parse cost) — worth specifying in the `/v1/ocr` contract once built.
- Duplicate processing: RAG embedding should happen once per request inside ml-service's `/v1/rag-query`, not separately for embed + separately for search — already reflected in the combined-endpoint recommendation in §12.

---

## 18. Priority Matrix

| Priority | Item |
|---|---|
| **High** | Decide and fix backend dependency toolchain (uv vs pip) before writing any app code |
| **High** | Design `ml_client.py` contract (§12) before writing gateway routes, so gateway code never has an inference call to "extract later" |
| **High** | Resolve plaintext log retention policy (carried from prior audit) |
| **High** | Write Security doc (carried from prior audit) |
| **High** | Implement rate limiting + webhook auth before any public exposure |
| **Medium** | Decide LLM provider / fallback logic (carried from prior audit) |
| **Medium** | Add correlation-ID structured logging from first line of code |
| **Medium** | Add readiness vs liveness distinction once ml-service exists |
| **Medium** | Add circuit breaker + fallback-on-ml-outage path |
| **Low** | Kubernetes migration, GPU scheduling, canary/blue-green — all correctly deferred at current project stage |
| **Low** | nginx reverse proxy — add only at real production deploy |

## 19. Concrete Refactoring / Build Tasks

Ordered as a build sequence (since there is no existing code to refactor, only a target to build toward):

1. Pick one backend dependency toolchain; delete the other manifest file.
2. Scaffold `backend/app/{api,core,config,middleware,auth,services,repositories,schemas,clients,workers,utils}/main.py` per the requested structure; `clients/ml_client.py` defines the HTTP contract from §12 as typed Pydantic models shared conceptually (not necessarily as a shared package yet) with ml-service's schemas.
3. Scaffold `ml-service/app/{api,inference,preprocessing,postprocessing,models,pipelines,schemas}/main.py` per the requested structure.
4. Add `ml-service` to `docker-compose.yml`, independent Dockerfile, healthcheck (readiness-aware).
5. Implement webhook auth + Redis rate limiter in gateway (currently zero code, high security priority).
6. Implement correlation-ID propagation end to end before adding any business logic that would need retrofitting for it later.
7. Update `obsidian-docs/02_Architecture/*` diagrams to include ml-service as its own box, in the same change as step 3-4.

## 20. Suggested Directory Structures

Backend and ml-service structures as specified in the request are both sound and match this audit's recommendations — no changes proposed to the requested layout. Confirmed additions:

- `backend/app/clients/ml_client.py` — the *only* file in the gateway allowed to know ml-service's URL/schema. No route or service file should call ml-service directly; everything goes through this client so the boundary is enforced by code structure, not convention.
- `ml-service/app/models/` should include a lightweight registry (dict or small class mapping model name+version to loaded instance) from the first model onward, per §11's multi-model readiness note.

## 21. Recommended Technology Stack (delta from current docs)

- Keep: FastAPI, Celery+Redis, Postgres 16, Qdrant, LlamaIndex, Next.js+shadcn.
- Add: `uv` as the single backend package manager (already half-adopted via `pyproject.toml`).
- Add: `structlog` (or equivalent) for structured JSON logs, both services.
- Add: `httpx` (async) in `ml_client.py` for the gateway-to-ml-service calls — matches FastAPI's async-native design already chosen.
- Decide (blocking, carried from prior audit): OpenAI GPT-4o-mini vs Claude 3.5 Haiku as the actual LLM — pick one now; design the `ml_client.py` `/v1/generate` contract to be provider-agnostic on the gateway side regardless of which is chosen, so switching later is a ml-service-internal change only.

## 22. Future-Proof Recommendations

- Every ml-service response includes `model_version` — the day a second model or a fine-tuned version ships, the gateway/logs already have the field to distinguish them, no schema migration needed.
- Path-based API versioning from `/v1/` on the very first endpoint — trivial now, painful to retrofit once a client (dashboard, WAHA integration) hardcodes unversioned paths.
- Treat `ml-service/` as independently deployable from day one (own Dockerfile, own healthcheck, own scale factor in compose) even before there's a real reason to scale it separately — the discipline costs nothing now and is the entire point of this migration.

---

## Breaking Changes / Migration Complexity Estimate

Since no backend code currently exists, there are **no breaking changes to existing running behavior** — this is a design-time decision, not a live migration. Complexity estimates below are for build effort, not migration risk:

| Change | Complexity | Why |
|---|---|---|
| Backend app scaffold (§19 step 2) | Medium | Straightforward FastAPI structure, but first real code in the repo — no existing patterns to follow, every convention decided here sets precedent |
| ml-service scaffold + first model (OCR or classify) | Medium-High | First real ML integration; model loading, memory footprint, and the registry pattern all need to be right the first time to avoid retrofitting |
| Gateway-to-ML REST contract (§12) | Low | Plain FastAPI/Pydantic on both ends, no new infra |
| Compose additions (ml-service, renaming) | Low | Compose already has the right patterns (healthcheck, depends_on) to copy |
| Rate limiting + webhook auth | Low-Medium | Redis already in place; mostly a FastAPI middleware/dependency to write |
| Observability (correlation IDs, structured logs) | Low if done now, High if retrofitted later | Cheapest possible time to add is before any log line exists |
| Full Kubernetes/canary/blue-green | Not scoped now | Correctly deferred; would be High complexity, not justified at current stage |

---

**Related:** [[01_Documentation_Audit_Report]] · [[01_System_Architecture]] · [[02_Data_Pipeline]] · [[03_Tech_Stack]]
