import socket

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
def live_qdrant(settings):
    """Skip rather than fail when no Qdrant is running (same policy as the gateway suite)."""
    if not _reachable(settings.qdrant_host, settings.qdrant_port):
        pytest.skip("qdrant not reachable")
    return settings
