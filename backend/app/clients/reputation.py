"""Shared shape for URL-reputation providers (Safe Browsing, VirusTotal).

Every provider answers the same question — "how dangerous is this URL" — and
every provider is allowed to answer "I don't know". `UNKNOWN` is a first-class
verdict, not an error: 02_Architecture/05_Integrations.md §4 requires that a
failing or throttled third party never blocks detection.
"""

from dataclasses import dataclass, field
from typing import Any

from app.pipeline.categories import RiskLevel


@dataclass(frozen=True)
class ProviderVerdict:
    """One provider's opinion about one URL."""

    provider: str
    url: str
    risk: RiskLevel
    available: bool = True
    cached: bool = False
    reason: str = ""
    details: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def unavailable(cls, provider: str, url: str, reason: str) -> "ProviderVerdict":
        """Provider could not be consulted — no key, timeout, quota, outage."""
        return cls(provider=provider, url=url, risk=RiskLevel.UNKNOWN, available=False, reason=reason)

    def as_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "url": self.url,
            "risk": self.risk.value,
            "available": self.available,
            "cached": self.cached,
            "reason": self.reason,
        }
