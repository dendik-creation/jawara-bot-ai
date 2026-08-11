"""Wire contract for Threat resolution actions (08_Dashboard/03_Threat_Monitoring.md §4)."""

from typing import Literal

from pydantic import BaseModel

ThreatActionValue = Literal["ALLOW", "WARN", "BLOCK", "ESCALATE", "CONFIRM", "FALSE_POSITIVE"]


class ThreatActionRequest(BaseModel):
    action: ThreatActionValue
    notes: str | None = None
