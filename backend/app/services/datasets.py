"""AI/ML Dataset management (04_AI_and_ML/04_Datasets_and_Operator_Feedback.md).

Curated, versioned, validated training data — the input Training Jobs
(Stage 11, not yet built) will eventually consume. `label` is plain TEXT,
not `category_enum`: a dataset training this system's classifier needs a
real negative class ("NOT_A_THREAT", sourced from FALSE_POSITIVE feedback)
that the content-topic `category_enum` — already locked against extension
(Stage 8's own finding) — cannot represent.

Validation (`VALIDATE`) runs two concrete, mechanical checks synchronously
(no async job queue exists, so "VALIDATING" is never a state this system
parks in): non-empty, and no exact-duplicate sample text (the spec's
"duplicates/leakage" check) plus a raw-phone-number pattern check (the
spec's "privacy compliance" check). Label-distribution balance and semantic
label-correctness need judgement this system can't automate — left out,
not fabricated as passed.
"""

import logging
import re
from typing import Any, Literal

import asyncpg

from app.core.config import Settings, get_settings

logger = logging.getLogger("app.services.datasets")

DatasetAction = Literal["UPDATE", "VALIDATE", "ARCHIVE"]

VALID_LABELS = {"HEALTH_HOAX", "FINANCIAL_FRAUD", "GENERAL_NEWS", "PHISHING_LINK", "FILE_APK", "NOT_A_THREAT"}

# Indonesian mobile numbers: 08xxxxxxxxxx or +628xxxxxxxxxx, 9-13 digits after the prefix.
_PHONE_PATTERN = re.compile(r"(?:\+62|0)8[0-9]{7,11}")

_LOCKED_STATUSES = {"VALIDATED", "ARCHIVED"}

ITEM_SQL_BASE = """
SELECT
    d.id, d.name, d.version, d.source::text AS source, d.status::text AS status,
    d.description, d.validation_notes, d.created_by, o.full_name AS created_by_name,
    d.created_at, d.updated_at,
    (SELECT count(*) FROM dataset_samples s WHERE s.dataset_id = d.id) AS sample_count
FROM datasets d
JOIN operators o ON o.id = d.created_by
"""


async def _connect(settings: Settings) -> asyncpg.Connection:
    return await asyncpg.connect(settings.database_url, timeout=5)


def _row_to_item(row: asyncpg.Record) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "name": row["name"],
        "version": row["version"],
        "source": row["source"],
        "status": row["status"],
        "description": row["description"],
        "validation_notes": row["validation_notes"],
        "created_by": str(row["created_by"]),
        "created_by_name": row["created_by_name"],
        "created_at": row["created_at"].isoformat(),
        "updated_at": row["updated_at"].isoformat(),
        "sample_count": row["sample_count"],
    }


def _sample_to_item(row: asyncpg.Record) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "dataset_id": str(row["dataset_id"]),
        "text": row["text"],
        "label": row["label"],
        "source_message_log_id": str(row["source_message_log_id"]) if row["source_message_log_id"] else None,
        "source_feedback_id": str(row["source_feedback_id"]) if row["source_feedback_id"] else None,
        "added_by": str(row["added_by"]),
        "added_at": row["added_at"].isoformat(),
    }


async def list_datasets(
    limit: int = 25, offset: int = 0, *, status: str | None = None, settings: Settings | None = None
) -> dict[str, Any]:
    settings = settings or get_settings()

    clauses: list[str] = []
    params: list[Any] = []
    if status:
        params.append(status)
        clauses.append(f"d.status = ${len(params)}::dataset_status_enum")

    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows_sql = (
        f"{ITEM_SQL_BASE} {where_sql} ORDER BY d.created_at DESC "
        f"LIMIT ${len(params) + 1} OFFSET ${len(params) + 2}"
    )
    count_sql = f"SELECT count(*) FROM datasets d {where_sql}"

    conn = await _connect(settings)
    try:
        rows = await conn.fetch(rows_sql, *params, limit, offset)
        total = await conn.fetchval(count_sql, *params)
    finally:
        await conn.close()

    return {"total": total, "items": [_row_to_item(row) for row in rows]}


async def get_dataset(dataset_id: str, settings: Settings | None = None) -> dict[str, Any] | None:
    settings = settings or get_settings()
    conn = await _connect(settings)
    try:
        row = await conn.fetchrow(f"{ITEM_SQL_BASE} WHERE d.id = $1", dataset_id)
        if row is None:
            return None
        samples = await conn.fetch(
            "SELECT * FROM dataset_samples WHERE dataset_id = $1 ORDER BY added_at", dataset_id
        )
        label_counts = await conn.fetch(
            "SELECT label, count(*) AS count FROM dataset_samples WHERE dataset_id = $1 GROUP BY label", dataset_id
        )
    finally:
        await conn.close()

    item = _row_to_item(row)
    item["samples"] = [_sample_to_item(sample) for sample in samples]
    item["label_counts"] = {r["label"]: r["count"] for r in label_counts}
    return item


async def create_dataset(
    name: str,
    version: int,
    source: str,
    description: str | None,
    created_by: str,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Raises `ValueError` if `(name, version)` already exists."""
    settings = settings or get_settings()

    conn = await _connect(settings)
    try:
        try:
            inserted = await conn.fetchrow(
                """
                INSERT INTO datasets (name, version, source, description, created_by)
                VALUES ($1, $2, $3::dataset_source_enum, $4, $5)
                RETURNING id
                """,
                name,
                version,
                source,
                description,
                created_by,
            )
        except asyncpg.UniqueViolationError:
            raise ValueError(f"dataset '{name}' v{version} already exists") from None
        row = await conn.fetchrow(f"{ITEM_SQL_BASE} WHERE d.id = $1", inserted["id"])
    finally:
        await conn.close()

    return _row_to_item(row)


def _run_validation_checks(samples: list[asyncpg.Record]) -> list[str]:
    failures: list[str] = []

    if not samples:
        failures.append("dataset tidak punya sample")
        return failures

    seen: set[str] = set()
    duplicates: set[str] = set()
    for sample in samples:
        text = sample["text"]
        if text in seen:
            duplicates.add(text)
        seen.add(text)
    if duplicates:
        failures.append(f"{len(duplicates)} teks duplikat ditemukan")

    for sample in samples:
        if _PHONE_PATTERN.search(sample["text"]):
            failures.append("teks mengandung pola nomor telepon mentah — pelanggaran privasi")
            break

    return failures


async def apply_dataset_action(
    dataset_id: str,
    *,
    action: DatasetAction,
    name: str | None = None,
    description: str | None = None,
    settings: Settings | None = None,
) -> dict[str, Any] | None:
    """`None` if the dataset doesn't exist. Raises `ValueError` for invalid
    transitions or an `UPDATE` with no fields. Returns `previous_status` for
    `VALIDATE`/`ARCHIVE` so the route's audit call can record old+new.
    """
    settings = settings or get_settings()

    if action == "UPDATE" and name is None and description is None:
        raise ValueError("UPDATE requires at least one of name/description")

    conn = await _connect(settings)
    try:
        current = await conn.fetchrow("SELECT status::text FROM datasets WHERE id = $1", dataset_id)
        if current is None:
            return None

        previous_status: str | None = None

        if action == "UPDATE":
            if current["status"] in _LOCKED_STATUSES:
                raise ValueError(f"cannot UPDATE a dataset in status {current['status']}")
            sets: list[str] = []
            params: list[Any] = []
            if name is not None:
                params.append(name)
                sets.append(f"name = ${len(params)}")
            if description is not None:
                params.append(description)
                sets.append(f"description = ${len(params)}")
            params.append(dataset_id)
            await conn.execute(f"UPDATE datasets SET {', '.join(sets)} WHERE id = ${len(params)}", *params)

        elif action == "VALIDATE":
            if current["status"] != "DRAFT":
                raise ValueError(f"cannot VALIDATE a dataset in status {current['status']}")
            previous_status = current["status"]
            samples = await conn.fetch("SELECT text FROM dataset_samples WHERE dataset_id = $1", dataset_id)
            failures = _run_validation_checks(samples)
            new_status = "REJECTED" if failures else "VALIDATED"
            notes = "; ".join(failures) if failures else None
            await conn.execute(
                "UPDATE datasets SET status = $2::dataset_status_enum, validation_notes = $3 WHERE id = $1",
                dataset_id,
                new_status,
                notes,
            )

        else:  # ARCHIVE
            if current["status"] == "ARCHIVED":
                raise ValueError("dataset is already ARCHIVED")
            previous_status = current["status"]
            await conn.execute(
                "UPDATE datasets SET status = 'ARCHIVED'::dataset_status_enum WHERE id = $1", dataset_id
            )

        row = await conn.fetchrow(f"{ITEM_SQL_BASE} WHERE d.id = $1", dataset_id)
    finally:
        await conn.close()

    result = _row_to_item(row)
    result["previous_status"] = previous_status
    return result


async def add_sample(
    dataset_id: str,
    text: str,
    label: str,
    added_by: str,
    *,
    source_message_log_id: str | None = None,
    source_feedback_id: str | None = None,
    settings: Settings | None = None,
) -> dict[str, Any] | None:
    """`None` if the dataset doesn't exist. Raises `ValueError` for an
    invalid `label` or a dataset that isn't `DRAFT` (datasets are immutable
    once VALIDATED, for training-job reproducibility).
    """
    if label not in VALID_LABELS:
        raise ValueError(f"'label' must be one of {sorted(VALID_LABELS)}")

    settings = settings or get_settings()
    conn = await _connect(settings)
    try:
        current = await conn.fetchrow("SELECT status::text FROM datasets WHERE id = $1", dataset_id)
        if current is None:
            return None
        if current["status"] != "DRAFT":
            raise ValueError(f"cannot add a sample to a dataset in status {current['status']}")

        row = await conn.fetchrow(
            """
            INSERT INTO dataset_samples (dataset_id, text, label, source_message_log_id, source_feedback_id, added_by)
            VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING *
            """,
            dataset_id,
            text,
            label,
            source_message_log_id,
            source_feedback_id,
            added_by,
        )
    finally:
        await conn.close()

    return _sample_to_item(row)


async def remove_sample(dataset_id: str, sample_id: str, settings: Settings | None = None) -> bool | None:
    """`None` if the dataset doesn't exist, `False` if the sample doesn't,
    raises `ValueError` if the dataset isn't `DRAFT`.
    """
    settings = settings or get_settings()
    conn = await _connect(settings)
    try:
        current = await conn.fetchrow("SELECT status::text FROM datasets WHERE id = $1", dataset_id)
        if current is None:
            return None
        if current["status"] != "DRAFT":
            raise ValueError(f"cannot remove a sample from a dataset in status {current['status']}")

        deleted = await conn.fetchrow(
            "DELETE FROM dataset_samples WHERE id = $1 AND dataset_id = $2 RETURNING id", sample_id, dataset_id
        )
    finally:
        await conn.close()

    return deleted is not None
