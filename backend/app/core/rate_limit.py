import logging
import time
import uuid
from dataclasses import dataclass

from redis.asyncio import Redis

from app.core.config import Settings

logger = logging.getLogger("app.rate_limit")

KEY_PREFIX = "ratelimit:webhook"
LOGIN_KEY_PREFIX = "ratelimit:login"


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    current: int
    limit: int
    retry_after: int


async def check_rate_limit(
    redis: Redis,
    settings: Settings,
    scope: str,
    *,
    limit: int | None = None,
    window: int | None = None,
    prefix: str = KEY_PREFIX,
) -> RateLimitResult:
    """Sliding-window rate limit backed by a Redis sorted set.

    Members are scored by request timestamp; entries older than the window are
    trimmed on every call, so the count is a true rolling window rather than a
    fixed bucket that resets on a clock boundary (which would let a caller send
    2x the limit across a boundary).

    `limit`/`window`/`prefix` default to the webhook budget. The login endpoint
    passes its own — far stricter, and in a separate keyspace so a chatty
    WhatsApp session can never consume an operator's login attempts.

    Fails open: if Redis is unreachable the request is allowed and the failure is
    logged. A rate limiter outage must not take webhook ingestion down with it —
    dropping real user messages is worse than briefly not throttling. The same
    applies to login: brute force is still bounded by bcrypt, while a locked-out
    operator during a Redis outage would be an outage of the security dashboard
    itself.
    """
    limit = limit if limit is not None else settings.rate_limit_max_requests
    window = window if window is not None else settings.rate_limit_window_seconds
    key = f"{prefix}:{scope}"
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
