import logging
import time
import uuid
from dataclasses import dataclass

from redis.asyncio import Redis

from app.core.config import Settings

logger = logging.getLogger("app.rate_limit")

KEY_PREFIX = "ratelimit:webhook"


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    current: int
    limit: int
    retry_after: int


async def check_rate_limit(redis: Redis, settings: Settings, scope: str) -> RateLimitResult:
    """Sliding-window rate limit backed by a Redis sorted set.

    Members are scored by request timestamp; entries older than the window are
    trimmed on every call, so the count is a true rolling window rather than a
    fixed bucket that resets on a clock boundary (which would let a caller send
    2x the limit across a boundary).

    Fails open: if Redis is unreachable the request is allowed and the failure is
    logged. A rate limiter outage must not take webhook ingestion down with it —
    dropping real user messages is worse than briefly not throttling.
    """
    limit = settings.rate_limit_max_requests
    window = settings.rate_limit_window_seconds
    key = f"{KEY_PREFIX}:{scope}"
    now = time.time()

    try:
        pipe = redis.pipeline()
        pipe.zremrangebyscore(key, 0, now - window)
        pipe.zadd(key, {f"{now}:{uuid.uuid4().hex}": now})
        pipe.zcard(key)
        pipe.expire(key, window)
        _, _, count, _ = await pipe.execute()
    except Exception:
        logger.warning("rate limit check failed, allowing request", extra={"scope": scope}, exc_info=True)
        return RateLimitResult(allowed=True, current=0, limit=limit, retry_after=0)

    return RateLimitResult(
        allowed=count <= limit,
        current=int(count),
        limit=limit,
        retry_after=window,
    )
