from fastapi import APIRouter

from app.api.v1.endpoints import auth, dashboard, webhook

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(webhook.router, tags=["webhook"])
api_router.include_router(auth.router, tags=["auth"])
api_router.include_router(dashboard.router, tags=["control-panel"])
