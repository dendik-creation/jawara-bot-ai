"""Continuous fact-check evidence ingestion (04_AI_and_ML/03_Knowledge_Base.md).

The generic pipeline behind every source adapter:

    fetch (feed) → parse → deduplicate (against what we already stored)
                 → fetch (article) → normalize → validate
                 → persist to fact_items → sync through the existing KB path

Two things this module deliberately does *not* do. It does not talk to
Qdrant: newly written rows go through `services.knowledge.sync_fact_items`,
the same ML Service `/v1/kb/upsert` path the operator's "Sync" button and
the CLI script already use, so there is exactly one road into the vector
store. And it knows nothing about TurnBackHoax: every source-specific
concern lives behind `app.ingestion.FactCheckSourceAdapter`.

Dedup happens *before* the per-article fetch, which is what makes the run
incremental — a scheduled run that finds nothing new costs one HTTP request
and writes one row to `fact_ingestion_runs`. The database's partial unique
index on (source_id, external_id) is the actual idempotency guarantee; the
pre-check is the optimisation, not the correctness argument.

Failure is per item wherever it can be: a malformed article is counted and
skipped, the other nine still land. Only a failure to reach the source at
all ends the run early, and even then the run row is closed with FAILED and
the reason — nothing is swallowed.
"""

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import asyncpg

from app.core.config import Settings, get_settings
from app.ingestion import get_adapter
from app.ingestion.base import (
    FactCheckSourceAdapter,
    IngestionError,
    NormalizedFactRecord,
    SourceFetchError,
    SourceParseError,
)
from app.services import knowledge

logger = logging.getLogger("app.services.fact_ingestion")

# Per-item failures kept on the run row. Enough to diagnose a pattern, not so
# many that one broken source writes an unbounded JSON blob every hour.
MAX_RECORDED_ERRORS = 20

RUN_COLUMNS = """
    id, source_slug, status::text AS status, triggered_by, started_at, finished_at,
    fetched, created, updated, duplicates, failed, synced, sync_failed, error, details
"""
RUN_SQL_BASE = f"SELECT {RUN_COLUMNS} FROM fact_ingestion_runs"


async def _connect(settings: Settings) -> asyncpg.Connection:
    return await asyncpg.connect(settings.database_url, timeout=5)


async def run_ingestion(
    slug: str,
    *,
    triggered_by: str = "SCHEDULE",
    limit: int | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Ingest one source. Returns the run summary.

    Raises `KeyError` for an unknown slug and propagates database failures
    (there is nowhere to record a run if PostgreSQL is unreachable). Source
    failures do not raise — they are recorded on the run and reported through
    `status`/`retryable`, so the caller decides whether a retry is worthwhile.
    """
    settings = settings or get_settings()
    adapter = get_adapter(slug, settings)
    limit = limit or settings.fact_ingestion_max_items

    conn = await _connect(settings)
    run_id: str | None = None
    try:
        run_id = str(
            await conn.fetchval(
                """
                INSERT INTO fact_ingestion_runs (source_slug, triggered_by, status)
                VALUES ($1, $2, 'RUNNING'::ingestion_run_status_enum)
                RETURNING id
                """,
                slug,
                triggered_by,
            )
        )
        logger.info("ingestion run started", extra={"run_id": run_id, "source": slug, "trigger": triggered_by})

        outcome = await _execute_run(conn, adapter, run_id=run_id, limit=limit, settings=settings)
        await _finish_run(conn, run_id, outcome)
        await _update_cursor(conn, slug, run_id, outcome)
    finally:
        try:
            await adapter.aclose()
        finally:
            await conn.close()

    summary = {"run_id": run_id, "source": slug, **outcome}
    # Nested under one key, not splatted: `created` (and `message`, `module`,
    # `filename`, ...) are attributes `logging.makeRecord` already owns, and an
    # `extra=` that collides with one raises KeyError — which would turn a
    # successful ingestion into a failed Celery task.
    logger.info("ingestion run finished", extra={"ingestion": summary})
    return summary


async def _execute_run(
    conn: asyncpg.Connection,
    adapter: FactCheckSourceAdapter,
    *,
    run_id: str,
    limit: int,
    settings: Settings,
) -> dict[str, Any]:
    counters = {
        "fetched": 0,
        "created": 0,
        "updated": 0,
        "duplicates": 0,
        "failed": 0,
        "synced": 0,
        "sync_failed": 0,
    }
    errors: list[dict[str, str]] = []

    source_id = await _ensure_source(conn, adapter)

    try:
        candidates = await adapter.list_candidates(limit)
    except (SourceFetchError, SourceParseError) as exc:
        # The source is unreachable or unreadable: nothing was ingested, and
        # the run says so. Retryability comes from the source error itself so
        # a 403 is not retried like a 503.
        retryable = isinstance(exc, SourceFetchError) and exc.retryable
        logger.warning(
            "ingestion source unavailable",
            extra={"run_id": run_id, "source": adapter.slug, "error": str(exc), "retryable": retryable},
        )
        return {
            **counters,
            "status": "FAILED",
            "error": str(exc),
            "retryable": retryable,
            "errors": [],
            "last_external_id": None,
            "last_published_at": None,
        }

    counters["fetched"] = len(candidates)
    skip = await _external_ids_to_skip(conn, source_id, [c.external_id for c in candidates], settings)
    touched_ids: list[str] = []
    latest_published: datetime | None = None

    for candidate in candidates:
        if candidate.external_id in skip:
            counters["duplicates"] += 1
            continue

        try:
            record = await adapter.fetch_record(candidate)
        except IngestionError as exc:
            counters["failed"] += 1
            _record_error(errors, candidate.external_id, str(exc))
            logger.warning(
                "article fetch failed",
                extra={"run_id": run_id, "external_id": candidate.external_id, "error": str(exc)},
            )
            continue
        except Exception as exc:  # noqa: BLE001 — one bad article must not end the run
            counters["failed"] += 1
            _record_error(errors, candidate.external_id, f"{type(exc).__name__}: {exc}")
            logger.error(
                "article ingestion crashed",
                extra={"run_id": run_id, "external_id": candidate.external_id},
                exc_info=True,
            )
            continue

        missing = record.missing_fields()
        if missing:
            counters["failed"] += 1
            _record_error(errors, candidate.external_id, f"missing fields: {', '.join(missing)}")
            continue

        try:
            outcome, fact_item_id = await _persist(conn, source_id, record)
        except asyncpg.PostgresError as exc:
            # A single row can fail (constraint race, bad encoding) without the
            # connection being lost. Count it and keep going; if the database
            # itself is gone the next statement raises out of the loop.
            counters["failed"] += 1
            _record_error(errors, candidate.external_id, f"database: {type(exc).__name__}")
            logger.error(
                "fact item persist failed",
                extra={"run_id": run_id, "external_id": candidate.external_id},
                exc_info=True,
            )
            continue

        counters["duplicates" if outcome == "duplicate" else outcome] += 1
        if fact_item_id and outcome in {"created", "updated"}:
            touched_ids.append(fact_item_id)
        if record.published_at and (latest_published is None or record.published_at > latest_published):
            latest_published = record.published_at

    if touched_ids and settings.fact_ingestion_auto_sync:
        synced, sync_failed, sync_error = await _sync_to_knowledge_base(touched_ids, settings, run_id)
        counters["synced"] = synced
        counters["sync_failed"] = sync_failed
        if sync_error:
            _record_error(errors, "sync", sync_error)

    status = _run_status(counters)
    return {
        **counters,
        "status": status,
        "error": None,
        # Item-level failures are not worth a Celery retry: the same malformed
        # article would fail identically. Only source-level failures are.
        "retryable": False,
        "errors": errors,
        "last_external_id": candidates[0].external_id if candidates else None,
        "last_published_at": latest_published,
    }


def _run_status(counters: dict[str, int]) -> str:
    if counters["failed"] or counters["sync_failed"]:
        # Something landed and something didn't — an operator needs to see the
        # difference, so PARTIAL is a real outcome rather than rounded to
        # SUCCESS or FAILED.
        if counters["created"] or counters["updated"] or counters["duplicates"]:
            return "PARTIAL"
        return "FAILED"
    return "SUCCESS"


async def _ensure_source(conn: asyncpg.Connection, adapter: FactCheckSourceAdapter) -> int:
    """The adapter's `fact_sources` row, created once and then reused.

    Adopts a pre-existing row with the same name (the seeded "TurnBackHoax")
    by stamping its slug rather than inserting a twin — operators already have
    fact items pointing at that row.
    """
    source_id = await conn.fetchval("SELECT id FROM fact_sources WHERE slug = $1", adapter.slug)
    if source_id:
        return source_id

    # `reliability_score` is seeded on adoption/creation and never written
    # again: after that it belongs to whoever operates the Control Panel.
    adopted = await conn.fetchval(
        """
        UPDATE fact_sources
        SET slug = $1, reliability_score = $3
        WHERE slug IS NULL AND name = $2
        RETURNING id
        """,
        adapter.slug,
        adapter.source_name,
        adapter.reliability,
    )
    if adopted:
        logger.info("adopted existing fact source", extra={"source": adapter.slug, "source_id": adopted})
        return adopted

    inserted = await conn.fetchval(
        """
        INSERT INTO fact_sources (name, base_url, is_trusted, slug, reliability_score)
        VALUES ($1, $2, $3, $4, $5)
        ON CONFLICT (slug) WHERE slug IS NOT NULL DO UPDATE SET base_url = EXCLUDED.base_url
        RETURNING id
        """,
        adapter.source_name,
        adapter.base_url,
        adapter.is_trusted,
        adapter.slug,
        adapter.reliability,
    )
    logger.info("created fact source", extra={"source": adapter.slug, "source_id": inserted})
    return inserted


async def _external_ids_to_skip(
    conn: asyncpg.Connection, source_id: int, ids: list[str], settings: Settings
) -> set[str]:
    """Which of these candidates need no article request this run.

    Everything already stored is skipped, with one exception: a young article
    that has not been looked at for a while is re-read, because fact-check
    organisations do publish corrections and a stronger ruling on an old
    article is exactly the kind of change the knowledge base must not miss.
    The window keeps that bounded — without it, "notice edits" would mean
    re-downloading every article in the feed on every tick.
    """
    if not ids:
        return set()

    rows = await conn.fetch(
        """
        SELECT external_id, ingested_at, published_at
        FROM fact_items
        WHERE source_id = $1 AND external_id = ANY($2::text[])
        """,
        source_id,
        ids,
    )

    refresh_after = settings.fact_ingestion_refresh_after_hours
    window = timedelta(days=settings.fact_ingestion_refresh_window_days)
    now = datetime.now(timezone.utc)

    skip: set[str] = set()
    for row in rows:
        if refresh_after <= 0 or row["ingested_at"] is None:
            skip.add(row["external_id"])
            continue
        due = now - row["ingested_at"] >= timedelta(hours=refresh_after)
        reference = row["published_at"] or row["ingested_at"]
        young = now - reference <= window
        if not (due and young):
            skip.add(row["external_id"])
    return skip


async def _persist(
    conn: asyncpg.Connection, source_id: int, record: NormalizedFactRecord
) -> tuple[str, str | None]:
    """Insert or update one fact item. Returns `(outcome, fact_item_id)`.

    Three dedup keys, in order of trustworthiness: the source's own id, the
    canonical URL, then the content fingerprint. The fingerprint doubles as
    the change detector — a match on identity with a different fingerprint is
    the source having edited the article, which is an UPDATE.

    `published_at` is written from the source and never from the clock;
    `ingested_at` is the clock. `updated_at` maintains itself via the trigger
    from 001_init_schema.sql.
    """
    fingerprint = record.fingerprint()
    metadata = json.dumps(record.raw_metadata, default=str, ensure_ascii=False)

    existing = await conn.fetchrow(
        """
        SELECT id, content_fingerprint
        FROM fact_items
        WHERE source_id = $1
          AND (
                (external_id IS NOT NULL AND external_id = $2)
             OR source_url = $3
             OR (content_fingerprint IS NOT NULL AND content_fingerprint = $4)
          )
        LIMIT 1
        """,
        source_id,
        record.external_id,
        record.source_url,
        fingerprint,
    )

    if existing is not None:
        if existing["content_fingerprint"] == fingerprint:
            return "duplicate", str(existing["id"])
        await conn.execute(
            """
            UPDATE fact_items
            SET category = $2::category_enum,
                title = $3,
                claim_summary = $4,
                fact_explanation = $5,
                verdict = $6::verdict_enum,
                source_url = $7,
                external_id = $8,
                content_fingerprint = $9,
                published_at = COALESCE($10, published_at),
                ingested_at = CURRENT_TIMESTAMP,
                raw_metadata = $11::jsonb,
                -- Content changed, so whatever is in Qdrant is now stale:
                -- clear the sync marks so the KB screen shows it as pending
                -- even if the re-sync below fails.
                synced_at = NULL,
                sync_error = NULL
            WHERE id = $1
            """,
            existing["id"],
            record.category,
            record.title,
            record.claim_text,
            record.fact_explanation,
            record.verdict,
            record.source_url,
            record.external_id,
            fingerprint,
            record.published_at,
            metadata,
        )
        return "updated", str(existing["id"])

    inserted = await conn.fetchrow(
        """
        INSERT INTO fact_items (
            source_id, category, title, claim_summary, fact_explanation, verdict, source_url,
            external_id, content_fingerprint, published_at, ingested_at, raw_metadata
        )
        VALUES ($1, $2::category_enum, $3, $4, $5, $6::verdict_enum, $7, $8, $9, $10,
                CURRENT_TIMESTAMP, $11::jsonb)
        -- Backstop for two overlapping runs: the SELECT above can miss a row
        -- another run inserted a millisecond ago, the unique index cannot.
        ON CONFLICT (source_id, external_id) WHERE external_id IS NOT NULL DO NOTHING
        RETURNING id
        """,
        source_id,
        record.category,
        record.title,
        record.claim_text,
        record.fact_explanation,
        record.verdict,
        record.source_url,
        record.external_id,
        fingerprint,
        record.published_at,
        metadata,
    )
    if inserted is None:
        return "duplicate", None
    return "created", str(inserted["id"])


async def _sync_to_knowledge_base(
    fact_item_ids: list[str], settings: Settings, run_id: str
) -> tuple[int, int, str | None]:
    """Push the run's new/changed items through the existing KB sync path.

    A sync failure is not an ingestion failure: the facts are safely in
    PostgreSQL and `sync_error` is already recorded per row by
    `sync_fact_items`, so the next run — or the operator's "Sync All" — picks
    them up. The run is marked PARTIAL so it is visible either way.
    """
    try:
        result = await knowledge.sync_fact_items(fact_item_ids, settings=settings)
    except Exception as exc:  # noqa: BLE001 — the ML Service being down must not lose the facts
        logger.error(
            "knowledge sync failed after ingestion",
            extra={"run_id": run_id, "items": len(fact_item_ids)},
            exc_info=True,
        )
        return 0, len(fact_item_ids), f"{type(exc).__name__}: {exc}"

    return int(result.get("upserted", 0)), int(result.get("failed", 0)), None


async def _finish_run(conn: asyncpg.Connection, run_id: str, outcome: dict[str, Any]) -> None:
    await conn.execute(
        """
        UPDATE fact_ingestion_runs
        SET status = $2::ingestion_run_status_enum,
            finished_at = CURRENT_TIMESTAMP,
            fetched = $3, created = $4, updated = $5, duplicates = $6,
            failed = $7, synced = $8, sync_failed = $9,
            error = $10, details = $11::jsonb
        WHERE id = $1
        """,
        run_id,
        outcome["status"],
        outcome["fetched"],
        outcome["created"],
        outcome["updated"],
        outcome["duplicates"],
        outcome["failed"],
        outcome["synced"],
        outcome["sync_failed"],
        outcome["error"],
        json.dumps({"errors": outcome["errors"], "retryable": outcome["retryable"]}, ensure_ascii=False),
    )


async def _update_cursor(
    conn: asyncpg.Connection, slug: str, run_id: str, outcome: dict[str, Any]
) -> None:
    """Remember where the last run got to.

    `last_success_at` only moves when something actually completed, so
    "when did ingestion last work" stays answerable after a string of failed
    runs. The cursor is never the dedup mechanism (the unique index is), so a
    stale one costs a re-read of ten feed entries, nothing more.
    """
    succeeded = outcome["status"] in {"SUCCESS", "PARTIAL"}
    await conn.execute(
        """
        INSERT INTO fact_ingestion_cursors (
            source_slug, last_external_id, last_published_at, last_success_at, last_run_id, updated_at
        )
        VALUES ($1, $2, $3, CASE WHEN $4::boolean THEN CURRENT_TIMESTAMP END, $5, CURRENT_TIMESTAMP)
        ON CONFLICT (source_slug) DO UPDATE SET
            last_external_id = COALESCE(EXCLUDED.last_external_id, fact_ingestion_cursors.last_external_id),
            last_published_at = GREATEST(
                EXCLUDED.last_published_at, fact_ingestion_cursors.last_published_at
            ),
            last_success_at = COALESCE(EXCLUDED.last_success_at, fact_ingestion_cursors.last_success_at),
            last_run_id = EXCLUDED.last_run_id,
            updated_at = CURRENT_TIMESTAMP
        """,
        slug,
        outcome["last_external_id"],
        outcome["last_published_at"],
        succeeded,
        run_id,
    )


def _record_error(errors: list[dict[str, str]], external_id: str, reason: str) -> None:
    if len(errors) < MAX_RECORDED_ERRORS:
        errors.append({"external_id": external_id, "reason": reason[:500]})


async def run_all_sources(
    *, triggered_by: str = "SCHEDULE", settings: Settings | None = None
) -> list[dict[str, Any]]:
    """Every configured source, in order. One source failing never stops the next."""
    settings = settings or get_settings()
    summaries: list[dict[str, Any]] = []
    for slug in settings.fact_ingestion_source_list:
        try:
            summaries.append(await run_ingestion(slug, triggered_by=triggered_by, settings=settings))
        except Exception as exc:  # noqa: BLE001 — reported, never silent
            logger.error("ingestion source run failed", extra={"source": slug}, exc_info=True)
            summaries.append(
                {"source": slug, "status": "FAILED", "error": f"{type(exc).__name__}: {exc}", "retryable": True}
            )
    return summaries


# --------------------------------------------------------------------------
# Read paths — the Control Panel's "is the knowledge base still being fed?"
# --------------------------------------------------------------------------


def _row_to_run(row: asyncpg.Record) -> dict[str, Any]:
    details = row["details"]
    if isinstance(details, str):
        try:
            details = json.loads(details)
        except ValueError:
            details = None
    return {
        "id": str(row["id"]),
        "source_slug": row["source_slug"],
        "status": row["status"],
        "triggered_by": row["triggered_by"],
        "started_at": row["started_at"].isoformat() if row["started_at"] else None,
        "finished_at": row["finished_at"].isoformat() if row["finished_at"] else None,
        "fetched": row["fetched"],
        "created": row["created"],
        "updated": row["updated"],
        "duplicates": row["duplicates"],
        "failed": row["failed"],
        "synced": row["synced"],
        "sync_failed": row["sync_failed"],
        "error": row["error"],
        "details": details,
    }


async def list_ingestion_runs(
    limit: int = 25, offset: int = 0, *, source_slug: str | None = None, settings: Settings | None = None
) -> dict[str, Any]:
    settings = settings or get_settings()
    where = "WHERE source_slug = $1" if source_slug else ""
    params: list[Any] = [source_slug] if source_slug else []

    conn = await _connect(settings)
    try:
        rows = await conn.fetch(
            f"{RUN_SQL_BASE} {where} ORDER BY started_at DESC LIMIT ${len(params) + 1} OFFSET ${len(params) + 2}",
            *params,
            limit,
            offset,
        )
        total = await conn.fetchval(
            f"SELECT count(*) FROM fact_ingestion_runs {where}", *params
        )
    finally:
        await conn.close()

    return {"total": total, "items": [_row_to_run(row) for row in rows]}


async def get_ingestion_status(settings: Settings | None = None) -> dict[str, Any]:
    """One block per configured source: last run, last success, freshness.

    Answers, without a second monitoring system: when did ingestion last run,
    how many items were fetched/new/duplicate/failed, when did it last
    succeed, and which source is failing.
    """
    settings = settings or get_settings()

    conn = await _connect(settings)
    try:
        cursors = {
            row["source_slug"]: row
            for row in await conn.fetch(
                "SELECT source_slug, last_external_id, last_published_at, last_success_at"
                " FROM fact_ingestion_cursors"
            )
        }
        latest = {
            row["source_slug"]: row
            for row in await conn.fetch(
                f"""
                SELECT DISTINCT ON (source_slug) {RUN_COLUMNS}
                FROM fact_ingestion_runs
                ORDER BY source_slug, started_at DESC
                """
            )
        }
        ingested_counts = {
            row["slug"]: row["count"]
            for row in await conn.fetch(
                """
                SELECT fs.slug AS slug, count(*) AS count
                FROM fact_items fi
                JOIN fact_sources fs ON fs.id = fi.source_id
                WHERE fs.slug IS NOT NULL AND fi.external_id IS NOT NULL
                GROUP BY fs.slug
                """
            )
        }
    finally:
        await conn.close()

    sources = []
    for slug in settings.fact_ingestion_source_list:
        cursor = cursors.get(slug)
        run = latest.get(slug)
        sources.append(
            {
                "slug": slug,
                "enabled": settings.fact_ingestion_enabled,
                "interval_minutes": settings.fact_ingestion_interval_minutes,
                "ingested_facts": ingested_counts.get(slug, 0),
                "last_success_at": (
                    cursor["last_success_at"].isoformat()
                    if cursor and cursor["last_success_at"]
                    else None
                ),
                "last_published_at": (
                    cursor["last_published_at"].isoformat()
                    if cursor and cursor["last_published_at"]
                    else None
                ),
                "last_run": _row_to_run(run) if run else None,
            }
        )

    return {"available": True, "sources": sources, "generated_at": datetime.now(timezone.utc).isoformat()}
