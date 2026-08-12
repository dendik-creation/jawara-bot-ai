#!/usr/bin/env bash
# Snapshot Postgres (message logs, knowledge, datasets, model registry, ...)
# and Qdrant (fact embeddings) to ./backups/<timestamp>/.
#
# Run from the repo root, with the stack up:
#   ./scripts/backup.sh
#
# Restore:
#   gunzip -c backups/<ts>/postgres.sql.gz | docker exec -i jawara-postgres \
#     psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"
#   docker cp backups/<ts>/qdrant-<collection>.snapshot \
#     jawara-qdrant:/qdrant/snapshots/<collection>/<file>.snapshot
#   curl -X PUT "http://127.0.0.1:${QDRANT_PORT}/collections/<collection>/snapshots/recover" \
#     -H 'Content-Type: application/json' \
#     -d '{"location": "file:///qdrant/snapshots/<collection>/<file>.snapshot"}'
#
# No scheduling here — wire this into cron/systemd-timer on the VPS yourself;
# this script only knows how to take one backup, not when to take it.

set -euo pipefail
cd "$(dirname "$0")/.."

set -a
source .env
set +a

TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT_DIR="backups/${TIMESTAMP}"
mkdir -p "$OUT_DIR"

echo "==> Postgres dump"
docker exec jawara-postgres pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  | gzip > "$OUT_DIR/postgres.sql.gz"

echo "==> Qdrant snapshot (${QDRANT_COLLECTION})"
SNAPSHOT_NAME="$(
  curl -sf -X POST "http://127.0.0.1:${QDRANT_PORT}/collections/${QDRANT_COLLECTION}/snapshots" \
    | grep -oE '"name":"[^"]+"' | head -1 | cut -d'"' -f4
)"
# Snapshots live under /qdrant/snapshots, a separate path from the
# /qdrant/storage volume — not persisted by qdrant_data, so this copy-out is
# the only durable record of it. Deleted server-side afterward: left alone,
# these accumulate (each one is a full collection copy) with no retention.
docker cp \
  "jawara-qdrant:/qdrant/snapshots/${QDRANT_COLLECTION}/${SNAPSHOT_NAME}" \
  "$OUT_DIR/qdrant-${QDRANT_COLLECTION}.snapshot"
curl -sf -X DELETE \
  "http://127.0.0.1:${QDRANT_PORT}/collections/${QDRANT_COLLECTION}/snapshots/${SNAPSHOT_NAME}" \
  > /dev/null

echo "==> Done: $OUT_DIR"
du -sh "$OUT_DIR"/*
