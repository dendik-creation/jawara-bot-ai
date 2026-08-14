# Third-Party License Compliance

JAWARA is licensed under the [MIT License](../../LICENSE). This document inventories
every third-party dependency, container image, and external API JAWARA links against,
builds with, or calls at runtime, with the license actually shipped in the version
JAWARA uses — not the license a package's README claims, and not whatever an older
inventory said.

**Source of truth:** `backend/uv.lock`, `ml-service/uv.lock`, `frontend/bun.lock`, and
`docker-compose.yml`. Every table below was generated from those files (see
[Regenerating this document](#regenerating-this-document)), not typed by hand.

Last generated: 2026-08-15, against these pinned versions:

| Component | Manifest | Lockfile |
|---|---|---|
| Frontend | `frontend/package.json` | `frontend/bun.lock` |
| Backend (API Gateway + Celery) | `backend/pyproject.toml` | `backend/uv.lock` |
| ML Service | `ml-service/pyproject.toml` | `ml-service/uv.lock` |
| Infrastructure | `docker-compose.yml` | — (pinned image tags) |

---

## Contents

1. [Frontend — Next.js dashboard](#1-frontend--nextjs-dashboard)
2. [Backend — FastAPI Gateway](#2-backend--fastapi-gateway)
3. [ML Service — FastAPI + ML/OCR](#3-ml-service--fastapi--mlocr)
4. [Infrastructure (self-hosted)](#4-infrastructure-self-hosted)
5. [External APIs (SaaS, not redistributed code)](#5-external-apis-saas-not-redistributed-code)
6. [Flagged items — read before shipping](#6-flagged-items--read-before-shipping)
7. [NOTICE / attribution files](#7-notice--attribution-files)
8. [Regenerating this document](#regenerating-this-document)

---

## 1. Frontend — Next.js dashboard

Runtime is `oven/bun:1-alpine` (`frontend/Dockerfile`); `bun run build` produces the
served bundle, so both `dependencies` and any `devDependencies` that participate in the
build (all of them, for a Next.js/Tailwind toolchain) end up influencing the shipped
artifact. Only `dependencies` end up in the client/server runtime bundle itself, though
— that's the split below.

### 1.1 Direct production dependencies (`package.json` → `dependencies`)

| Package | Version | License | Repository |
|---|---|---|---|
| @base-ui/react | 1.7.0 | MIT | https://github.com/mui/base-ui |
| class-variance-authority | 0.7.1 | Apache-2.0 | https://github.com/joe-bell/cva |
| clsx | 2.1.1 | MIT | https://github.com/lukeed/clsx |
| lucide-react | 1.28.0 | ISC | https://github.com/lucide-icons/lucide |
| next | 16.2.6 | MIT | https://github.com/vercel/next.js |
| next-themes | 0.4.6 | MIT | https://github.com/pacocoursey/next-themes |
| react | 19.2.4 | MIT | https://github.com/facebook/react |
| react-dom | 19.2.4 | MIT | https://github.com/facebook/react |
| recharts | 3.8.0 | MIT | https://github.com/recharts/recharts |
| shadcn | 4.16.1 | MIT | https://github.com/shadcn-ui/ui |
| tailwind-merge | 3.6.0 | MIT | https://github.com/dcastil/tailwind-merge |
| tw-animate-css | 1.4.0 | MIT | https://github.com/Wombosvideo/tw-animate-css |

### 1.2 Direct development dependencies (`package.json` → `devDependencies`)

Build-time only — not present in the deployed bundle, but still linked in during the
Docker build stage.

| Package | Version | License | Repository |
|---|---|---|---|
| @tailwindcss/postcss | 4.3.3 | MIT | https://github.com/tailwindlabs/tailwindcss |
| @types/node | 20.19.43 | MIT | https://github.com/DefinitelyTyped/DefinitelyTyped |
| @types/react | 19.2.18 | MIT | https://github.com/DefinitelyTyped/DefinitelyTyped |
| @types/react-dom | 19.2.4 | MIT | https://github.com/DefinitelyTyped/DefinitelyTyped |
| eslint | 9.39.5 | MIT | https://github.com/eslint/eslint |
| eslint-config-next | 16.2.6 | MIT | https://github.com/vercel/next.js |
| prettier | 3.9.6 | MIT | https://github.com/prettier/prettier |
| prettier-plugin-tailwindcss | 0.8.1 | MIT | https://github.com/tailwindlabs/prettier-plugin-tailwindcss |
| tailwindcss | 4.3.3 | MIT | https://github.com/tailwindlabs/tailwindcss |
| typescript | 5.9.3 | Apache-2.0 | https://github.com/microsoft/TypeScript |

### 1.3 Full dependency tree (transitive)

`next` alone pulls in the SWC compiler, and several of these are *runtime* production
dependencies of `next`/`react-dom`/`recharts`, not dev tooling — that's why the
production closure below is much larger than §1.1's 12 direct packages.

`bun install` resolves **377 production packages** and **233 additional
development-only packages** (610 total) from `frontend/bun.lock`. The full
per-package list — every name, version, license, and resolved repository — is
generated data, not hand-maintained; see:

- [`reports/frontend-production.json`](reports/frontend-production.json) — full production closure
- [`reports/frontend-all.json`](reports/frontend-all.json) — production + development

License breakdown of the 377-package production closure (excludes JAWARA's own
`UNLICENSED` `frontend` package entry):

| License | Package count |
|---|---|
| MIT | 316 |
| ISC | 32 |
| Apache-2.0 | 8 |
| BSD-3-Clause | 8 |
| BSD-2-Clause | 5 |
| BlueOak-1.0.0 | 2 |
| 0BSD | 1 |
| CC-BY-4.0 | 1 (`caniuse-lite` — data file, not code) |
| Python-2.0 | 1 (`argparse` npm shim, unrelated to the real CPython `argparse`) |
| MIT AND ISC | 1 (`victory-vendor`) |
| Apache-2.0 AND LGPL-3.0-or-later | 1 (`@img/sharp-win32-x64`, see §6) |

All permissive, no copyleft obligations beyond attribution (MIT/ISC/BSD/Apache-2.0
notice preservation — see §7).

---

## 2. Backend — FastAPI Gateway

Runtime is `python:3.14-slim` (`backend/Dockerfile`), dependencies installed via
`uv sync --locked --no-dev` — the `dev` group (pytest) never ships. Table below is
`backend/uv.lock`'s full resolved production closure (55 packages), generated via
`pip-licenses` against the synced `.venv`, cross-checked against `uv export --no-dev`.

### 2.1 Production dependencies (full resolved closure)

| Package | Version | License | Source |
|---|---|---|---|
| amqp | 5.3.1 | BSD License | http://github.com/celery/py-amqp |
| annotated-types | 0.8.0 | MIT | https://github.com/annotated-types/annotated-types |
| anyio | 4.14.2 | MIT | https://anyio.readthedocs.io/en/stable/versionhistory.html |
| asyncpg | 0.31.0 | Apache-2.0 | https://github.com/MagicStack/asyncpg |
| bcrypt | 5.0.0 | Apache-2.0 | https://github.com/pyca/bcrypt/ |
| billiard | 4.2.4 | BSD License | https://github.com/celery/billiard |
| celery | 5.3.6 | BSD License | https://docs.celeryq.dev/ |
| certifi | 2026.7.22 | MPL-2.0 | https://github.com/certifi/python-certifi |
| click | 8.4.2 | BSD-3-Clause | https://github.com/pallets/click/ |
| click-didyoumean | 0.3.1 | MIT License | https://github.com/click-contrib/click-didyoumean |
| click-plugins | 1.1.1.2 | BSD License | https://github.com/click-contrib/click-plugins |
| click-repl | 0.3.0 | MIT | https://github.com/untitaker/click-repl |
| colorama | 0.4.6 | BSD License | https://github.com/tartley/colorama |
| dnspython | 2.8.0 | ISC License (ISCL) | https://www.dnspython.org |
| email-validator | 2.3.0 | Unlicense (public domain) | https://github.com/JoshData/python-email-validator |
| fastapi | 0.110.0 | MIT | https://github.com/tiangolo/fastapi |
| grpcio | 1.83.0 | Apache-2.0 | https://grpc.io |
| grpcio-tools | 1.83.0 | Apache-2.0 | https://grpc.io |
| h11 | 0.16.0 | MIT License | https://github.com/python-hyper/h11 |
| h2 | 4.4.1 | MIT | https://github.com/python-hyper/h2/ |
| hpack | 4.2.0 | MIT | https://github.com/python-hyper/hpack/ |
| httpcore | 1.0.9 | BSD-3-Clause | https://www.encode.io/httpcore/ |
| httptools | 0.8.0 | MIT | https://github.com/MagicStack/httptools |
| httpx | 0.27.0 | BSD-3-Clause | https://github.com/encode/httpx |
| hyperframe | 6.1.0 | MIT License | https://github.com/python-hyper/hyperframe/ |
| idna | 3.18 | BSD-3-Clause | https://github.com/kjd/idna |
| kombu | 5.6.2 | BSD-3-Clause | https://kombu.readthedocs.io |
| numpy | 2.5.2 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 | https://numpy.org |
| packaging | 26.3 | Apache-2.0 OR BSD-2-Clause | https://github.com/pypa/packaging |
| portalocker | 2.10.1 | BSD License | https://github.com/wolph/portalocker/ |
| prompt_toolkit | 3.0.53 | BSD License | https://github.com/prompt-toolkit/python-prompt-toolkit |
| protobuf | 7.35.1 | BSD-3-Clause | https://developers.google.com/protocol-buffers/ |
| pydantic | 2.13.4 | MIT | https://github.com/pydantic/pydantic |
| pydantic-settings | 2.2.1 | MIT | https://github.com/pydantic/pydantic-settings |
| pydantic_core | 2.46.4 | MIT | https://github.com/pydantic/pydantic-core |
| python-dateutil | 2.9.0.post0 | Apache-2.0 OR BSD-3-Clause (dual) | https://github.com/dateutil/dateutil |
| python-dotenv | 1.2.2 | BSD-3-Clause | https://github.com/theskumar/python-dotenv |
| python-multipart | 0.0.32 | Apache-2.0 | https://github.com/Kludex/python-multipart |
| PyYAML | 6.0.3 | MIT License | https://pyyaml.org/ |
| qdrant-client | 1.8.2 | Apache-2.0 | https://github.com/qdrant/qdrant-client |
| redis | 5.0.1 | MIT License | https://github.com/redis/redis-py |
| setuptools | 84.0.0 | MIT | https://github.com/pypa/setuptools |
| six | 1.17.0 | MIT License | https://github.com/benjaminp/six |
| sniffio | 1.3.1 | Apache-2.0 OR MIT (dual) | https://github.com/python-trio/sniffio |
| starlette | 0.36.3 | BSD-3-Clause | https://github.com/encode/starlette |
| typing-inspection | 0.4.2 | MIT | https://github.com/pydantic/typing-inspection |
| typing_extensions | 4.16.0 | PSF-2.0 | https://github.com/python/typing_extensions |
| tzdata | 2026.3 | Apache-2.0 | https://github.com/python/tzdata |
| urllib3 | 2.7.0 | MIT | https://github.com/urllib3/urllib3 |
| uvicorn | 0.27.1 | BSD-3-Clause | https://www.uvicorn.org/ |
| uvloop | 0.22.1 | MIT OR Apache-2.0 (dual) | https://github.com/MagicStack/uvloop |
| vine | 5.1.0 | BSD License | https://github.com/celery/vine |
| watchfiles | 1.2.0 | MIT License | https://github.com/samuelcolvin/watchfiles |
| wcwidth | 0.8.2 | MIT | https://github.com/jquast/wcwidth |
| websockets | 17.0.1 | BSD-3-Clause | https://github.com/python-websockets/websockets |

`uvloop` is a Linux-only conditional dependency of `uvicorn[standard]`
(`platform_python_implementation != 'PyPy' and sys_platform != 'cygwin' and
sys_platform != 'win32'`) — it never installs on a Windows dev machine, only in the
`python:3.14-slim` (Linux) container that actually runs in production, and so is added
here from the lockfile rather than a Windows-venv scan. Its dual MIT/Apache-2.0 license
is per the project's own `LICENSE`/`LICENSE.APACHE` files.

`colorama` and `pywin32` (`portalocker`'s Windows backend) are the reverse case:
`sys_platform == 'win32'`-gated, so they install into a Windows dev `.venv` but never
into the Linux production container. Listed above for completeness since a dev running
this stack locally on Windows does end up with them installed, but they carry zero
weight for what's actually shipped.

### 2.2 Development-only dependencies (`dependency-groups.dev`, never shipped)

| Package | Version | License | Source |
|---|---|---|---|
| iniconfig | 2.3.0 | MIT | https://github.com/pytest-dev/iniconfig |
| pluggy | 1.6.0 | MIT License | https://github.com/pytest-dev/pluggy |
| pytest | 8.1.1 | MIT License | https://docs.pytest.org/en/latest/ |
| pytest-asyncio | 0.23.6 | Apache-2.0 | https://github.com/pytest-dev/pytest-asyncio |

---

## 3. ML Service — FastAPI + ML/OCR

Runtime is `python:3.14-slim` plus the `tesseract-ocr` system package
(`ml-service/Dockerfile`) — Tesseract itself is Apache-2.0, invoked as an external
binary via `pytesseract` (shelling out, not linked in-process), so its license doesn't
propagate into the Python dependency closure the way a linked library would.

### 3.1 Production dependencies (full resolved closure)

| Package | Version | License | Source |
|---|---|---|---|
| annotated-types | 0.8.0 | MIT | https://github.com/annotated-types/annotated-types |
| anyio | 4.14.2 | MIT | https://anyio.readthedocs.io/en/stable/versionhistory.html |
| certifi | 2026.7.22 | MPL-2.0 | https://github.com/certifi/python-certifi |
| click | 8.4.2 | BSD-3-Clause | https://github.com/pallets/click/ |
| fastapi | 0.110.0 | MIT | https://github.com/tiangolo/fastapi |
| grpcio | 1.83.0 | Apache-2.0 | https://grpc.io |
| grpcio-tools | 1.83.0 | Apache-2.0 | https://grpc.io |
| h11 | 0.16.0 | MIT License | https://github.com/python-hyper/h11 |
| h2 | 4.4.1 | MIT | https://github.com/python-hyper/h2/ |
| hpack | 4.2.0 | MIT | https://github.com/python-hyper/hpack/ |
| httpcore | 1.0.9 | BSD-3-Clause | https://www.encode.io/httpcore/ |
| httptools | 0.8.0 | MIT | https://github.com/MagicStack/httptools |
| httpx | 0.27.0 | BSD-3-Clause | https://github.com/encode/httpx |
| hyperframe | 6.1.0 | MIT License | https://github.com/python-hyper/hyperframe/ |
| idna | 3.18 | BSD-3-Clause | https://github.com/kjd/idna |
| joblib | 1.5.3 | BSD-3-Clause | https://joblib.readthedocs.io |
| narwhals | 2.24.0 | MIT | https://github.com/narwhals-dev/narwhals |
| numpy | 2.5.2 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 | https://numpy.org |
| packaging | 26.3 | Apache-2.0 OR BSD-2-Clause | https://github.com/pypa/packaging |
| **pillow** | **12.3.0** | **MIT-CMU** | https://python-pillow.github.io |
| python-dotenv | 1.2.2 | BSD-3-Clause | https://github.com/theskumar/python-dotenv |
| python-multipart | 0.0.20 | Apache-2.0 | https://github.com/Kludex/python-multipart |
| PyYAML | 6.0.3 | MIT License | https://pyyaml.org/ |
| pydantic | 2.13.4 | MIT | https://github.com/pydantic/pydantic |
| pydantic-settings | 2.2.1 | MIT | https://github.com/pydantic/pydantic-settings |
| pydantic_core | 2.46.4 | MIT | https://github.com/pydantic/pydantic-core |
| pytesseract | 0.3.13 | Apache-2.0 | https://github.com/madmaze/pytesseract |
| qdrant-client | 1.8.2 | Apache-2.0 | https://github.com/qdrant/qdrant-client |
| scikit-learn | 1.9.0 | BSD-3-Clause | https://scikit-learn.org |
| scipy | 1.18.0 | BSD-3-Clause | https://scipy.org/ |
| setuptools | 84.0.0 | MIT | https://github.com/pypa/setuptools |
| sniffio | 1.3.1 | Apache-2.0 OR MIT (dual) | https://github.com/python-trio/sniffio |
| starlette | 0.36.3 | BSD-3-Clause | https://github.com/encode/starlette |
| threadpoolctl | 3.6.0 | BSD License | https://github.com/joblib/threadpoolctl |
| typing-inspection | 0.4.2 | MIT | https://github.com/pydantic/typing-inspection |
| typing_extensions | 4.16.0 | PSF-2.0 | https://github.com/python/typing_extensions |
| urllib3 | 2.7.0 | MIT | https://github.com/urllib3/urllib3 |
| uvicorn | 0.27.1 | BSD-3-Clause | https://www.uvicorn.org/ |
| uvloop | 0.22.1 | MIT OR Apache-2.0 (dual) | https://github.com/MagicStack/uvloop |
| watchfiles | 1.2.0 | MIT License | https://github.com/samuelcolvin/watchfiles |
| websockets | 17.0.1 | BSD-3-Clause | https://github.com/python-websockets/websockets |

Same Linux-only (`uvloop`) / Windows-only (`colorama`, `pywin32`) platform notes from
§2.1 apply here.

### 3.2 Development-only dependencies

| Package | Version | License | Source |
|---|---|---|---|
| iniconfig | 2.3.0 | MIT | https://github.com/pytest-dev/iniconfig |
| pluggy | 1.6.0 | MIT License | https://github.com/pytest-dev/pluggy |
| pytest | 8.1.1 | MIT License | https://docs.pytest.org/en/latest/ |
| pytest-asyncio | 0.23.6 | Apache-2.0 | https://github.com/pytest-dev/pytest-asyncio |

### 3.3 Pillow — verified in detail

Pillow's license is easy to get wrong because it has been described inconsistently
across tooling and years (SPDX historically bucketed it under `HPND`, some scanners
still say "HPND, similar to MIT"). That is **not** what the pinned version declares.

**Verified directly from the installed 12.3.0 package**
(`ml-service/.venv/…/pillow-12.3.0.dist-info/`):

- `METADATA` declares `License-Expression: MIT-CMU` — Pillow's own SPDX self-classification, not a third party's guess.
- The bundled `licenses/LICENSE` file states verbatim: *"Like PIL, Pillow is licensed under the open source MIT-CMU License"*, followed by the actual permissive grant (permission to use/copy/modify/distribute without fee, provided the copyright notice is retained; a name-in-advertising restriction naming Secret Labs AB/the author; standard "AS IS" disclaimer).

**MIT-CMU is its own SPDX identifier**, not a synonym for the plain MIT License — the
distinguishing clause is the restriction on using Secret Labs AB's or the author's name
in advertising without permission, which the generic MIT License doesn't have. Document
it as `MIT-CMU`, not as "MIT" and not as "HPND (similar to MIT)."

**Bundled binary dependencies:** Pillow's wheel statically links several C libraries
(libjpeg-turbo, zlib-ng, libtiff, freetype, lcms2, libwebp, brotli, and others) rather
than dynamically loading system copies. Their individual license texts are appended
inside the same `LICENSE` file Pillow ships. That full 1617-line file — MIT-CMU grant
plus every vendored library's license — is preserved verbatim at
[`reports/pillow-12.3.0-LICENSE-bundled.txt`](reports/pillow-12.3.0-LICENSE-bundled.txt).
All vendored licenses are permissive (MIT/BSD/zlib-style); none are copyleft.

---

## 4. Infrastructure (self-hosted)

Pulled as Docker images in `docker-compose.yml` — not linked into JAWARA's own code,
but self-hosted and redistributed as part of the deployed stack, so still in scope.

| Service | Image | Version | License | Notes |
|---|---|---|---|---|
| Database | `postgres:16-alpine` | PostgreSQL 16 | **PostgreSQL License** | Permissive, OSI-approved, MIT/BSD-style — *not* the plain "BSD License" some inventories shorthand it as. See §6. |
| Cache / broker | `redis:7-alpine` | Redis 7.4.x (floating `7-alpine` tag) | **RSALv2 OR SSPLv1 (dual)** | **Not BSD-3-Clause.** Redis relicensed away from BSD as of 7.4 — see §6, this is the single most important finding in this document. |
| Vector search | `qdrant/qdrant:v1.8.0` | Qdrant 1.8.0 | Apache-2.0 | Fully open source, no feature gating; pinned tag, not floating. |
| WhatsApp gateway | `devlikeapro/waha:latest` | WAHA (Core tier in use) | Apache-2.0 (`core` branch) | See §6 — image bundles paid Plus/PRO tiers behind a license key; JAWARA runs the free Core tier only, and the tag is floating (`:latest`), not pinned. |

---

## 5. External APIs (SaaS, not redistributed code)

These are called over HTTPS at runtime (`ML_SERVICE_URL`, `GOOGLE_SAFE_BROWSING_API_KEY`,
`VIRUSTOTAL_API_KEY`, `ANTHROPIC_API_KEY`/`OPENAI_API_KEY` in `docker-compose.yml`). No
code from these services is vendored or redistributed, so there's no "license" to track
in the OSS sense — the applicable document is each provider's Terms of Service /
Acceptable Use Policy, which governs how JAWARA is allowed to use the API, not how the
API's own code may be reused.

| Service | Used for | Governing terms |
|---|---|---|
| Anthropic API (Claude) | Reply generation, claim extraction (`ml-service`, `LLM_PROVIDER`) | https://www.anthropic.com/legal/consumer-terms · https://www.anthropic.com/legal/aup |
| OpenAI API | Alternate LLM provider (`LLM_PROVIDER`, `OPENAI_API_KEY`) | https://openai.com/policies/row-terms-of-use/ · https://openai.com/policies/usage-policies/ |
| Google Safe Browsing API | URL/link risk checks (`GOOGLE_SAFE_BROWSING_API_KEY`) | https://developers.google.com/safe-browsing/terms |
| VirusTotal API | URL/file risk checks (`VIRUSTOTAL_API_KEY`) | https://docs.virustotal.com/docs/terms-of-service |

None of these grant redistribution rights over their models, data, or detection
signals — JAWARA only consumes results through the documented API surface.

---

## 6. Flagged items — read before shipping

Ranked by how much this changes what a naive "MIT/BSD/Apache, all fine" table would
have said.

### 6.1 Redis 7-alpine is no longer BSD-licensed

`docker-compose.yml` pins `redis:7-alpine`. Redis relicensed as of version 7.4: **from
7.4.0 onward, Redis ships under a dual RSALv2 (Redis Source Available License v2) /
SSPLv1 (Server Side Public License) license, not the 3-Clause BSD license it used
through 7.2.x.** The floating `7-alpine` tag currently resolves to Redis 7.4.9, i.e.
the *new* license — this is a live fact about what gets pulled today, not a versioned
snapshot.

Neither RSALv2 nor SSPLv1 is OSI-approved open source. Both are "source available":
free to self-host and use, but with restrictions aimed at cloud providers offering
Redis as a managed service — not a concern for JAWARA's own self-hosted use as an
internal cache/broker, but worth knowing before assuming "it's basically BSD" or
redistributing this stack as a product built around a bundled Redis. If open-source
licensing terms matter for how this stack is distributed, either pin to a pre-7.4 tag
(e.g. `redis:7.2.4-alpine`) or switch to a fork still under the old license (Valkey,
BSD-3-Clause, is the drop-in replacement the Redis community forked to for exactly this
reason).

**Action:** decide explicitly — pin the tag either way — rather than continuing to
float on `:7-alpine` and silently inheriting whatever license Redis ships under next.

### 6.2 WAHA image bundles a paywalled tier

`devlikeapro/waha:latest` is the same image regardless of which tier you're licensed
for; Plus (media messages, multi-session) and PRO (source access, team seats) unlock
via a license key, not a separate pull. The `core` branch's `LICENSE` file is
Apache-2.0, and `docker-compose.yml`/`.env.example` show no `WAHA_*` license-key
variable, confirming JAWARA runs the free Core tier only — no undisclosed paid
dependency. Two loose ends worth tightening independent of licensing:

- `:latest` is floating — an upstream image update could change behavior or license
  terms under JAWARA without anyone noticing at pull time.
- Because Core is single-session and text-only, any future feature work (media
  replies, multiple WhatsApp numbers) would silently require a Plus subscription — that
  cost/legal decision should be made deliberately, not discovered when a feature stops
  working.

### 6.3 PostgreSQL License ≠ "BSD License"

`postgres:16-alpine` — PostgreSQL is under its own **PostgreSQL License**, a
permissive, OSI-approved license that closely resembles the MIT/ISC style (no
copyleft, attribution required) but is textually its own license, not a copy of any
BSD variant. Prior inventories describing it as "BSD" or "BSD-style" aren't
functionally wrong about the permissions, but the correct name for reproduction in a
compliance doc is "PostgreSQL License."

### 6.4 `@img/sharp-win32-x64` — Apache-2.0 AND LGPL-3.0-or-later

Transitive dependency of `sharp` (Next.js's image optimizer), Windows-only native
binding. LGPL-3.0-or-later is weak copyleft — it applies to the bound native library
itself and requires that users be able to replace/relink it, not to JAWARA's own
application code, since `sharp` accesses it through a stable dynamic interface rather
than static-linking application logic into it. No action needed for a standard
Next.js build, flagged here only because it's the one LGPL-tainted entry in an
otherwise entirely permissive 377-package frontend closure.

### 6.5 Everything else

No GPL, AGPL, SSPL (outside §6.1), or other strong-copyleft/network-copyleft licenses
were found anywhere in the frontend, backend, or ML service dependency closures. The
overwhelming majority of both closures is MIT/BSD/Apache-2.0/ISC — permissive, with
attribution/notice-preservation as the only real obligation (§7).

---

## 7. NOTICE / attribution files

Checked every `*.dist-info` directory in both Python virtual environments and the top
two levels of `frontend/node_modules` for `NOTICE`/`NOTICE.txt`/`NOTICE.md` files (the
mechanism Apache-2.0 §4(d) uses to carry forward upstream attributions through a
dependency chain): **none of JAWARA's current dependencies ship one.** Re-check this
whenever the lockfiles change — an added Apache-2.0 package with third-party
attributions inside it (Airflow and Kafka clients are common examples) would introduce
one, and it would need to be carried into a project-level `NOTICE` file at that point.

Pillow is the one package that bundles extensive third-party attributions, done inside
its own `LICENSE` file rather than a separate `NOTICE` file — preserved in full at
[`reports/pillow-12.3.0-LICENSE-bundled.txt`](reports/pillow-12.3.0-LICENSE-bundled.txt)
(see §3.3).

---

## Regenerating this document

The tables above are prose written over generated data, not hand-maintained — when a
lockfile changes, regenerate the underlying reports and re-diff:

```bash
./scripts/licenses/generate-reports.sh
```

This writes fresh JSON/text reports to `docs/licenses/reports/` using ephemeral tool
installs (`bunx license-checker-rseidelsohn`, `uv run --with pip-licenses`) — it never
touches `frontend/package.json`, `backend/pyproject.toml`, or
`ml-service/pyproject.toml`. Then diff the new reports against the committed ones in
`reports/`, and hand-update the prose tables in this file for anything that changed
(added/removed/relicensed package, new NOTICE file, a floating infra tag resolving to a
different major version).

Committed report snapshots (regenerated by the script above):

- `reports/frontend-production.json`, `reports/frontend-all.json`
- `reports/backend-all.json`, `reports/backend-production.deps.txt`, `reports/backend-all.deps.txt`
- `reports/ml-service-all.json`, `reports/ml-service-production.deps.txt`, `reports/ml-service-all.deps.txt`
- `reports/pillow-12.3.0-LICENSE-bundled.txt`

Infrastructure image versions (§4) aren't covered by the script — they're read
directly off `docker-compose.yml`'s pinned tags, so check that file's `image:` lines
when re-verifying §4 and §6.
