"""Maps pipeline `Category` (content topic) onto Control Panel threat categories
(attack vector), closing the open decision in [[01_PostgreSQL_Schema]] §0 /
[[Open_Decisions_Carried_Forward]] §2.4.

The two taxonomies answer different questions and were never going to line up
1:1: `Category` is *what the content is about* (a health claim, a financial
pitch), chosen so `fact_items` has something stable to key its knowledge base
on. `ThreatCategory` is *how the message attacks the reader* (impersonation,
urgency, a bad link) — the vocabulary a human operator triaging incidents
thinks in (08_Dashboard/03_Threat_Monitoring.md §2).

Extending `category_enum` to also carry attack-vector meaning was rejected:
it is schema- and test-locked to the intent router
(`tests/test_categories.py` parses `001_init_schema.sql` and fails on drift),
and conflating the two questions in one column would make every future
`Category` addition ambiguous about which axis it belongs to. This module is
the "keep two levels" option — a pure, one-way mapping with no schema change,
so it can be revised by editing a dict entry rather than a migration.

The mapping is necessarily lossy in both directions:

- `GENERAL_NEWS` and `HEALTH_HOAX` are content topics with no attack vector of
  their own (a false health claim is not phishing, impersonation, or a scam
  by itself) — both land on OTHER, the taxonomy's own catch-all
  ("Other Suspicious Activity").
- `SOCIAL_ENGINEERING`, `IMPERSONATION`, and `SPAM` have no `Category` that
  produces them today — nothing in the pipeline currently distinguishes
  "urgency-based manipulation" from any other text. They exist here so the
  Control Panel's filter dropdown is complete even though no message can
  reach them yet, and so adding the underlying signal later is a mapping
  change, not a new enum member.
"""

from enum import StrEnum

from app.pipeline.categories import Category


class ThreatCategory(StrEnum):
    """Control Panel taxonomy — 08_Dashboard/03_Threat_Monitoring.md §2."""

    PHISHING = "PHISHING"
    SCAM = "SCAM"
    SOCIAL_ENGINEERING = "SOCIAL_ENGINEERING"
    MALICIOUS_LINK = "MALICIOUS_LINK"
    IMPERSONATION = "IMPERSONATION"
    SPAM = "SPAM"
    OTHER = "OTHER"


_CATEGORY_TO_THREAT: dict[Category, ThreatCategory] = {
    Category.HEALTH_HOAX: ThreatCategory.OTHER,
    Category.FINANCIAL_FRAUD: ThreatCategory.SCAM,
    Category.GENERAL_NEWS: ThreatCategory.OTHER,
    Category.PHISHING_LINK: ThreatCategory.PHISHING,
    # A malicious APK is a delivered payload rather than social content, which
    # puts it closer to MALICIOUS_LINK (a bad technical artifact) than to any
    # of the purely social-engineering buckets.
    Category.FILE_APK: ThreatCategory.MALICIOUS_LINK,
}


def to_threat_category(category: Category | str | None) -> ThreatCategory:
    """`None` or an unclassified message maps to OTHER, never to a guess."""
    if category is None:
        return ThreatCategory.OTHER
    if not isinstance(category, Category):
        try:
            category = Category(category)
        except ValueError:
            return ThreatCategory.OTHER
    return _CATEGORY_TO_THREAT[category]
