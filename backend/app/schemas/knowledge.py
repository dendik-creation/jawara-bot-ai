"""Wire contract for the AI/ML Knowledge Base (04_AI_and_ML/03_Knowledge_Base.md).

`FactCategory`/`Verdict` mirror the DB's `category_enum`/`verdict_enum`
(`001_init_schema.sql`) — static, enumerable shapes, so validated here at
the schema level rather than in the service (unlike Detection Rules'/
Policies' `condition`, whose required shape depends on a runtime value).
"""

from typing import Literal

from pydantic import BaseModel, Field

FactCategory = Literal["HEALTH_HOAX", "FINANCIAL_FRAUD", "GENERAL_NEWS", "PHISHING_LINK", "FILE_APK"]
Verdict = Literal["HOAX", "FACT", "MISLEADING", "UNVERIFIED"]
FactItemActionValue = Literal["UPDATE", "ACTIVATE", "DEACTIVATE"]


class FactItemCreateRequest(BaseModel):
    source_id: int
    category: FactCategory
    title: str = Field(min_length=1)
    claim_summary: str = Field(min_length=1)
    fact_explanation: str = Field(min_length=1)
    verdict: Verdict
    source_url: str = Field(min_length=1)


class FactItemActionRequest(BaseModel):
    action: FactItemActionValue
    # Only used by UPDATE.
    category: FactCategory | None = None
    title: str | None = None
    claim_summary: str | None = None
    fact_explanation: str | None = None
    verdict: Verdict | None = None
    source_url: str | None = None


class FactSourceCreateRequest(BaseModel):
    name: str = Field(min_length=1)
    base_url: str = Field(min_length=1)
    is_trusted: bool = True
