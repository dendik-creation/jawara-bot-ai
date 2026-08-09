"""Pipeline enums mirroring the PostgreSQL types in migration 001.

These are the *only* place in the gateway that spells out the enum members, and
`tests/test_categories.py` parses `001_init_schema.sql` to prove the two stay in
step. Acceptance criterion of [[Build Intent Router]]: "Category output values
match `category_enum` exactly (no drift between code and schema)".
"""

from enum import StrEnum


class Category(StrEnum):
    """`category_enum` — first-generation pipeline intents."""

    HEALTH_HOAX = "HEALTH_HOAX"
    FINANCIAL_FRAUD = "FINANCIAL_FRAUD"
    GENERAL_NEWS = "GENERAL_NEWS"
    PHISHING_LINK = "PHISHING_LINK"
    FILE_APK = "FILE_APK"


class Verdict(StrEnum):
    """`verdict_enum` — knowledge-base fact verdicts."""

    HOAX = "HOAX"
    FACT = "FACT"
    MISLEADING = "MISLEADING"
    UNVERIFIED = "UNVERIFIED"


class RiskLevel(StrEnum):
    """`risk_level_enum` — risk assessment output."""

    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    UNKNOWN = "UNKNOWN"


class InputType(StrEnum):
    """`input_type_enum` — how the analysed content reached us."""

    TEXT = "TEXT"
    IMAGE_OCR = "IMAGE_OCR"
    URL_LINK = "URL_LINK"
    FILE_APK = "FILE_APK"
    BANK_ACCOUNT = "BANK_ACCOUNT"


# Ordered worst-first; used when several signals disagree and the pipeline has to
# collapse them into one `risk_score`. UNKNOWN is deliberately not the lowest:
# "we could not check" must never outrank "we checked and it was clean", but it
# must also never be silently reported as LOW.
_SEVERITY = {
    RiskLevel.HIGH: 3,
    RiskLevel.MEDIUM: 2,
    RiskLevel.UNKNOWN: 1,
    RiskLevel.LOW: 0,
}


def worst_risk(*levels: RiskLevel) -> RiskLevel:
    """Highest-severity level among the arguments (`UNKNOWN` when none given)."""
    if not levels:
        return RiskLevel.UNKNOWN
    return max(levels, key=lambda level: _SEVERITY[level])
