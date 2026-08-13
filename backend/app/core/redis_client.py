import asyncio

import redis.asyncio as aioredis

from app.core.config import get_settings

_client: aioredis.Redis | None = None
# The loop `_client` was built on. The gateway (uvicorn) runs one loop for the
# whole process, so this never changes there — but the Celery worker runs
# each task inside its own `asyncio.run()` (app/worker/tasks.py), and a
# client's connection is bound to the loop it was created on. Reusing it
# after that loop closes raised "Future attached to a different loop" /
# "Event loop is closed" from inside `message_log._publish_activity` — caught
# there, so it never broke a reply, but it silently dropped that message from
# the Live Activity feed.
_client_loop: asyncio.AbstractEventLoop | None = None


def get_redis() -> aioredis.Redis:
    """Process-wide async Redis client, rebuilt whenever the running loop
    has changed since it was created.

    The stale client is not explicitly closed on rebuild — its loop is
    already gone by the time a new one is needed, so there is nothing left
    that could close it cleanly; it is simply dropped for GC. One connection
    pool per loop, not per request/task — creating a client per webhook
    would burn the <200ms budget on a fresh handshake.
    """
    global _client, _client_loop
    current_loop = asyncio.get_running_loop()
    if _client is None or _client_loop is not current_loop:
        settings = get_settings()
        _client = aioredis.from_url(
            settings.redis_url,
            socket_connect_timeout=2,
            socket_timeout=2,
            decode_responses=True,
        )
        _client_loop = current_loop
    return _client


async def close_redis() -> None:
    global _client, _client_loop
    if _client is not None:
        await _client.aclose()
        _client = None
        _client_loop = None
