"""`get_redis()` must rebuild across event loops, not just processes.

The Celery worker runs each task inside its own `asyncio.run()`
(app/worker/tasks.py) — a client's connection is bound to the loop it was
created on, so reusing a cached client from a prior, now-closed loop raised
"Future attached to a different loop" / "Event loop is closed" from inside
`message_log._publish_activity`. `aioredis.from_url()` never opens a real
connection at construction time, so this is testable without a live Redis.
"""

import asyncio

from app.core import redis_client


def teardown_function() -> None:
    # Every test starts from a clean slate — module-level cache, not a fixture.
    redis_client._client = None
    redis_client._client_loop = None


def test_same_loop_reuses_the_same_client():
    seen: list[int] = []

    async def run():
        seen.append(id(redis_client.get_redis()))
        seen.append(id(redis_client.get_redis()))

    asyncio.run(run())

    assert seen[0] == seen[1]


def test_a_new_loop_rebuilds_the_client_instead_of_reusing_a_dead_one():
    seen: list[int] = []

    async def run():
        seen.append(id(redis_client.get_redis()))

    asyncio.run(run())  # loop #1, then closes — this is what killed the old client
    asyncio.run(run())  # loop #2 must not reuse loop #1's client

    assert seen[0] != seen[1]
