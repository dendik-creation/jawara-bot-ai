"""Wire contract for AI/ML Training Jobs (04_AI_and_ML/05_Training_Jobs.md)."""

from typing import Any, Literal

from pydantic import BaseModel, Field

TrainingJobStatus = Literal["QUEUED", "RUNNING", "EVALUATING", "COMPLETED", "FAILED", "CANCELLED"]
TrainingJobActionValue = Literal["CANCEL"]


class TrainingJobCreateRequest(BaseModel):
    dataset_id: str
    base_model: str = Field(min_length=1)
    epochs: int | None = None
    learning_rate: float | None = None
    batch_size: int | None = None
    validation_split: float | None = None
    extra_config: dict[str, Any] | None = None


class TrainingJobActionRequest(BaseModel):
    action: TrainingJobActionValue
