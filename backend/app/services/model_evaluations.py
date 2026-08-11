"""AI/ML Model Evaluation (04_AI_and_ML/06_Model_Evaluation.md).

Gate between "model finished training" and "model may serve production" —
the spec frames evaluation as scoring a trained model against a fixed,
independent eval/test dataset. `ml-service` has no `/v1/evaluate` route at
all yet. `execute_model_evaluation` (run from the Celery worker,
`app.worker.tasks.run_model_evaluation`) genuinely calls
`MlClient.evaluate(...)` and genuinely fails today — the same honesty
pattern already live for `/v1/train` (Stage 11) and `/v1/classify`'s
`model_not_available` before that, rather than fabricating a completed
evaluation or invented metrics.

`training_job_id` names the trained model under test (via its
`generated_model_version` — only set on `COMPLETED` training jobs, so
that's the create-time gate). `dataset_id` is an independent `VALIDATED`
dataset used as the eval/test set — not assumed equal to the training
job's own dataset.

A `COMPLETED` evaluation atomically produces a `model_versions` `CANDIDATE`
row (07_Model_Registry_and_Deployment.md) — see
`app.services.model_versions.create_model_version_candidate`.
"""

import json
import logging
from typing import Any, Literal

import asyncpg
from fastapi.concurrency import run_in_threadpool

from app.clients.ml_client import MlClient, MlServiceError
from app.core.config import Settings, get_settings
from app.services.audit import record_audit
from app.services.model_versions import create_model_version_candidate

logger = logging.getLogger("app.services.model_evaluations")

EvaluationAction = Literal["CANCEL"]

_CANCELLABLE_STATUSES = {"QUEUED", "RUNNING"}

ITEM_SQL_BASE = """
SELECT
    e.id, e.training_job_id, t.base_model AS training_job_base_model,
    t.generated_model_version, e.dataset_id, d.name AS dataset_name, d.version AS dataset_version,
    e.status::text AS status, e.progress, e.metrics, e.error_message, e.celery_task_id,
    e.started_at, e.finished_at,
    e.created_by, o.full_name AS created_by_name, e.created_at, e.updated_at
FROM model_evaluations e
JOIN training_jobs t ON t.id = e.training_job_id
JOIN datasets d ON d.id = e.dataset_id
JOIN operators o ON o.id = e.created_by
"""


async def _connect(settings: Settings) -> asyncpg.Connection:
    return await asyncpg.connect(settings.database_url, timeout=5)


def _row_to_item(row: asyncpg.Record) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "training_job_id": str(row["training_job_id"]),
        "training_job_base_model": row["training_job_base_model"],
        "generated_model_version": row["generated_model_version"],
        "dataset_id": str(row["dataset_id"]),
        "dataset_name": row["dataset_name"],
        "dataset_version": row["dataset_version"],
        "status": row["status"],
        "progress": row["progress"],
        "metrics": (json.loads(row["metrics"]) if isinstance(row["metrics"], str) else row["metrics"]),
        "error_message": row["error_message"],
        "celery_task_id": row["celery_task_id"],
        "started_at": row["started_at"].isoformat() if row["started_at"] else None,
        "finished_at": row["finished_at"].isoformat() if row["finished_at"] else None,
        "created_by": str(row["created_by"]),
        "created_by_name": row["created_by_name"],
        "created_at": row["created_at"].isoformat(),
        "updated_at": row["updated_at"].isoformat(),
    }


async def list_model_evaluations(
    limit: int = 25, offset: int = 0, *, status: str | None = None, settings: Settings | None = None
) -> dict[str, Any]:
    settings = settings or get_settings()

    clauses: list[str] = []
    params: list[Any] = []
    if status:
        params.append(status)
        clauses.append(f"e.status = ${len(params)}::model_evaluation_status_enum")

    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows_sql = (
        f"{ITEM_SQL_BASE} {where_sql} ORDER BY e.created_at DESC "
        f"LIMIT ${len(params) + 1} OFFSET ${len(params) + 2}"
    )
    count_sql = f"SELECT count(*) FROM model_evaluations e {where_sql}"

    conn = await _connect(settings)
    try:
        rows = await conn.fetch(rows_sql, *params, limit, offset)
        total = await conn.fetchval(count_sql, *params)
    finally:
        await conn.close()

    return {"total": total, "items": [_row_to_item(row) for row in rows]}


async def get_model_evaluation(evaluation_id: str, settings: Settings | None = None) -> dict[str, Any] | None:
    settings = settings or get_settings()
    conn = await _connect(settings)
    try:
        row = await conn.fetchrow(f"{ITEM_SQL_BASE} WHERE e.id = $1", evaluation_id)
    finally:
        await conn.close()
    return _row_to_item(row) if row else None


async def create_model_evaluation(
    training_job_id: str,
    dataset_id: str,
    created_by: str,
    *,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Raises `ValueError` if the training job doesn't exist or isn't
    `COMPLETED` (only a `COMPLETED` job carries a `generated_model_version`,
    the thing actually under evaluation), or if the dataset doesn't exist or
    isn't `VALIDATED` (same gate `create_training_job` already applies).
    """
    settings = settings or get_settings()

    conn = await _connect(settings)
    try:
        job = await conn.fetchrow("SELECT status::text AS status FROM training_jobs WHERE id = $1", training_job_id)
        if job is None:
            raise ValueError(f"training job {training_job_id} does not exist")
        if job["status"] != "COMPLETED":
            raise ValueError(f"training job must be COMPLETED, not {job['status']}")

        dataset = await conn.fetchrow("SELECT status::text AS status FROM datasets WHERE id = $1", dataset_id)
        if dataset is None:
            raise ValueError(f"dataset {dataset_id} does not exist")
        if dataset["status"] != "VALIDATED":
            raise ValueError(f"dataset must be VALIDATED, not {dataset['status']}")

        inserted = await conn.fetchrow(
            """
            INSERT INTO model_evaluations (training_job_id, dataset_id, created_by)
            VALUES ($1, $2, $3)
            RETURNING id
            """,
            training_job_id,
            dataset_id,
            created_by,
        )
        evaluation_id = str(inserted["id"])

        task_id = await _dispatch(evaluation_id, settings)
        await conn.execute("UPDATE model_evaluations SET celery_task_id = $2 WHERE id = $1", evaluation_id, task_id)

        row = await conn.fetchrow(f"{ITEM_SQL_BASE} WHERE e.id = $1", evaluation_id)
    finally:
        await conn.close()

    return _row_to_item(row)


async def _dispatch(evaluation_id: str, settings: Settings) -> str | None:
    """Enqueue the real Celery task. Sent by task name, never by importing the
    task function — the gateway must not pull worker/ML dependencies into the
    request path (same reasoning `services/training_jobs.py` already documents).
    """
    from app.worker import TASK_RUN_MODEL_EVALUATION, celery_app

    try:
        result = await run_in_threadpool(
            celery_app.send_task,
            TASK_RUN_MODEL_EVALUATION,
            args=[evaluation_id],
            queue=settings.celery_evaluation_queue_name,
        )
        return result.id
    except Exception:  # noqa: BLE001
        logger.error("failed to dispatch model evaluation", extra={"evaluation_id": evaluation_id}, exc_info=True)
        return None


async def apply_evaluation_action(
    evaluation_id: str, *, action: EvaluationAction, settings: Settings | None = None
) -> dict[str, Any] | None:
    """`None` if the evaluation doesn't exist. Raises `ValueError` if it isn't
    `QUEUED`/`RUNNING`. Best-effort revoke against the Celery task — an
    evaluation that fails almost instantly (no live `/v1/evaluate` to hang
    on) may finish before the revoke lands; the DB status transition is
    authoritative.
    """
    settings = settings or get_settings()

    conn = await _connect(settings)
    try:
        current = await conn.fetchrow(
            "SELECT status::text AS status, celery_task_id FROM model_evaluations WHERE id = $1", evaluation_id
        )
        if current is None:
            return None
        if current["status"] not in _CANCELLABLE_STATUSES:
            raise ValueError(f"cannot CANCEL an evaluation in status {current['status']}")

        if current["celery_task_id"]:
            try:
                from app.worker import celery_app

                celery_app.control.revoke(current["celery_task_id"], terminate=True)
            except Exception:  # noqa: BLE001
                logger.warning("celery revoke failed", extra={"evaluation_id": evaluation_id}, exc_info=True)

        await conn.execute(
            """
            UPDATE model_evaluations
            SET status = 'CANCELLED'::model_evaluation_status_enum, finished_at = CURRENT_TIMESTAMP
            WHERE id = $1
            """,
            evaluation_id,
        )
        row = await conn.fetchrow(f"{ITEM_SQL_BASE} WHERE e.id = $1", evaluation_id)
    finally:
        await conn.close()

    return _row_to_item(row)


async def execute_model_evaluation(evaluation_id: str, settings: Settings | None = None) -> None:
    """Run from the Celery worker (`app.worker.tasks.run_model_evaluation`).

    Marks RUNNING, calls the real (currently unimplemented) `/v1/evaluate`,
    and persists whatever really happens — a genuine `MlServiceError`
    becomes a genuine FAILED row with the real error text, never a faked
    COMPLETED with invented metrics.
    """
    settings = settings or get_settings()
    conn = await _connect(settings)
    try:
        job = await conn.fetchrow(
            """
            SELECT e.training_job_id, t.generated_model_version,
                   d.id AS dataset_id, d.name AS dataset_name, d.version AS dataset_version
            FROM model_evaluations e
            JOIN training_jobs t ON t.id = e.training_job_id
            JOIN datasets d ON d.id = e.dataset_id
            WHERE e.id = $1
            """,
            evaluation_id,
        )
        if job is None:
            logger.error("model evaluation vanished before execution", extra={"evaluation_id": evaluation_id})
            return

        await conn.execute(
            """
            UPDATE model_evaluations
            SET status = 'RUNNING'::model_evaluation_status_enum, started_at = CURRENT_TIMESTAMP
            WHERE id = $1
            """,
            evaluation_id,
        )

        try:
            response = await MlClient(settings).evaluate(
                request_id=f"eval-{evaluation_id}",
                model_version=job["generated_model_version"],
                dataset_ref={
                    "id": str(job["dataset_id"]),
                    "name": job["dataset_name"],
                    "version": job["dataset_version"],
                },
            )
        except MlServiceError as exc:
            await _mark_failed(conn, evaluation_id, f"{exc.error_code}: {exc.message}", settings)
            return
        except Exception as exc:  # noqa: BLE001
            await _mark_failed(conn, evaluation_id, str(exc), settings)
            return

        async with conn.transaction():
            await conn.execute(
                """
                UPDATE model_evaluations
                SET status = 'COMPLETED'::model_evaluation_status_enum, finished_at = CURRENT_TIMESTAMP,
                    metrics = $2::jsonb
                WHERE id = $1
                """,
                evaluation_id,
                json.dumps(response.result or {}),
            )
            model_version_id = await create_model_version_candidate(
                conn, str(job["training_job_id"]), evaluation_id
            )
    finally:
        await conn.close()

    await record_audit(
        actor_operator_id=None,
        action="model_version.candidate_created",
        target_type="model_version",
        target_id=model_version_id,
        result="SUCCESS",
        metadata={"training_job_id": str(job["training_job_id"]), "model_evaluation_id": evaluation_id},
        settings=settings,
    )


async def _mark_failed(conn: asyncpg.Connection, evaluation_id: str, error_message: str, settings: Settings) -> None:
    await conn.execute(
        """
        UPDATE model_evaluations
        SET status = 'FAILED'::model_evaluation_status_enum, finished_at = CURRENT_TIMESTAMP, error_message = $2
        WHERE id = $1
        """,
        evaluation_id,
        error_message,
    )
    logger.warning("model evaluation failed", extra={"evaluation_id": evaluation_id, "error": error_message})
    await record_audit(
        actor_operator_id=None,
        action="model_evaluation.failed",
        target_type="model_evaluation",
        target_id=evaluation_id,
        result="FAILED",
        metadata={"error_message": error_message},
        settings=settings,
    )
