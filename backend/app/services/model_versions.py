"""AI/ML Model Registry & Deployment (04_AI_and_ML/07_Model_Registry_and_Deployment.md).

Lifecycle: `CANDIDATE -> VALIDATED -> PRODUCTION -> ARCHIVED`. A row is
always system-created — `create_model_version_candidate` is called only
from `app.services.model_evaluations.execute_model_evaluation`'s success
path, never from a route, and never automatically promoted (§3: "a new
model is never automatically production"). From `CANDIDATE` onward, only
explicit human `PATCH` actions (`VALIDATE`/`PROMOTE`/`ARCHIVE`) move a row
forward. `PROMOTE` is transactional: promoting to `PRODUCTION` atomically
demotes whatever row currently holds `PRODUCTION` to `ARCHIVED` (§5 —
rollback *is* re-promoting an archived version, and that demotion must
itself be audited as its own event, not folded into the promotion's
metadata).
"""

import json
import logging
from typing import Any, Literal

import asyncpg

from app.core.config import Settings, get_settings

logger = logging.getLogger("app.services.model_versions")

ModelVersionAction = Literal["VALIDATE", "PROMOTE", "ARCHIVE"]

_STATUS_TRANSITIONS: dict[str, set[str]] = {
    "VALIDATE": {"CANDIDATE"},
    "PROMOTE": {"VALIDATED", "ARCHIVED"},
    "ARCHIVE": {"CANDIDATE", "VALIDATED", "PRODUCTION"},
}

ITEM_SQL_BASE = """
SELECT
    mv.id, mv.training_job_id, t.base_model AS training_job_base_model, t.generated_model_version,
    td.name AS training_dataset_name, td.version AS training_dataset_version,
    mv.model_evaluation_id, e.metrics AS evaluation_metrics,
    ed.name AS evaluation_dataset_name, ed.version AS evaluation_dataset_version,
    mv.status::text AS status, mv.created_at, mv.updated_at
FROM model_versions mv
JOIN training_jobs t ON t.id = mv.training_job_id
JOIN datasets td ON td.id = t.dataset_id
JOIN model_evaluations e ON e.id = mv.model_evaluation_id
JOIN datasets ed ON ed.id = e.dataset_id
"""


async def _connect(settings: Settings) -> asyncpg.Connection:
    return await asyncpg.connect(settings.database_url, timeout=5)


def _row_to_item(row: asyncpg.Record) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "training_job_id": str(row["training_job_id"]),
        "training_job_base_model": row["training_job_base_model"],
        "generated_model_version": row["generated_model_version"],
        "training_dataset_name": row["training_dataset_name"],
        "training_dataset_version": row["training_dataset_version"],
        "model_evaluation_id": str(row["model_evaluation_id"]),
        "evaluation_metrics": (
            json.loads(row["evaluation_metrics"])
            if isinstance(row["evaluation_metrics"], str)
            else row["evaluation_metrics"]
        ),
        "evaluation_dataset_name": row["evaluation_dataset_name"],
        "evaluation_dataset_version": row["evaluation_dataset_version"],
        "status": row["status"],
        "created_at": row["created_at"].isoformat(),
        "updated_at": row["updated_at"].isoformat(),
    }


async def list_model_versions(
    limit: int = 25, offset: int = 0, *, status: str | None = None, settings: Settings | None = None
) -> dict[str, Any]:
    settings = settings or get_settings()

    clauses: list[str] = []
    params: list[Any] = []
    if status:
        params.append(status)
        clauses.append(f"mv.status = ${len(params)}::model_version_status_enum")

    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows_sql = (
        f"{ITEM_SQL_BASE} {where_sql} ORDER BY mv.created_at DESC "
        f"LIMIT ${len(params) + 1} OFFSET ${len(params) + 2}"
    )
    count_sql = f"SELECT count(*) FROM model_versions mv {where_sql}"

    conn = await _connect(settings)
    try:
        rows = await conn.fetch(rows_sql, *params, limit, offset)
        total = await conn.fetchval(count_sql, *params)
    finally:
        await conn.close()

    return {"total": total, "items": [_row_to_item(row) for row in rows]}


async def get_model_version(model_version_id: str, settings: Settings | None = None) -> dict[str, Any] | None:
    settings = settings or get_settings()
    conn = await _connect(settings)
    try:
        row = await conn.fetchrow(f"{ITEM_SQL_BASE} WHERE mv.id = $1", model_version_id)
    finally:
        await conn.close()
    return _row_to_item(row) if row else None


async def create_model_version_candidate(
    conn: asyncpg.Connection, training_job_id: str, model_evaluation_id: str
) -> str:
    """Insert a `CANDIDATE` row on an existing connection/transaction —
    called from `model_evaluations.execute_model_evaluation`'s success path
    so eval-completes-implies-candidate-exists is atomic, not best-effort.
    No `created_by`: this row is always system-created, never by a human.
    """
    inserted = await conn.fetchrow(
        """
        INSERT INTO model_versions (training_job_id, model_evaluation_id, status)
        VALUES ($1, $2, 'CANDIDATE'::model_version_status_enum)
        RETURNING id
        """,
        training_job_id,
        model_evaluation_id,
    )
    return str(inserted["id"])


async def apply_model_version_action(
    model_version_id: str, *, action: ModelVersionAction, settings: Settings | None = None
) -> dict[str, Any] | None:
    """`None` if the model version doesn't exist. Raises `ValueError` for an
    invalid transition. `PROMOTE` atomically demotes whatever row currently
    holds `PRODUCTION` to `ARCHIVED` first (§5's rollback rule). Returns
    `previous_status` and `demoted_version_id` (`None` unless a real
    demotion happened) so the route can fire a second, distinct audit entry
    for the demoted row.
    """
    settings = settings or get_settings()

    conn = await _connect(settings)
    try:
        current = await conn.fetchrow("SELECT status::text AS status FROM model_versions WHERE id = $1", model_version_id)
        if current is None:
            return None
        if current["status"] not in _STATUS_TRANSITIONS[action]:
            raise ValueError(f"cannot {action} a model version in status {current['status']}")

        previous_status = current["status"]
        demoted_version_id: str | None = None

        if action == "PROMOTE":
            async with conn.transaction():
                old_production = await conn.fetchrow(
                    "SELECT id FROM model_versions WHERE status = 'PRODUCTION' FOR UPDATE"
                )
                if old_production is not None:
                    demoted_version_id = str(old_production["id"])
                    await conn.execute(
                        "UPDATE model_versions SET status = 'ARCHIVED'::model_version_status_enum WHERE id = $1",
                        demoted_version_id,
                    )
                await conn.execute(
                    "UPDATE model_versions SET status = 'PRODUCTION'::model_version_status_enum WHERE id = $1",
                    model_version_id,
                )
        else:
            new_status = {"VALIDATE": "VALIDATED", "ARCHIVE": "ARCHIVED"}[action]
            await conn.execute(
                "UPDATE model_versions SET status = $2::model_version_status_enum WHERE id = $1",
                model_version_id,
                new_status,
            )

        row = await conn.fetchrow(f"{ITEM_SQL_BASE} WHERE mv.id = $1", model_version_id)
    finally:
        await conn.close()

    result = _row_to_item(row)
    result["previous_status"] = previous_status
    result["demoted_version_id"] = demoted_version_id
    return result
