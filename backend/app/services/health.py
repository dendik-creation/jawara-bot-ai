"""Dependency probes behind `GET /health` and the Service Health screen.

Basic availability only — "is this service answering right now". Long-run CPU /
RAM / disk trends are Infrastructure Analytics, which is **Deferred**
(05_Product_Scope_and_Roadmap §6) and must not creep in here
(08_Dashboard/08_Service_Health.md §2).

Every probe swallows its own exceptions: a health endpoint that can itself fail
is not a health endpoint.
"""

import asyncio

import asyncpg
import httpx
import redis.asyncio as redis

from app.clients.ml_client import MlClient
from app.clients.waha_client import WahaClient
from app.core.config import Settings

PROBE_TIMEOUT_SECONDS = 3.0


async def check_database(settings: Settings) -> bool:
    try:
        conn = await asyncpg.connect(settings.database_url, timeout=3)
        await conn.close()
        return True
    except Exception:
        return False


async def check_redis(settings: Settings) -> bool:
    client = redis.from_url(settings.redis_url, socket_connect_timeout=3)
    try:
        return await client.ping()
    except Exception:
        return False
    finally:
        await client.aclose()


async def check_qdrant(settings: Settings) -> bool:
    url = f"http://{settings.qdrant_host}:{settings.qdrant_port}/healthz"
    try:
        async with httpx.AsyncClient(timeout=PROBE_TIMEOUT_SECONDS) as client:
            response = await client.get(url)
        return response.status_code < 400
    except Exception:
        return False


async def check_waha(settings: Settings) -> bool:
    return await WahaClient(settings).is_reachable()


async def check_ml_service(settings: Settings) -> tuple[bool, dict[str, object]]:
    """Readiness, not liveness — a loaded-but-not-ready model is not HEALTHY."""
    if not settings.ml_enabled:
        return False, {"reason": "disabled_by_config"}
    return await MlClient(settings).ready()


async def service_health(settings: Settings) -> dict[str, object]:
    """Per-service status for the System → Service Health screen.

    Probes run concurrently: six sequential timeouts would make an unhealthy
    system take longer to report than a healthy one.
    """
    database, redis_ok, qdrant, waha, ml = await asyncio.gather(
        check_database(settings),
        check_redis(settings),
        check_qdrant(settings),
        check_waha(settings),
        check_ml_service(settings),
    )
    ml_ready, ml_detail = ml

    services = {
        "api_gateway": {"status": "HEALTHY", "detail": {}},
        "postgres": {"status": _status(database), "detail": {}},
        "redis": {"status": _status(redis_ok), "detail": {}},
        "qdrant": {"status": _status(qdrant), "detail": {}},
        "waha": {"status": _status(waha), "detail": {}},
        "ml_service": {"status": _status(ml_ready), "detail": ml_detail},
    }
    degraded = [name for name, service in services.items() if service["status"] != "HEALTHY"]

    return {
        "status": "ok" if not degraded else "degraded",
        "degraded": degraded,
        "services": services,
    }


def _status(reachable: bool) -> str:
    return "HEALTHY" if reachable else "DOWN"
