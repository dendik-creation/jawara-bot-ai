import uuid

import pytest
from redis.asyncio import Redis

from app.core.config import Settings
from app.core.rate_limit import KEY_PREFIX, check_rate_limit


class FakePipeline:
    def __init__(self, count: int, fail: bool = False):
        self._count = count
        self._fail = fail

    def zremrangebyscore(self, *_args, **_kwargs):
        return self

    def zadd(self, *_args, **_kwargs):
        return self

    def zcard(self, *_args, **_kwargs):
        return self

    def expire(self, *_args, **_kwargs):
        return self

    async def execute(self):
        if self._fail:
            raise ConnectionError("redis down")
        return [0, 1, self._count, True]


class FakeRedis:
    def __init__(self, count: int, fail: bool = False):
        self._count = count
        self._fail = fail

    def pipeline(self):
        return FakePipeline(self._count, self._fail)


@pytest.fixture
def limits() -> Settings:
    return Settings(rate_limit_max_requests=5, rate_limit_window_seconds=60)


async def test_allows_request_under_limit(limits):
    verdict = await check_rate_limit(FakeRedis(count=5), limits, "default:628@c.us")
    assert verdict.allowed is True
    assert verdict.current == 5


async def test_blocks_request_over_limit(limits):
    verdict = await check_rate_limit(FakeRedis(count=6), limits, "default:628@c.us")
    assert verdict.allowed is False
    assert verdict.retry_after == 60


async def test_fails_open_when_redis_unavailable(limits):
    verdict = await check_rate_limit(FakeRedis(count=99, fail=True), limits, "default:628@c.us")
    assert verdict.allowed is True


@pytest.mark.integration
async def test_sliding_window_against_live_redis(redis_url, limits):
    client = Redis.from_url(redis_url, decode_responses=True)
    scope = f"test:{uuid.uuid4().hex}"
    try:
        verdicts = [await check_rate_limit(client, limits, scope) for _ in range(7)]
        assert [v.allowed for v in verdicts] == [True] * 5 + [False, False]
        assert await client.ttl(f"{KEY_PREFIX}:{scope}") > 0
    finally:
        await client.delete(f"{KEY_PREFIX}:{scope}")
        await client.aclose()


@pytest.mark.integration
async def test_separate_scopes_do_not_share_budget(redis_url, limits):
    client = Redis.from_url(redis_url, decode_responses=True)
    scope_a = f"test:{uuid.uuid4().hex}"
    scope_b = f"test:{uuid.uuid4().hex}"
    try:
        for _ in range(6):
            await check_rate_limit(client, limits, scope_a)
        verdict = await check_rate_limit(client, limits, scope_b)
        assert verdict.allowed is True
    finally:
        await client.delete(f"{KEY_PREFIX}:{scope_a}", f"{KEY_PREFIX}:{scope_b}")
        await client.aclose()
