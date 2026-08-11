from fastapi import APIRouter

from app.api.v1.endpoints import (
    ai_ml_overview,
    alerts,
    audit,
    auth,
    dashboard,
    datasets,
    detection_rules,
    feedback,
    incidents,
    knowledge,
    model_evaluations,
    model_versions,
    policies,
    threats,
    training_jobs,
    users,
    webhook,
)

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(webhook.router, tags=["webhook"])
api_router.include_router(auth.router, tags=["auth"])
api_router.include_router(dashboard.router, tags=["control-panel"])
api_router.include_router(audit.router, tags=["control-panel"])
api_router.include_router(threats.router, tags=["control-panel"])
api_router.include_router(alerts.router, tags=["control-panel"])
api_router.include_router(incidents.router, tags=["control-panel"])
api_router.include_router(users.router, tags=["control-panel"])
api_router.include_router(detection_rules.router, tags=["control-panel"])
api_router.include_router(policies.router, tags=["control-panel"])
api_router.include_router(knowledge.router, tags=["control-panel"])
api_router.include_router(ai_ml_overview.router, tags=["control-panel"])
api_router.include_router(feedback.router, tags=["control-panel"])
api_router.include_router(datasets.router, tags=["control-panel"])
api_router.include_router(training_jobs.router, tags=["control-panel"])
api_router.include_router(model_evaluations.router, tags=["control-panel"])
api_router.include_router(model_versions.router, tags=["control-panel"])
