"""Wire contract shared by every `/v1` endpoint.

    request   { request_id, payload, metadata }
    response  { request_id, result, confidence, model_version, latency_ms }

`request_id` is the gateway's correlation ID (the WAHA message id), echoed back
so one message can be traced across every hop. `model_version` is required on
every inference response — see 02_Architecture/04_ML_Service.md §7.
"""

from typing import Any

from pydantic import BaseModel, Field


class MlRequest(BaseModel):
    request_id: str = Field(min_length=1, max_length=200)
    payload: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class MlResponse(BaseModel):
    request_id: str
    result: dict[str, Any]
    model_version: str
    confidence: float | None = None
    latency_ms: int | None = None
