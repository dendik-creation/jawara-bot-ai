from fastapi import APIRouter, Response, status

from app.core.config import get_settings
from app.services.health import check_database, check_redis

router = APIRouter()


@router.get("/health")
async def health(response: Response) -> dict[str, object]:
    settings = get_settings()
    db_ok = await check_database(settings)
    redis_ok = await check_redis(settings)
    healthy = db_ok and redis_ok

    if not healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return {
        "status": "ok" if healthy else "degraded",
        "dependencies": {"database": db_ok, "redis": redis_ok},
    }
