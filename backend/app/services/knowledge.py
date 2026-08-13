"""AI/ML Knowledge Base (04_AI_and_ML/03_Knowledge_Base.md).

CRUD over `fact_items`/`fact_sources` plus a real sync path into the ML
Service's `/v1/kb/upsert` (Qdrant collection `fact_knowledge_base`) — the
operator-facing replacement for the CLI-only `app.scripts.ingest_knowledge`.
`fetch_facts_for_sync`/`sync_fact_items` are the shared core that script now
imports from here, so there is exactly one implementation of "read
fact_items, POST them to the ML Service."

No raw-document upload/parse/chunk pipeline lives here — the spec's own
ownership table marks parsing/chunking "belum diputuskan," and that would be
a structurally different (multi-vector-per-document) model than the
single-point-per-fact_item model the ML Service already implements. Left
out, not faked.

Deactivating a fact does not delete its Qdrant point — per
`ingest_knowledge.py`'s own prior design note, the retrieval filter (not the
point's absence) is what keeps a retired fact out of results, so
deactivate+resync is a metadata change, not a re-embed. Whether `rag-query`
actually filters on `is_active` is an `orchestrator.py`/`inference.py`
concern, out of scope here.
"""

import logging
from typing import Any, Literal

import asyncpg

from app.clients.ml_client import MlClient, MlServiceError
from app.core.config import Settings, get_settings

logger = logging.getLogger("app.services.knowledge")

FactItemAction = Literal["UPDATE", "ACTIVATE", "DEACTIVATE"]

CSV_REQUIRED_COLUMNS = ("source_id", "category", "title", "claim_summary", "fact_explanation", "verdict", "source_url")
_VALID_CATEGORIES = {"HEALTH_HOAX", "FINANCIAL_FRAUD", "GENERAL_NEWS", "PHISHING_LINK", "FILE_APK"}
_VALID_VERDICTS = {"HOAX", "FACT", "MISLEADING", "UNVERIFIED"}

ITEM_SQL_BASE = """
SELECT
    fi.id, fi.source_id, fs.name AS source_name, fi.category::text AS category,
    fi.title, fi.claim_summary, fi.fact_explanation, fi.verdict::text AS verdict,
    fi.source_url, fi.is_active, fi.synced_at, fi.sync_error,
    fi.created_at, fi.updated_at
FROM fact_items fi
LEFT JOIN fact_sources fs ON fs.id = fi.source_id
"""

SELECT_FACTS_FOR_SYNC = """
SELECT
    fi.id::text        AS fact_item_id,
    fi.category::text  AS category,
    fi.title,
    fi.claim_summary   AS claim_text,
    fi.fact_explanation,
    fi.verdict::text   AS verdict,
    fi.source_url,
    fi.external_id,
    fi.published_at,
    fi.is_active,
    fi.updated_at,
    coalesce(fs.name, '') AS source_name,
    fs.reliability_score
FROM fact_items fi
LEFT JOIN fact_sources fs ON fs.id = fi.source_id
WHERE ($1::boolean OR fi.is_active = TRUE)
  AND ($2::uuid[] IS NULL OR fi.id = ANY($2::uuid[]))
ORDER BY fi.updated_at
"""


async def _connect(settings: Settings) -> asyncpg.Connection:
    return await asyncpg.connect(settings.database_url, timeout=5)


def _row_to_item(row: asyncpg.Record) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "source_id": row["source_id"],
        "source_name": row["source_name"],
        "category": row["category"],
        "title": row["title"],
        "claim_summary": row["claim_summary"],
        "fact_explanation": row["fact_explanation"],
        "verdict": row["verdict"],
        "source_url": row["source_url"],
        "is_active": row["is_active"],
        "synced_at": row["synced_at"].isoformat() if row["synced_at"] else None,
        "sync_error": row["sync_error"],
        "created_at": row["created_at"].isoformat(),
        "updated_at": row["updated_at"].isoformat(),
    }


async def list_fact_items(
    limit: int = 25,
    offset: int = 0,
    *,
    category: str | None = None,
    verdict: str | None = None,
    is_active: bool | None = None,
    source_id: int | None = None,
    search: str | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    settings = settings or get_settings()

    clauses: list[str] = []
    params: list[Any] = []

    def add(clause: str, value: Any) -> None:
        params.append(value)
        clauses.append(clause.format(len(params)))

    if category:
        add("fi.category = ${}::category_enum", category)
    if verdict:
        add("fi.verdict = ${}::verdict_enum", verdict)
    if is_active is not None:
        add("fi.is_active = ${}", is_active)
    if source_id is not None:
        add("fi.source_id = ${}", source_id)
    if search:
        params.append(f"%{search}%")
        n = len(params)
        clauses.append(f"(fi.title ILIKE ${n} OR fi.claim_summary ILIKE ${n})")

    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows_sql = (
        f"{ITEM_SQL_BASE} {where_sql} ORDER BY fi.updated_at DESC "
        f"LIMIT ${len(params) + 1} OFFSET ${len(params) + 2}"
    )
    count_sql = f"SELECT count(*) FROM fact_items fi {where_sql}"

    conn = await _connect(settings)
    try:
        rows = await conn.fetch(rows_sql, *params, limit, offset)
        total = await conn.fetchval(count_sql, *params)
    finally:
        await conn.close()

    return {"total": total, "items": [_row_to_item(row) for row in rows]}


async def get_fact_item(fact_item_id: str, settings: Settings | None = None) -> dict[str, Any] | None:
    settings = settings or get_settings()
    conn = await _connect(settings)
    try:
        row = await conn.fetchrow(f"{ITEM_SQL_BASE} WHERE fi.id = $1", fact_item_id)
    finally:
        await conn.close()
    return _row_to_item(row) if row else None


async def create_fact_item(
    source_id: int,
    category: str,
    title: str,
    claim_summary: str,
    fact_explanation: str,
    verdict: str,
    source_url: str,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Raises `ValueError` if `source_id` doesn't reference a real `fact_sources` row."""
    settings = settings or get_settings()

    conn = await _connect(settings)
    try:
        source_exists = await conn.fetchval("SELECT 1 FROM fact_sources WHERE id = $1", source_id)
        if not source_exists:
            raise ValueError(f"source_id {source_id} does not exist")

        inserted = await conn.fetchrow(
            """
            INSERT INTO fact_items (source_id, category, title, claim_summary, fact_explanation, verdict, source_url)
            VALUES ($1, $2::category_enum, $3, $4, $5, $6::verdict_enum, $7)
            RETURNING id
            """,
            source_id,
            category,
            title,
            claim_summary,
            fact_explanation,
            verdict,
            source_url,
        )
        row = await conn.fetchrow(f"{ITEM_SQL_BASE} WHERE fi.id = $1", inserted["id"])
    finally:
        await conn.close()

    return _row_to_item(row)


async def apply_fact_item_action(
    fact_item_id: str,
    *,
    action: FactItemAction,
    category: str | None = None,
    title: str | None = None,
    claim_summary: str | None = None,
    fact_explanation: str | None = None,
    verdict: str | None = None,
    source_url: str | None = None,
    settings: Settings | None = None,
) -> dict[str, Any] | None:
    """`None` if the fact item doesn't exist. Raises `ValueError` if `UPDATE`
    carries no fields. `ACTIVATE`/`DEACTIVATE` are idempotent flips of
    `is_active` — genuinely binary, not a lifecycle, so no transition guard
    like Detection Rules'/Policies' `status` needed.

    The returned dict carries `previous_active` (only set for
    `ACTIVATE`/`DEACTIVATE`) for the route's audit call.
    """
    settings = settings or get_settings()

    if action == "UPDATE" and all(
        v is None for v in (category, title, claim_summary, fact_explanation, verdict, source_url)
    ):
        raise ValueError("UPDATE requires at least one field")

    conn = await _connect(settings)
    try:
        current = await conn.fetchrow("SELECT is_active FROM fact_items WHERE id = $1", fact_item_id)
        if current is None:
            return None

        previous_active: bool | None = None

        if action == "UPDATE":
            sets: list[str] = []
            params: list[Any] = []
            if category is not None:
                params.append(category)
                sets.append(f"category = ${len(params)}::category_enum")
            if title is not None:
                params.append(title)
                sets.append(f"title = ${len(params)}")
            if claim_summary is not None:
                params.append(claim_summary)
                sets.append(f"claim_summary = ${len(params)}")
            if fact_explanation is not None:
                params.append(fact_explanation)
                sets.append(f"fact_explanation = ${len(params)}")
            if verdict is not None:
                params.append(verdict)
                sets.append(f"verdict = ${len(params)}::verdict_enum")
            if source_url is not None:
                params.append(source_url)
                sets.append(f"source_url = ${len(params)}")
            params.append(fact_item_id)
            await conn.execute(f"UPDATE fact_items SET {', '.join(sets)} WHERE id = ${len(params)}", *params)
        else:
            previous_active = current["is_active"]
            new_active = action == "ACTIVATE"
            await conn.execute("UPDATE fact_items SET is_active = $2 WHERE id = $1", fact_item_id, new_active)

        row = await conn.fetchrow(f"{ITEM_SQL_BASE} WHERE fi.id = $1", fact_item_id)
    finally:
        await conn.close()

    result = _row_to_item(row)
    result["previous_active"] = previous_active
    return result


async def fetch_facts_for_sync(
    conn: asyncpg.Connection, *, only_ids: list[str] | None = None, include_inactive: bool = True
) -> list[dict[str, Any]]:
    """Rows in the shape `/v1/kb/upsert` expects.

    `source_name`/`source_url` are the provenance the LLM cites through the
    existing evidence mechanism; `external_id`/`published_at` ride along so a
    retrieved point can be traced back to the source's own article and dated
    without a round trip to PostgreSQL. Automatically ingested facts and
    hand-entered ones travel this same path — the extra fields are simply
    empty for the latter.

    `source_reliability` is denormalised out of `fact_sources` for the same
    reason: ml-service re-ranks retrieved matches by it and has no database to
    join against. That makes re-sync the mechanism by which a changed score
    reaches retrieval — see `apply_fact_source_action`.
    """
    rows = await conn.fetch(SELECT_FACTS_FOR_SYNC, include_inactive, only_ids)
    return [
        {
            "fact_item_id": row["fact_item_id"],
            "category": row["category"],
            "title": row["title"],
            "claim_text": row["claim_text"],
            "fact_explanation": row["fact_explanation"],
            "verdict": row["verdict"],
            "source_name": row["source_name"],
            "source_url": row["source_url"],
            "external_id": row["external_id"],
            "published_at": row["published_at"].isoformat() if row["published_at"] else None,
            "source_reliability": (
                float(row["reliability_score"]) if row["reliability_score"] is not None else None
            ),
            "is_active": row["is_active"],
            "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
        }
        for row in rows
    ]


async def sync_fact_items(
    ids: list[str] | None = None,
    *,
    include_inactive: bool = True,
    batch_size: int = 25,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Push `fact_items` to the ML Service's real `/v1/kb/upsert`. `ids=None`
    means "sync everything" (used by both "Sync All" and the CLI script);
    a non-`None` list is what the single-item Sync button passes.

    Writes `synced_at`/`sync_error` back onto every affected row so the UI's
    sync-status column reflects the real, most recent outcome — never
    silently reports success.
    """
    settings = settings or get_settings()
    client = MlClient(settings)

    conn = await _connect(settings)
    try:
        facts = await fetch_facts_for_sync(conn, only_ids=ids, include_inactive=include_inactive)
        if not facts:
            return {"total": 0, "upserted": 0, "failed": 0, "rejected": []}

        upserted = 0
        failed = 0
        rejected_all: list[dict[str, Any]] = []

        for start in range(0, len(facts), batch_size):
            batch = facts[start : start + batch_size]
            batch_ids = [item["fact_item_id"] for item in batch]
            request_id = f"kb-sync-{start // batch_size}"

            try:
                response = await client.upsert_knowledge(request_id, batch)
            except MlServiceError as exc:
                failed += len(batch)
                await conn.execute(
                    "UPDATE fact_items SET sync_error = $2 WHERE id = ANY($1::uuid[])",
                    batch_ids,
                    f"{exc.error_code}: {exc.message}",
                )
                continue

            rejected = response.result.get("rejected") or []
            rejected_ids = {item["fact_item_id"] for item in rejected}
            succeeded_ids = [fid for fid in batch_ids if fid not in rejected_ids]
            upserted += int(response.result.get("upserted", 0))

            if succeeded_ids:
                await conn.execute(
                    "UPDATE fact_items SET synced_at = CURRENT_TIMESTAMP, sync_error = NULL WHERE id = ANY($1::uuid[])",
                    succeeded_ids,
                )
            for item in rejected:
                await conn.execute(
                    "UPDATE fact_items SET sync_error = $2 WHERE id = $1",
                    item["fact_item_id"],
                    f"rejected: missing {item.get('missing')}",
                )
                failed += 1
                rejected_all.append(item)

        return {"total": len(facts), "upserted": upserted, "failed": failed, "rejected": rejected_all}
    finally:
        await conn.close()


SOURCE_COLUMNS = "id, name, base_url, slug, is_trusted, reliability_score, created_at"


def _row_to_source(row: asyncpg.Record) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "base_url": row["base_url"],
        "slug": row["slug"],
        "is_trusted": row["is_trusted"],
        "reliability_score": float(row["reliability_score"]),
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
    }


async def list_fact_sources(settings: Settings | None = None) -> list[dict[str, Any]]:
    settings = settings or get_settings()
    conn = await _connect(settings)
    try:
        rows = await conn.fetch(
            f"""
            SELECT {SOURCE_COLUMNS},
                   (SELECT count(*) FROM fact_items fi WHERE fi.source_id = fs.id) AS fact_count,
                   (SELECT count(*) FROM fact_items fi
                     WHERE fi.source_id = fs.id AND fi.synced_at IS NOT NULL AND fi.sync_error IS NULL
                   ) AS synced_count
            FROM fact_sources fs
            ORDER BY name
            """
        )
    finally:
        await conn.close()
    return [
        # `fact_count`/`synced_count` answer the question a reliability edit
        # immediately raises: how many facts carry this score, and how many of
        # them still hold the old one in Qdrant.
        {**_row_to_source(row), "fact_count": row["fact_count"], "synced_count": row["synced_count"]}
        for row in rows
    ]


async def create_fact_source(
    name: str,
    base_url: str,
    is_trusted: bool,
    reliability_score: float | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    settings = settings or get_settings()
    conn = await _connect(settings)
    try:
        row = await conn.fetchrow(
            f"""
            INSERT INTO fact_sources (name, base_url, is_trusted, reliability_score)
            VALUES ($1, $2, $3, coalesce($4::numeric, 0.80))
            RETURNING {SOURCE_COLUMNS}
            """,
            name,
            base_url,
            is_trusted,
            reliability_score,
        )
    finally:
        await conn.close()
    return _row_to_source(row)


async def apply_fact_source_action(
    source_id: int,
    *,
    reliability_score: float | None = None,
    is_trusted: bool | None = None,
    settings: Settings | None = None,
) -> dict[str, Any] | None:
    """Update a source's trust settings. `None` if it doesn't exist.

    The returned dict carries `previous_reliability` for the route's audit
    call, and `stale_in_qdrant` — the number of this source's facts already
    synced under the old score. That number is not cosmetic: reliability is
    denormalised into each fact's Qdrant payload at sync time, so an operator
    who lowers a score and walks away has changed nothing about retrieval
    until those facts are re-synced. Saying so is better than a silent
    half-applied change.
    """
    settings = settings or get_settings()

    if reliability_score is None and is_trusted is None:
        raise ValueError("at least one of reliability_score or is_trusted is required")
    if reliability_score is not None and not 0.0 <= reliability_score <= 1.0:
        raise ValueError("reliability_score must be between 0 and 1")

    conn = await _connect(settings)
    try:
        current = await conn.fetchrow("SELECT reliability_score FROM fact_sources WHERE id = $1", source_id)
        if current is None:
            return None

        row = await conn.fetchrow(
            f"""
            UPDATE fact_sources
            SET reliability_score = coalesce($2::numeric, reliability_score),
                is_trusted = coalesce($3::boolean, is_trusted)
            WHERE id = $1
            RETURNING {SOURCE_COLUMNS}
            """,
            source_id,
            reliability_score,
            is_trusted,
        )
        stale = await conn.fetchval(
            "SELECT count(*) FROM fact_items WHERE source_id = $1 AND synced_at IS NOT NULL", source_id
        )
    finally:
        await conn.close()

    return {
        **_row_to_source(row),
        "previous_reliability": float(current["reliability_score"]),
        "stale_in_qdrant": stale,
    }


async def fact_item_ids_for_source(source_id: int, settings: Settings | None = None) -> list[str]:
    """Every fact item belonging to one source — the re-sync set after a
    reliability change."""
    settings = settings or get_settings()
    conn = await _connect(settings)
    try:
        rows = await conn.fetch("SELECT id::text AS id FROM fact_items WHERE source_id = $1", source_id)
    finally:
        await conn.close()
    return [row["id"] for row in rows]


async def import_fact_items_csv(
    rows: list[dict[str, str]], settings: Settings | None = None
) -> dict[str, Any]:
    """Bulk-create `fact_items` from parsed CSV rows — the operator-facing
    "feed the knowledge base in bulk" path (04_AI_and_ML/03_Knowledge_Base.md
    §7's "type/size validation" control, applied at the row level too).

    Each row is validated and inserted independently: a bad row is skipped
    and reported with its 1-indexed row number and reason, valid rows still
    commit. `source_id` must reference an existing `fact_sources` row —
    no get-or-create-by-name, same "validate the FK before insert"
    precedent `create_fact_item` already established. Imported items start
    exactly like a manually-created fact (`is_active=True`, never synced) —
    the operator still triggers Sync/Sync All afterward.
    """
    settings = settings or get_settings()

    conn = await _connect(settings)
    try:
        valid_source_ids = {row["id"] for row in await conn.fetch("SELECT id FROM fact_sources")}

        created = 0
        errors: list[dict[str, Any]] = []

        for index, row in enumerate(rows, start=1):
            missing = [col for col in CSV_REQUIRED_COLUMNS if not (row.get(col) or "").strip()]
            if missing:
                errors.append({"row": index, "reason": f"kolom kosong: {', '.join(missing)}"})
                continue

            category = row["category"].strip()
            verdict = row["verdict"].strip()

            if category not in _VALID_CATEGORIES:
                errors.append({"row": index, "reason": f"category tidak valid: {category}"})
                continue
            if verdict not in _VALID_VERDICTS:
                errors.append({"row": index, "reason": f"verdict tidak valid: {verdict}"})
                continue

            try:
                source_id = int(row["source_id"])
            except ValueError:
                errors.append({"row": index, "reason": f"source_id bukan angka: {row['source_id']}"})
                continue
            if source_id not in valid_source_ids:
                errors.append({"row": index, "reason": f"source_id {source_id} tidak ditemukan"})
                continue

            await conn.execute(
                """
                INSERT INTO fact_items (source_id, category, title, claim_summary, fact_explanation, verdict, source_url)
                VALUES ($1, $2::category_enum, $3, $4, $5, $6::verdict_enum, $7)
                """,
                source_id,
                category,
                row["title"].strip(),
                row["claim_summary"].strip(),
                row["fact_explanation"].strip(),
                verdict,
                row["source_url"].strip(),
            )
            created += 1
    finally:
        await conn.close()

    return {"total": len(rows), "created": created, "failed": len(errors), "errors": errors}
