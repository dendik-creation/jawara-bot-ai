"""Wire contract for AI/ML Datasets (04_AI_and_ML/04_Datasets_and_Operator_Feedback.md).

`label` on a sample is a plain string, not a Pydantic `Literal` — the valid
set (`app.services.datasets.VALID_LABELS`) includes the synthetic
`NOT_A_THREAT` negative class alongside `category_enum`'s values, checked in
the service layer (same reasoning `dataset_samples.label` is TEXT, not a DB
enum, in the migration).
"""

from typing import Literal

from pydantic import BaseModel, Field

DatasetSource = Literal["CURATED", "OPERATOR_FEEDBACK", "IMPORTED", "APPROVED_INTERNAL"]
DatasetStatus = Literal["DRAFT", "VALIDATING", "VALIDATED", "REJECTED", "ARCHIVED"]
DatasetActionValue = Literal["UPDATE", "VALIDATE", "ARCHIVE"]


class DatasetCreateRequest(BaseModel):
    name: str = Field(min_length=1)
    version: int = 1
    source: DatasetSource
    description: str | None = None


class DatasetActionRequest(BaseModel):
    action: DatasetActionValue
    # Only used by UPDATE.
    name: str | None = None
    description: str | None = None


class DatasetSampleCreateRequest(BaseModel):
    text: str = Field(min_length=1)
    label: str = Field(min_length=1)
    source_message_log_id: str | None = None
    source_feedback_id: str | None = None


class PromoteFeedbackRequest(BaseModel):
    feedback_type: Literal["CONFIRM", "FALSE_POSITIVE"] | None = None
    limit: int = Field(default=100, ge=1, le=1000)
