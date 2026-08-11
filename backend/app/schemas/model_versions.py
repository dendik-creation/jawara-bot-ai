"""Wire contract for AI/ML Model Registry & Deployment (04_AI_and_ML/07_Model_Registry_and_Deployment.md)."""

from typing import Literal

from pydantic import BaseModel

ModelVersionStatus = Literal["CANDIDATE", "VALIDATED", "PRODUCTION", "ARCHIVED"]
ModelVersionActionValue = Literal["VALIDATE", "PROMOTE", "ARCHIVE"]


class ModelVersionActionRequest(BaseModel):
    action: ModelVersionActionValue
