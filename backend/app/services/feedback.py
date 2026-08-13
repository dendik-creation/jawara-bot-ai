"""Operator Feedback (04_AI_and_ML/04_Datasets_and_Operator_Feedback.md).

Human-in-the-loop correction events, fed only from Threats' CONFIRM/
FALSE_POSITIVE actions (Stage 2) — the roadmap's own named scope. The
spec's third button, "change classification," needs a Threats action this
system doesn't have yet and is deliberately not built here.

Independent of `threat_cases` (a resolution *overlay*, overwritten on
re-action): this table is append-only, so a message re-actioned later
doesn't erase the fact that an operator once confirmed or corrected it.

`model_version` is the ML Service's *current* model identity at the moment
feedback is recorded (via the same `MlClient.ready()` call
`services/ai_ml_overview.py` already uses), not a historically-pinned
per-message value — `message_logs` has no such column and wiring one means
touching the live pipeline, deferred same as every prior stage's pipeline
cuts. Best-effort: never blocks recording feedback if the ML Service is down.
"""

import logging
from typing import Any

import asyncpg

from app.clients.ml_client import MlClient
from app.core.config import Settings, get_settings
from app.services.audit import record_audit
from app.services.datasets import add_sample

logger = logging.getLogger("app.services.feedback")

ITEM_SQL_BASE = """
SELECT
    f.id, f.message_log_id, f.original_classification::text AS original_classification,
    f.feedback_type::text AS feedback_type, f.model_version, f.reason,
    f.actor_operator_id, o.full_name AS actor_name, f.created_at,
    m.extracted_text, m.detected_intent::text AS current_intent, m.risk_score::text AS risk_score,
    ds.dataset_id AS used_in_dataset_id, d.name AS used_in_dataset_name
FROM operator_feedback f
JOIN operators o ON o.id = f.actor_operator_id
JOIN message_logs m ON m.id = f.message_log_id
LEFT JOIN dataset_samples ds ON ds.source_feedback_id = f.id
LEFT JOIN datasets d ON d.id = ds.dataset_id
"""


async def _connect(settings: Settings) -> asyncpg.Connection:
    return await asyncpg.connect(settings.database_url, timeout=5)


def _row_to_item(row: asyncpg.Record) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "message_log_id": str(row["message_log_id"]),
        "original_classification": row["original_classification"],
        "feedback_type": row["feedback_type"],
        "model_version": row["model_version"],
        "reason": row["reason"],
        "actor_operator_id": str(row["actor_operator_id"]),
        "actor_name": row["actor_name"],
        "created_at": row["created_at"].isoformat(),
        "extracted_text": row["extracted_text"],
        "current_intent": row["current_intent"],
        "risk_score": row["risk_score"],
        "used_in_dataset_id": str(row["used_in_dataset_id"]) if row["used_in_dataset_id"] else None,
        "used_in_dataset_name": row["used_in_dataset_name"],
    }


async def record_feedback(
    message_log_id: str,
    feedback_type: str,
    actor_operator_id: str,
    reason: str | None = None,
    settings: Settings | None = None,
) -> dict[str, Any] | None:
    """`None` if the message doesn't exist. Never raises on ML Service
    unavailability — `model_version` is simply `None` in that case.
    """
    settings = settings or get_settings()

    try:
        _ready, body = await MlClient(settings).ready()
        models = body.get("models") or {}
        model_version = models.get("embedder") or None
    except Exception:  # noqa: BLE001
        logger.warning("model_version lookup failed for feedback capture", exc_info=True)
        model_version = None

    conn = await _connect(settings)
    try:
        message = await conn.fetchrow("SELECT detected_intent::text AS detected_intent FROM message_logs WHERE id = $1", message_log_id)
        if message is None:
            return None

        inserted = await conn.fetchrow(
            """
            INSERT INTO operator_feedback (message_log_id, original_classification, feedback_type, model_version, reason, actor_operator_id)
            VALUES ($1, $2::category_enum, $3::feedback_type_enum, $4, $5, $6)
            RETURNING id
            """,
            message_log_id,
            message["detected_intent"],
            feedback_type,
            model_version,
            reason,
            actor_operator_id,
        )
        row = await conn.fetchrow(f"{ITEM_SQL_BASE} WHERE f.id = $1", inserted["id"])
    finally:
        await conn.close()

    result = _row_to_item(row)

    await record_audit(
        actor_operator_id=actor_operator_id,
        action="feedback.recorded",
        target_type="operator_feedback",
        target_id=result["id"],
        result="SUCCESS",
        metadata={
            "message_log_id": message_log_id,
            "feedback_type": feedback_type,
            "original_classification": result["original_classification"],
            "model_version": model_version,
        },
        settings=settings,
    )

    return result


async def list_feedback(
    limit: int = 25,
    offset: int = 0,
    *,
    feedback_type: str | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    settings = settings or get_settings()

    clauses: list[str] = []
    params: list[Any] = []
    if feedback_type:
        params.append(feedback_type)
        clauses.append(f"f.feedback_type = ${len(params)}::feedback_type_enum")

    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows_sql = (
        f"{ITEM_SQL_BASE} {where_sql} ORDER BY f.created_at DESC "
        f"LIMIT ${len(params) + 1} OFFSET ${len(params) + 2}"
    )
    count_sql = f"SELECT count(*) FROM operator_feedback f {where_sql}"

    conn = await _connect(settings)
    try:
        rows = await conn.fetch(rows_sql, *params, limit, offset)
        total = await conn.fetchval(count_sql, *params)
    finally:
        await conn.close()

    return {"total": total, "items": [_row_to_item(row) for row in rows]}


async def promote_to_dataset(
    dataset_id: str,
    added_by: str,
    *,
    feedback_type: str | None = None,
    limit: int = 100,
    settings: Settings | None = None,
) -> dict[str, Any] | None:
    """Batch-promote reviewed feedback into `dataset_samples` — the
    active-learning loop's closing step (19_Active_Learning_Strategy):
    human confirms/corrects via Threats, an operator later triggers this to
    fold validated feedback into training data. Never automatic.

    Label derivation is a direct fact, not a guess: `FALSE_POSITIVE` means
    the operator asserted the message was not a threat -> `NOT_A_THREAT`;
    `CONFIRM` means the operator agreed with `original_classification` ->
    that same label. A `CONFIRM` row with no `original_classification`
    (message was never auto-classified) has nothing to promote and is
    skipped, not guessed at.

    Idempotent: feedback already linked to a sample via `source_feedback_id`
    is excluded, so re-running only picks up feedback recorded since the
    last run. `None` if the dataset doesn't exist; raises `ValueError` if
    it isn't `DRAFT` (mirrors `add_sample`'s own guard).
    """
    settings = settings or get_settings()

    conn = await _connect(settings)
    try:
        dataset_status = await conn.fetchval("SELECT status::text FROM datasets WHERE id = $1", dataset_id)
        if dataset_status is None:
            return None
        if dataset_status != "DRAFT":
            raise ValueError(f"cannot promote feedback into a dataset in status {dataset_status}")

        rows = await conn.fetch(
            """
            SELECT f.id, f.message_log_id, f.original_classification::text AS original_classification,
                   f.feedback_type::text AS feedback_type, m.extracted_text
            FROM operator_feedback f
            JOIN message_logs m ON m.id = f.message_log_id
            WHERE NOT EXISTS (SELECT 1 FROM dataset_samples ds WHERE ds.source_feedback_id = f.id)
              AND ($1::feedback_type_enum IS NULL OR f.feedback_type = $1::feedback_type_enum)
            ORDER BY f.created_at
            LIMIT $2
            """,
            feedback_type,
            limit,
        )
    finally:
        await conn.close()

    promoted = 0
    skipped_reasons: dict[str, int] = {}

    def _skip(reason: str) -> None:
        skipped_reasons[reason] = skipped_reasons.get(reason, 0) + 1

    for row in rows:
        if row["feedback_type"] == "FALSE_POSITIVE":
            label = "NOT_A_THREAT"
        else:
            label = row["original_classification"]
            if label is None:
                _skip("confirm_without_original_classification")
                continue

        text = row["extracted_text"]
        if not text or not text.strip():
            _skip("empty_message_text")
            continue

        await add_sample(
            dataset_id,
            text,
            label,
            added_by,
            source_message_log_id=str(row["message_log_id"]),
            source_feedback_id=str(row["id"]),
            settings=settings,
        )
        promoted += 1

    return {
        "dataset_id": dataset_id,
        "considered": len(rows),
        "promoted": promoted,
        "skipped": sum(skipped_reasons.values()),
        "skipped_reasons": skipped_reasons,
    }
