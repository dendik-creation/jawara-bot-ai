from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


class MessageJob(BaseModel):
    """Envelope pushed to Redis by the gateway and consumed by the Celery worker.

    `event` holds the WAHA payload verbatim so the worker never depends on the
    gateway having understood the message — the gateway only extracts routing
    fields and forwards the rest untouched.
    """

    waha_message_id: str | None = None
    session: str
    event_name: str
    chat_id: str | None = None
    received_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    event: dict[str, Any]
