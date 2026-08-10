"""Webhook event de-duplication.

WAHA fires both `message` and `message.any` for the same inbound message (see
`WHATSAPP_HOOK_EVENTS`), and retries an event on a non-2xx response. Both cases
enqueue a duplicate `waha_message_id`, and running the pipeline twice for one
message means two concurrent `send_text` calls to the same chat — WAHA's
WEBJS engine serialises sends per session, so the second call queues behind
the first and trips the client timeout, surfacing as a false
`dispatch_failed:timeout` rather than the real duplicate-delivery bug.

Fails open: if Redis is unreachable, the event is treated as new. Dropping a
real message because the dedup check failed is worse than occasionally
double-processing one.
"""

import logging

from redis.asyncio import Redis

logger = logging.getLogger("app.dedup")

KEY_PREFIX = "dedup:webhook"
DEFAULT_TTL_SECONDS = 600


async def is_duplicate(redis: Redis, waha_message_id: str, *, ttl: int = DEFAULT_TTL_SECONDS) -> bool:
    """True if this `waha_message_id` was already seen within the TTL window."""
    key = f"{KEY_PREFIX}:{waha_message_id}"
    try:
        was_set = await redis.set(key, "1", nx=True, ex=ttl)
    except Exception:
        logger.warning("dedup check failed, allowing event", extra={"waha_message_id": waha_message_id}, exc_info=True)
        return False
    return not was_set
