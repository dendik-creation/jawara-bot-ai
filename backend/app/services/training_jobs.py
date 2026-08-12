"""AI/ML Training Jobs (04_AI_and_ML/05_Training_Jobs.md).

Orchestration/tracking layer for a controlled async training operation — the
spec's own responsibility table names "execute training, produce artifact"
as ML Service's job (TF-IDF + LogisticRegression, `ml-service/app/models/
classifier.py`). `execute_training_job` (run from the Celery worker,
`app.worker.tasks.run_training_job`) calls the real `MlClient.train(...)`
with the dataset's rows shipped inline (ml-service has no database of its
own) and persists whatever really happens — `response.result` (which
includes the artifact's `artifact_sha256`, later trusted by evaluation and
inference) lands verbatim in `metrics`, never fabricated.
"""

import json
import logging
from typing import Any, Literal

import asyncpg
from fastapi.concurrency import run_in_threadpool

from app.clients.ml_client import MlClient, MlServiceError
from app.core.config import Settings, get_settings
from app.services.audit import record_audit

logger = logging.getLogger("app.services.training_jobs")

JobAction = Literal["CANCEL"]

_CANCELLABLE_STATUSES = {"QUEUED", "RUNNING"}

ITEM_SQL_BASE = """
SELECT
    t.id, t.dataset_id, d.name AS dataset_name, d.version AS dataset_version,
    t.base_model, t.epochs, t.learning_rate, t.batch_size, t.validation_split, t.extra_config,
    t.status::text AS status, t.progress, t.metrics, t.error_message, t.generated_model_version,
    t.celery_task_id, t.started_at, t.finished_at,
    t.created_by, o.full_name AS created_by_name, t.created_at, t.updated_at
FROM training_jobs t
JOIN datasets d ON d.id = t.dataset_id
JOIN operators o ON o.id = t.created_by
"""


async def _connect(settings: Settings) -> asyncpg.Connection:
    return await asyncpg.connect(settings.database_url, timeout=5)


def _row_to_item(row: asyncpg.Record) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "dataset_id": str(row["dataset_id"]),
        "dataset_name": row["dataset_name"],
        "dataset_version": row["dataset_version"],
        "base_model": row["base_model"],
        "epochs": row["epochs"],
        "learning_rate": row["learning_rate"],
        "batch_size": row["batch_size"],
        "validation_split": row["validation_split"],
        "extra_config": (
            json.loads(row["extra_config"]) if isinstance(row["extra_config"], str) else row["extra_config"]
        ),
        "status": row["status"],
        "progress": row["progress"],
        "metrics": (json.loads(row["metrics"]) if isinstance(row["metrics"], str) else row["metrics"]),
        "error_message": row["error_message"],
        "generated_model_version": row["generated_model_version"],
        "celery_task_id": row["celery_task_id"],
        "started_at": row["started_at"].isoformat() if row["started_at"] else None,
        "finished_at": row["finished_at"].isoformat() if row["finished_at"] else None,
        "created_by": str(row["created_by"]),
        "created_by_name": row["created_by_name"],
        "created_at": row["created_at"].isoformat(),
        "updated_at": row["updated_at"].isoformat(),
    }


async def list_training_jobs(
    limit: int = 25, offset: int = 0, *, status: str | None = None, settings: Settings | None = None
) -> dict[str, Any]:
    settings = settings or get_settings()

    clauses: list[str] = []
    params: list[Any] = []
    if status:
        params.append(status)
        clauses.append(f"t.status = ${len(params)}::training_job_status_enum")

    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows_sql = (
        f"{ITEM_SQL_BASE} {where_sql} ORDER BY t.created_at DESC "
        f"LIMIT ${len(params) + 1} OFFSET ${len(params) + 2}"
    )
    count_sql = f"SELECT count(*) FROM training_jobs t {where_sql}"

    conn = await _connect(settings)
    try:
        rows = await conn.fetch(rows_sql, *params, limit, offset)
        total = await conn.fetchval(count_sql, *params)
    finally:
        await conn.close()

    return {"total": total, "items": [_row_to_item(row) for row in rows]}


async def get_training_job(job_id: str, settings: Settings | None = None) -> dict[str, Any] | None:
    settings = settings or get_settings()
    conn = await _connect(settings)
    try:
        row = await conn.fetchrow(f"{ITEM_SQL_BASE} WHERE t.id = $1", job_id)
    finally:
        await conn.close()
    return _row_to_item(row) if row else None


async def create_training_job(
    dataset_id: str,
    base_model: str,
    created_by: str,
    *,
    epochs: int | None = None,
    learning_rate: float | None = None,
    batch_size: int | None = None,
    validation_split: float | None = None,
    extra_config: dict[str, Any] | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Raises `ValueError` if the dataset doesn't exist or isn't `VALIDATED`
    (05_Training_Jobs §6: "hanya dataset VALIDATED yang boleh dipakai").
    """
    settings = settings or get_settings()

    conn = await _connect(settings)
    try:
        dataset = await conn.fetchrow("SELECT status::text AS status FROM datasets WHERE id = $1", dataset_id)
        if dataset is None:
            raise ValueError(f"dataset {dataset_id} does not exist")
        if dataset["status"] != "VALIDATED":
            raise ValueError(f"dataset must be VALIDATED, not {dataset['status']}")

        inserted = await conn.fetchrow(
            """
            INSERT INTO training_jobs
                (dataset_id, base_model, epochs, learning_rate, batch_size, validation_split, extra_config, created_by)
            VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8)
            RETURNING id
            """,
            dataset_id,
            base_model,
            epochs,
            learning_rate,
            batch_size,
            validation_split,
            json.dumps(extra_config or {}),
            created_by,
        )
        job_id = str(inserted["id"])

        task_id = await _dispatch(job_id, settings)
        await conn.execute("UPDATE training_jobs SET celery_task_id = $2 WHERE id = $1", job_id, task_id)

        row = await conn.fetchrow(f"{ITEM_SQL_BASE} WHERE t.id = $1", job_id)
    finally:
        await conn.close()

    return _row_to_item(row)


async def _dispatch(job_id: str, settings: Settings) -> str | None:
    """Enqueue the real Celery task. Sent by task name, never by importing the
    task function — the gateway must not pull worker/ML dependencies into the
    request path (same reasoning `services/queue.py` already documents).
    """
    from app.worker import TASK_RUN_TRAINING_JOB, celery_app

    try:
        result = await run_in_threadpool(
            celery_app.send_task,
            TASK_RUN_TRAINING_JOB,
            args=[job_id],
            queue=settings.celery_training_queue_name,
        )
        return result.id
    except Exception:  # noqa: BLE001
        logger.error("failed to dispatch training job", extra={"job_id": job_id}, exc_info=True)
        return None


async def apply_job_action(
    job_id: str, *, action: JobAction, settings: Settings | None = None
) -> dict[str, Any] | None:
    """`None` if the job doesn't exist. Raises `ValueError` if it isn't
    `QUEUED`/`RUNNING`. Best-effort revoke against the Celery task — a job
    that fails almost instantly (no live `/v1/train` to hang on) may finish
    before the revoke lands; the DB status transition is authoritative.
    """
    settings = settings or get_settings()

    conn = await _connect(settings)
    try:
        current = await conn.fetchrow(
            "SELECT status::text AS status, celery_task_id FROM training_jobs WHERE id = $1", job_id
        )
        if current is None:
            return None
        if current["status"] not in _CANCELLABLE_STATUSES:
            raise ValueError(f"cannot CANCEL a job in status {current['status']}")

        if current["celery_task_id"]:
            try:
                from app.worker import celery_app

                celery_app.control.revoke(current["celery_task_id"], terminate=True)
            except Exception:  # noqa: BLE001
                logger.warning("celery revoke failed", extra={"job_id": job_id}, exc_info=True)

        await conn.execute(
            """
            UPDATE training_jobs
            SET status = 'CANCELLED'::training_job_status_enum, finished_at = CURRENT_TIMESTAMP
            WHERE id = $1
            """,
            job_id,
        )
        row = await conn.fetchrow(f"{ITEM_SQL_BASE} WHERE t.id = $1", job_id)
    finally:
        await conn.close()

    return _row_to_item(row)


async def execute_training_job(job_id: str, settings: Settings | None = None) -> None:
    """Run from the Celery worker (`app.worker.tasks.run_training_job`).

    Marks RUNNING, calls the real (currently unimplemented) `/v1/train`, and
    persists whatever really happens — a genuine `MlServiceError` becomes a
    genuine FAILED row with the real error text, never a faked COMPLETED.
    """
    settings = settings or get_settings()
    conn = await _connect(settings)
    try:
        job = await conn.fetchrow(
            """
            SELECT t.dataset_id, d.name AS dataset_name, d.version AS dataset_version,
                   t.base_model, t.epochs, t.learning_rate, t.batch_size, t.validation_split, t.extra_config
            FROM training_jobs t JOIN datasets d ON d.id = t.dataset_id
            WHERE t.id = $1
            """,
            job_id,
        )
        if job is None:
            logger.error("training job vanished before execution", extra={"job_id": job_id})
            return

        await conn.execute(
            """
            UPDATE training_jobs
            SET status = 'RUNNING'::training_job_status_enum, started_at = CURRENT_TIMESTAMP
            WHERE id = $1
            """,
            job_id,
        )

        extra_config = job["extra_config"]
        if isinstance(extra_config, str):
            extra_config = json.loads(extra_config)

        # ml-service has no database of its own — ship the dataset's rows
        # inline rather than a reference it could look up itself.
        sample_rows = await conn.fetch(
            "SELECT text, label FROM dataset_samples WHERE dataset_id = $1", job["dataset_id"]
        )
        samples = [{"text": row["text"], "label": row["label"]} for row in sample_rows]

        try:
            response = await MlClient(settings).train(
                request_id=f"train-{job_id}",
                dataset_ref={
                    "id": str(job["dataset_id"]),
                    "name": job["dataset_name"],
                    "version": job["dataset_version"],
                    "samples": samples,
                },
                base_model=job["base_model"],
                config={
                    "epochs": job["epochs"],
                    "learning_rate": job["learning_rate"],
                    "batch_size": job["batch_size"],
                    "validation_split": job["validation_split"],
                    **(extra_config or {}),
                },
            )
        except MlServiceError as exc:
            await _mark_failed(conn, job_id, f"{exc.error_code}: {exc.message}", settings)
            return
        except Exception as exc:  # noqa: BLE001
            await _mark_failed(conn, job_id, str(exc), settings)
            return

        await conn.execute(
            """
            UPDATE training_jobs
            SET status = 'COMPLETED'::training_job_status_enum, finished_at = CURRENT_TIMESTAMP,
                metrics = $2::jsonb, generated_model_version = $3
            WHERE id = $1
            """,
            job_id,
            json.dumps(response.result or {}),
            response.model_version,
        )
    finally:
        await conn.close()


async def _mark_failed(conn: asyncpg.Connection, job_id: str, error_message: str, settings: Settings) -> None:
    await conn.execute(
        """
        UPDATE training_jobs
        SET status = 'FAILED'::training_job_status_enum, finished_at = CURRENT_TIMESTAMP, error_message = $2
        WHERE id = $1
        """,
        job_id,
        error_message,
    )
    logger.warning("training job failed", extra={"job_id": job_id, "error": error_message})
    await record_audit(
        actor_operator_id=None,
        action="training_job.failed",
        target_type="training_job",
        target_id=job_id,
        result="FAILED",
        metadata={"error_message": error_message},
        settings=settings,
    )
