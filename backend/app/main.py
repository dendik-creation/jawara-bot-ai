import logging

from fastapi import FastAPI

from app.api.v1.endpoints import health
from app.api.v1.router import api_router

logging.basicConfig(level=logging.INFO)


def create_app() -> FastAPI:
    app = FastAPI(title="JAWARA API Gateway")
    app.include_router(health.router)
    app.include_router(api_router)
    return app


app = create_app()
