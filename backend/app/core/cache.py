"""Tiny JSON cache over Redis, used for external threat-intel verdicts.

Fails open in both directions: a cache miss caused by Redis being down must not
turn into a pipeline error, and a write failure must not lose the verdict the
caller already computed. Same reasoning as the rate limiter — availability of a
convenience layer is never worth the availability of the pipeline.
"""

import json
import logging
from typing import Any

from redis.asyncio import Redis

logger = logging.getLogger("app.cache")


class JsonCache:
    def __init__(self, redis: Redis | None, prefix: str) -> None:
        self._redis = redis
        self._prefix = prefix

    def _key(self, key: str) -> str:
        return f"{self._prefix}:{key}"

    async def get(self, key: str) -> Any | None:
        if self._redis is None:
            return None
        try:
            raw = await self._redis.get(self._key(key))
        except Exception:
            logger.debug("cache read failed", extra={"key": key}, exc_info=True)
            return None
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except ValueError:
            return None

    async def set(self, key: str, value: Any, ttl_seconds: int) -> None:
        if self._redis is None:
            return
        try:
            await self._redis.set(self._key(key), json.dumps(value), ex=ttl_seconds)
        except Exception:
            logger.debug("cache write failed", extra={"key": key}, exc_info=True)
