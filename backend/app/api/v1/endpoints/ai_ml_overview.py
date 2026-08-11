"""AI/ML Overview aggregation API (04_AI_and_ML/02_ML_Control_Center_Overview.md)."""

import logging

from fastapi import APIRouter, Depends

from app.core.security import require_operator
from app.services import ai_ml_overview

logger = logging.getLogger("app.api.ai_ml_overview")

router = APIRouter(dependencies=[Depends(require_operator)])


@router.get("/ai-ml/overview")
async def get_ai_ml_overview() -> dict[str, object]:
    try:
        return await ai_ml_overview.get_overview()
    except Exception:  # noqa: BLE001
        logger.error("ai/ml overview aggregation failed", exc_info=True)
        return {
            "knowledge_base": {"available": False, "reason": "database_unavailable"},
            "detection_rules": {"available": False, "reason": "database_unavailable"},
            "policies": {"available": False, "reason": "database_unavailable"},
            "datasets": {"available": False, "reason": "database_unavailable"},
            "feedback": {"available": False, "reason": "database_unavailable"},
            "ml_service": {"available": False, "reason": "ml_service_unreachable"},
            "training_jobs": {"available": False, "reason": "database_unavailable"},
            "model_registry": {"available": False, "reason": "database_unavailable"},
            "evaluation": {"available": False, "reason": "database_unavailable"},
        }
