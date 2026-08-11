"""Wire contract for Detection Rules (09_Security/03_Detection_Rules.md).

`condition`'s required shape depends on `rule_type` (a runtime value), so
its structural validation lives in `app.services.detection_rules._validate_condition`
— the service raises `ValueError`, the route maps it to 400 — rather than
here. This schema only checks what's true regardless of `rule_type`.
"""

from typing import Any, Literal

from pydantic import BaseModel, Field

DetectionRuleType = Literal[
    "KEYWORD",
    "DOMAIN",
    "URL",
    "RISK_THRESHOLD",
    "PATTERN",
    "REPEATED_OFFENDER",
    "RATE_LIMIT",
    "ALLOWLIST",
    "BLOCKLIST",
]
DetectionRuleSeverity = Literal["HIGH", "MEDIUM", "LOW"]
DetectionRuleStatus = Literal["DRAFT", "ACTIVE", "DISABLED", "ARCHIVED"]
DetectionRuleActionValue = Literal["UPDATE", "ACTIVATE", "DISABLE", "ARCHIVE"]


class DetectionRuleCreateRequest(BaseModel):
    name: str = Field(min_length=1)
    rule_type: DetectionRuleType
    condition: dict[str, Any]
    severity: DetectionRuleSeverity


class DetectionRuleActionRequest(BaseModel):
    action: DetectionRuleActionValue
    # Only used by UPDATE; rule_type is immutable and not accepted here.
    name: str | None = None
    condition: dict[str, Any] | None = None
    severity: DetectionRuleSeverity | None = None
