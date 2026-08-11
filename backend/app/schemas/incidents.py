"""Wire contract for Incident management (08_Dashboard/05_Incident_Management.md)."""

from typing import Literal

from pydantic import BaseModel, Field

IncidentSeverity = Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
IncidentActionValue = Literal["ASSIGN_TO_ME", "SET_STATE", "SET_SEVERITY", "CLOSE", "ESCALATE"]


class CreateIncidentRequest(BaseModel):
    title: str = Field(min_length=1)
    severity: IncidentSeverity
    message_log_ids: list[str] = Field(min_length=1)


class IncidentActionRequest(BaseModel):
    action: IncidentActionValue
    state: Literal["INVESTIGATING", "CONTAINED", "RESOLVED", "FALSE_POSITIVE"] | None = None
    severity: IncidentSeverity | None = None
    reason: str | None = None


class AddThreatRequest(BaseModel):
    message_log_id: str


class AddNoteRequest(BaseModel):
    note: str = Field(min_length=1)
