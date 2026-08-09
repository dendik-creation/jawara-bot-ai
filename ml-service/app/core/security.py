from fastapi import Header

from app.core.config import get_settings
from app.core.errors import MlError


async def verify_internal_key(x_internal_api_key: str | None = Header(default=None)) -> None:
    """Service-to-service auth.

    ML Service is reachable only on the internal Docker network, but network
    placement is not authentication: a compromised container inside the network
    would otherwise have free access to inference and to the knowledge base.
    """
    settings = get_settings()
    if not x_internal_api_key or x_internal_api_key != settings.ml_service_api_key:
        raise MlError(
            "unauthorized",
            "Invalid or missing X-Internal-Api-Key",
            status_code=401,
            retryable=False,
        )
