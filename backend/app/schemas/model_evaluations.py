"""Wire contract for AI/ML Model Evaluation (04_AI_and_ML/06_Model_Evaluation.md)."""

from typing import Literal

from pydantic import BaseModel, Field

ModelEvaluationStatus = Literal["QUEUED", "RUNNING", "COMPLETED", "FAILED", "CANCELLED"]
ModelEvaluationActionValue = Literal["CANCEL"]


class ModelEvaluationCreateRequest(BaseModel):
    training_job_id: str = Field(min_length=1)
    dataset_id: str = Field(min_length=1)


class ModelEvaluationActionRequest(BaseModel):
    action: ModelEvaluationActionValue
