#!/usr/bin/env bash
# Regenerate the raw third-party license reports under docs/licenses/reports/.
# These are the source-of-truth data files behind docs/licenses/THIRD_PARTY_LICENSES.md
# — that doc is hand-written prose over this output, so re-run this and re-diff the
# doc whenever a lockfile changes, not just when someone remembers to.
#
# Uses ephemeral tool installs (uv run --with, bunx) so it never touches
# frontend/package.json, backend/pyproject.toml, or ml-service/pyproject.toml.
#
# Run from the repo root:
#   ./scripts/licenses/generate-reports.sh

set -euo pipefail
cd "$(dirname "$0")/../.."

OUT_DIR="docs/licenses/reports"
mkdir -p "$OUT_DIR"

echo "== frontend (bun) =="
( cd frontend && bunx license-checker-rseidelsohn --production --json ) \
  > "$OUT_DIR/frontend-production.json"
( cd frontend && bunx license-checker-rseidelsohn --json ) \
  > "$OUT_DIR/frontend-all.json"

echo "== backend (uv) =="
# --project activates backend's own synced venv; --with pip-licenses layers the
# report tool on top for this invocation only — neither touches uv.lock.
uv run --project backend --with pip-licenses -- \
  pip-licenses --with-system --with-authors --with-urls \
    --with-license-file --no-license-path --format=json \
  > "$OUT_DIR/backend-all.json"
uv export --project backend --no-dev --no-hashes -q > "$OUT_DIR/backend-production.deps.txt"
uv export --project backend --no-hashes -q > "$OUT_DIR/backend-all.deps.txt"

echo "== ml-service (uv) =="
uv run --project ml-service --with pip-licenses -- \
  pip-licenses --with-system --with-authors --with-urls \
    --with-license-file --no-license-path --format=json \
  > "$OUT_DIR/ml-service-all.json"
uv export --project ml-service --no-dev --no-hashes -q > "$OUT_DIR/ml-service-production.deps.txt"
uv export --project ml-service --no-hashes -q > "$OUT_DIR/ml-service-all.deps.txt"

echo ""
echo "Done. *-all.json covers the whole synced venv (prod + dev group); cross-reference"
echo "against *-production.deps.txt to see which packages are dev-only (name matching,"
echo "'_' and '-' are equivalent)."
echo ""
echo "Note: uvloop is a Linux-only production dependency of uvicorn (platform marker"
echo "sys_platform != 'win32'). Running this on a Windows dev machine will silently"
echo "omit it from *-all.json — cross-check *-production.deps.txt, which lists it"
echo "unconditionally from the lockfile regardless of host platform."
