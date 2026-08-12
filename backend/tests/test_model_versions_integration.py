"""`get_production_model` against a live PostgreSQL.

`app.services.model_versions.get_production_model` is what the pipeline
(`app.pipeline.orchestrator`) calls to learn which classifier artifact to
trust — a plain read, but one that joins across `model_versions`,
`training_jobs`, and depends on `training_jobs.metrics->>'artifact_sha256'`
being present. Worth proving against real SQL, not just a mock.

Each function under test opens its own connection (`_connect(settings)`), so
a rollback-on-exit transaction in the fixture would be invisible to it —
real commits + explicit FK-order cleanup, same pattern as
`test_auth_integration.py`.
"""

import json
import uuid

import asyncpg
import pytest

from app.core.config import Settings, get_settings
from app.db.migrate import apply_migrations
from app.services.model_versions import get_production_model

pytestmark = pytest.mark.integration


def _cheap_settings(dsn: str) -> Settings:
    return get_settings().model_copy(update={"database_url": dsn})


@pytest.fixture
async def store(postgres_dsn):
    await apply_migrations(postgres_dsn)
    settings = _cheap_settings(postgres_dsn)
    created: dict[str, list[str]] = {"model_versions": [], "model_evaluations": [], "training_jobs": [], "datasets": [], "operators": []}

    yield settings, created

    conn = await asyncpg.connect(postgres_dsn)
    try:
        # Children before parents — FK order.
        await conn.execute("DELETE FROM model_versions WHERE id = ANY($1::uuid[])", created["model_versions"])
        await conn.execute("DELETE FROM model_evaluations WHERE id = ANY($1::uuid[])", created["model_evaluations"])
        await conn.execute("DELETE FROM training_jobs WHERE id = ANY($1::uuid[])", created["training_jobs"])
        await conn.execute("DELETE FROM datasets WHERE id = ANY($1::uuid[])", created["datasets"])
        await conn.execute("DELETE FROM operators WHERE id = ANY($1::uuid[])", created["operators"])
    finally:
        await conn.close()


async def _seed_model_version(
    store, *, status: str, artifact_sha256: str | None, generated_model_version: str | None = "clf-test-abc123"
) -> None:
    settings, created = store
    conn = await asyncpg.connect(settings.database_url)
    try:
        operator_id = await conn.fetchval(
            "INSERT INTO operators (email, full_name, password_hash) VALUES ($1, 'Pytest', 'x') RETURNING id",
            f"pytest-mv-{uuid.uuid4().hex[:12]}@example.test",
        )
        created["operators"].append(operator_id)

        dataset_id = await conn.fetchval(
            """
            INSERT INTO datasets (name, version, source, status, created_by)
            VALUES ($1, 1, 'CURATED'::dataset_source_enum, 'VALIDATED'::dataset_status_enum, $2)
            RETURNING id
            """,
            f"pytest-ds-{uuid.uuid4().hex[:12]}",
            operator_id,
        )
        created["datasets"].append(dataset_id)

        metrics = json.dumps({"artifact_sha256": artifact_sha256} if artifact_sha256 else {})
        training_job_id = await conn.fetchval(
            """
            INSERT INTO training_jobs (dataset_id, base_model, status, metrics, generated_model_version, created_by)
            VALUES ($1, 'tfidf-logreg', 'COMPLETED'::training_job_status_enum, $2::jsonb, $3, $4)
            RETURNING id
            """,
            dataset_id,
            metrics,
            generated_model_version,
            operator_id,
        )
        created["training_jobs"].append(training_job_id)

        evaluation_id = await conn.fetchval(
            """
            INSERT INTO model_evaluations (training_job_id, dataset_id, status, created_by)
            VALUES ($1, $2, 'COMPLETED'::model_evaluation_status_enum, $3)
            RETURNING id
            """,
            training_job_id,
            dataset_id,
            operator_id,
        )
        created["model_evaluations"].append(evaluation_id)

        model_version_id = await conn.fetchval(
            """
            INSERT INTO model_versions (training_job_id, model_evaluation_id, status)
            VALUES ($1, $2, $3::model_version_status_enum)
            RETURNING id
            """,
            training_job_id,
            evaluation_id,
            status,
        )
        created["model_versions"].append(model_version_id)
    finally:
        await conn.close()


async def test_no_production_model_returns_none(store):
    settings, _ = store
    await _seed_model_version(store, status="CANDIDATE", artifact_sha256="deadbeef")

    assert await get_production_model(settings) is None


async def test_production_model_returns_version_and_checksum(store):
    settings, _ = store
    await _seed_model_version(store, status="PRODUCTION", artifact_sha256="cafef00d")

    result = await get_production_model(settings)

    assert result == {"model_version": "clf-test-abc123", "artifact_sha256": "cafef00d"}


async def test_production_model_without_a_recorded_checksum_is_treated_as_absent(store):
    """A PRODUCTION row whose training job never recorded `artifact_sha256`
    (shouldn't happen, but must not be trusted if it does) is the same as no
    production model — the pipeline has nothing safe to verify against.
    """
    settings, _ = store
    await _seed_model_version(store, status="PRODUCTION", artifact_sha256=None)

    assert await get_production_model(settings) is None
