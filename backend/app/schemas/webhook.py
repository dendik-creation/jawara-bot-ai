from typing import Any

from pydantic import BaseModel


class WahaMessagePayload(BaseModel):
    id: str | None = None
    from_: str | None = None
    to: str | None = None
    body: str | None = None
    fromMe: bool | None = None
    timestamp: int | None = None
    type: str | None = None

    model_config = {"populate_by_name": True, "extra": "allow"}


class WahaWebhookEvent(BaseModel):
    event: str
    session: str
    payload: dict[str, Any]
    engine: str | None = None


class SessionStatusEvent(BaseModel):
    event: str | None = None
    session: str
    payload: dict[str, Any]
