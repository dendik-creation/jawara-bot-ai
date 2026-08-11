"""AI/ML Overview aggregation (04_AI_and_ML/02_ML_Control_Center_Overview.md).

§2's 9 spec'd content blocks all depended on Models/Training Jobs/Evaluation
(Stages 10-13 of the rollout), which didn't exist yet when this module was
first written. As of Stage 13 every block is backed by a real data source
(Knowledge Base, Detection Rules, Policies, Datasets, Feedback, ML Service
readiness, Training Jobs, Evaluation, Model Registry) — same "never invent
a number" discipline `services/dashboard.py` already follows, now applied
to genuinely-populated tables instead of stubs.

Each block is independently try/excepted (mirrors `dashboard.py`'s
`/dashboard/recent` pattern) so one DB hiccup or a down ML Service doesn't
blank the whole page.
"""

import logging
from typing import Any

import asyncpg

from app.clients.ml_client import MlClient
from app.core.config import Settings, get_settings

logger = logging.getLogger("app.services.ai_ml_overview")


async def _connect(settings: Settings) -> asyncpg.Connection:
    return await asyncpg.connect(settings.database_url, timeout=5)


async def _knowledge_base_stats(settings: Settings) -> dict[str, Any]:
    try:
        conn = await _connect(settings)
        try:
            facts = await conn.fetchrow(
                """
                SELECT
                    count(*) AS total,
                    count(*) FILTER (WHERE is_active) AS active,
                    count(*) FILTER (WHERE synced_at IS NOT NULL AND sync_error IS NULL) AS synced,
                    count(*) FILTER (WHERE synced_at IS NULL) AS never_synced,
                    count(*) FILTER (WHERE sync_error IS NOT NULL) AS sync_failed
                FROM fact_items
                """
            )
            sources_total = await conn.fetchval("SELECT count(*) FROM fact_sources")
        finally:
            await conn.close()
    except Exception:  # noqa: BLE001
        logger.error("knowledge base overview query failed", exc_info=True)
        return {"available": False, "reason": "database_unavailable"}

    return {
        "available": True,
        "total_facts": facts["total"],
        "active_facts": facts["active"],
        "synced": facts["synced"],
        "never_synced": facts["never_synced"],
        "sync_failed": facts["sync_failed"],
        "total_sources": sources_total,
    }


async def _status_breakdown(table: str, settings: Settings) -> dict[str, Any]:
    try:
        conn = await _connect(settings)
        try:
            rows = await conn.fetch(f"SELECT status::text AS status, count(*) AS count FROM {table} GROUP BY status")
            total = await conn.fetchval(f"SELECT count(*) FROM {table}")
        finally:
            await conn.close()
    except Exception:  # noqa: BLE001
        logger.error("%s overview query failed", table, exc_info=True)
        return {"available": False, "reason": "database_unavailable"}

    return {
        "available": True,
        "total": total,
        "by_status": {row["status"]: row["count"] for row in rows},
    }


async def _ml_service_status(settings: Settings) -> dict[str, Any]:
    try:
        ready, body = await MlClient(settings).ready()
    except Exception:  # noqa: BLE001
        logger.error("ml service overview check failed", exc_info=True)
        return {"available": False, "reason": "ml_service_unreachable"}

    models = body.get("models") or {}
    vector_store = body.get("vector_store") or {}

    return {
        "available": True,
        "status": body.get("status", "not_ready" if not ready else "ready"),
        "embedder": models.get("embedder"),
        "llm": models.get("llm"),
        "degraded_reasons": models.get("degraded_reasons") or [],
        "vector_store": (
            {
                "available": True,
                "collection": vector_store.get("collection"),
                "points_count": vector_store.get("points_count"),
                "vector_size": vector_store.get("vector_size"),
                "distance": vector_store.get("distance"),
            }
            if "points_count" in vector_store
            else {"available": False, "reason": "vector_store_unreachable"}
        ),
    }


async def _feedback_stats(settings: Settings) -> dict[str, Any]:
    try:
        conn = await _connect(settings)
        try:
            rows = await conn.fetch(
                "SELECT feedback_type::text AS feedback_type, count(*) AS count FROM operator_feedback GROUP BY feedback_type"
            )
            total = await conn.fetchval("SELECT count(*) FROM operator_feedback")
        finally:
            await conn.close()
    except Exception:  # noqa: BLE001
        logger.error("feedback overview query failed", exc_info=True)
        return {"available": False, "reason": "database_unavailable"}

    return {
        "available": True,
        "total": total,
        "by_type": {row["feedback_type"]: row["count"] for row in rows},
    }


async def get_overview(settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()

    return {
        "knowledge_base": await _knowledge_base_stats(settings),
        "detection_rules": await _status_breakdown("detection_rules", settings),
        "policies": await _status_breakdown("policies", settings),
        "datasets": await _status_breakdown("datasets", settings),
        "feedback": await _feedback_stats(settings),
        "ml_service": await _ml_service_status(settings),
        "training_jobs": await _status_breakdown("training_jobs", settings),
        "model_registry": await _status_breakdown("model_versions", settings),
        "evaluation": await _status_breakdown("model_evaluations", settings),
    }
