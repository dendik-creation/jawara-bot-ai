"""Wire contract for the AI/ML Knowledge Base (04_AI_and_ML/03_Knowledge_Base.md).

`FactCategory`/`Verdict` mirror the DB's `category_enum`/`verdict_enum`
(`001_init_schema.sql`) — static, enumerable shapes, so validated here at
the schema level rather than in the service (unlike Detection Rules'/
Policies' `condition`, whose required shape depends on a runtime value).
"""

from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, field_validator

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
    # Omitted means the column default (0.80) — an unscored source sits just
    # below one an operator has explicitly vouched for.
    reliability_score: float | None = Field(default=None, ge=0.0, le=1.0)

    @field_validator("base_url")
    @classmethod
    def _base_url_must_have_a_hostname(cls, value: str) -> str:
        parsed = urlsplit(value if "://" in value else f"http://{value}")
        if parsed.scheme not in ("http", "https") or not parsed.hostname or "." not in parsed.hostname:
            raise ValueError("base_url harus berupa URL http(s) dengan domain yang valid")
        return value


class FactSourceUpdateRequest(BaseModel):
    """Trust settings an operator may change on an existing source.

    Both optional, at least one required — enforced in the service, which is
    where the same "an update must update something" rule already lives for
    fact items.
    """

    reliability_score: float | None = Field(default=None, ge=0.0, le=1.0)
    is_trusted: bool | None = None
    # Reliability is denormalised into Qdrant payloads at sync time, so a score
    # change only reaches retrieval once this source's facts are re-synced.
    # Default true: the surprising behaviour would be an edit that silently
    # does nothing to retrieval.
    resync: bool = True


class IngestionRunRequest(BaseModel):
    """Manual trigger for the scheduled fact-check ingestion.

    `source` is an adapter slug (`turnbackhoax`); omitted means every
    configured source. Validated against the registry in the route, not here
    — the set of known sources is a runtime fact, not a wire-level one.
    """

    source: str | None = None
