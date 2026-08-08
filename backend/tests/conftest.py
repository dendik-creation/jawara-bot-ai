import socket
from urllib.parse import urlparse

import pytest

from app.core.config import get_settings


def _reachable(host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


@pytest.fixture(scope="session")
def settings():
    return get_settings()


@pytest.fixture(scope="session")
def postgres_dsn(settings):
    """DSN of a live Postgres, or skip.

    Skips rather than fails when credentials are absent: the default DSN in
    `Settings` is a placeholder, so these tests only run where a real
    `DATABASE_URL` is exported (local hybrid dev, CI service container).
    """
    parsed = urlparse(settings.database_url)
    if not _reachable(parsed.hostname or "localhost", parsed.port or 5432):
        pytest.skip("postgres not reachable")

    import asyncio

    import asyncpg

    async def _probe() -> str | None:
        try:
            conn = await asyncpg.connect(settings.database_url, timeout=3)
        except Exception as exc:
            return str(exc)
        await conn.close()
        return None

    error = asyncio.run(_probe())
    if error:
        pytest.skip(f"postgres not usable with configured DATABASE_URL: {error}")
    return settings.database_url


@pytest.fixture(scope="session")
def redis_url(settings):
    parsed = urlparse(settings.redis_url)
    if not _reachable(parsed.hostname or "localhost", parsed.port or 6379):
        pytest.skip("redis not reachable")
    return settings.redis_url


@pytest.fixture(scope="session")
def qdrant_client(settings):
    if not _reachable(settings.qdrant_host, settings.qdrant_port):
        pytest.skip("qdrant not reachable")
    from app.vector.qdrant_setup import get_client

    return get_client(settings)
