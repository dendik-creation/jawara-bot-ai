from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.errors import MlError, ml_error_handler, unhandled_error_handler
from app.core.logging import configure_logging
from app.models.registry import registry
from app.rag.qdrant_repo import QdrantRepository


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level)
    # Models load once per process at startup, never per request — that cost is
    # the whole reason this service is separate from the gateway.
    registry.load(settings)
    app.state.qdrant = QdrantRepository(settings)
    yield
    await app.state.qdrant.close()


def create_app() -> FastAPI:
    app = FastAPI(title="JAWARA ML Service", lifespan=lifespan)
    app.add_exception_handler(MlError, ml_error_handler)
    app.add_exception_handler(Exception, unhandled_error_handler)
    app.include_router(api_router)
    return app


app = create_app()
