"""Category -> ThreatCategory mapping ([[Open_Decisions_Carried_Forward]] §2.4)."""

import pytest

from app.pipeline.categories import Category
from app.pipeline.threat_categories import ThreatCategory, to_threat_category


def test_every_category_has_a_mapping():
    """A `Category` added without a mapping entry must fail loudly, not KeyError
    at request time months later."""
    for category in Category:
        assert to_threat_category(category) in ThreatCategory


@pytest.mark.parametrize(
    ("category", "expected"),
    [
        (Category.HEALTH_HOAX, ThreatCategory.OTHER),
        (Category.FINANCIAL_FRAUD, ThreatCategory.SCAM),
        (Category.GENERAL_NEWS, ThreatCategory.OTHER),
        (Category.PHISHING_LINK, ThreatCategory.PHISHING),
        (Category.FILE_APK, ThreatCategory.MALICIOUS_LINK),
    ],
)
def test_known_mappings(category: Category, expected: ThreatCategory):
    assert to_threat_category(category) == expected


def test_accepts_the_string_form_too():
    """`detected_intent` comes back from asyncpg as `str`, not `Category`."""
    assert to_threat_category("FINANCIAL_FRAUD") == ThreatCategory.SCAM


def test_unclassified_message_is_other_not_a_crash():
    assert to_threat_category(None) == ThreatCategory.OTHER
    assert to_threat_category("UNCLASSIFIED") == ThreatCategory.OTHER
    assert to_threat_category("not-a-real-category") == ThreatCategory.OTHER
