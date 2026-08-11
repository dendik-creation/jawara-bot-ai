"""Wire contract for Alert actions (09_Security/04_Alert_Center.md §2)."""

from typing import Literal

from pydantic import BaseModel

AlertActionValue = Literal["ACKNOWLEDGE", "RESOLVE", "ASSIGN_TO_ME"]


class AlertActionRequest(BaseModel):
    action: AlertActionValue
    reason: str | None = None
