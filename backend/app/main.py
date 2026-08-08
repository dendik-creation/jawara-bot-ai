from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.v1.endpoints import health
from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.core.redis_client import close_redis


@asynccontextmanager
async def lifespan(_: FastAPI):
    configure_logging(get_settings().log_level)
    yield
    await close_redis()


def create_app() -> FastAPI:
    app = FastAPI(title="JAWARA API Gateway", lifespan=lifespan)
    app.include_router(health.router)
    app.include_router(api_router)
    return app


app = create_app()
