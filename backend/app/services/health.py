import asyncpg
import redis.asyncio as redis

from app.core.config import Settings


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
