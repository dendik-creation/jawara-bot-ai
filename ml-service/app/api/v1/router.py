from fastapi import APIRouter

from app.api.v1.endpoints import health, inference, knowledge, ocr

# Version in the path from the first endpoint, not retrofitted later
# (02_Architecture/04_ML_Service.md §7).
api_router = APIRouter(prefix="/v1")
api_router.include_router(health.router, tags=["health"])
api_router.include_router(inference.router, tags=["inference"])
api_router.include_router(knowledge.router, tags=["knowledge"])
api_router.include_router(ocr.router, tags=["ocr"])
