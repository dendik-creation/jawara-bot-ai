"""Combined URL risk from Safe Browsing + VirusTotal ([[Integrate VirusTotal]]).

Two providers, one verdict. The combination rule is deliberately asymmetric:

- **Worst wins.** A link flagged by only one provider still surfaces as high
  risk. Coverage between the two barely overlaps — Safe Browsing knows freshly
  reported phishing, VirusTotal knows what its engines have crawled — so
  requiring agreement would mean discarding most true positives.
- **Unknown never lowers risk.** A provider that timed out, ran out of quota, or
  has no key contributes nothing; it cannot pull a HIGH down to LOW.
- **A shortlink nobody could resolve is MEDIUM, not LOW.** The visible domain
  (`bit.ly`) is not the domain the user will land on, so "no provider flagged
  it" says nothing about the destination.

Providers are queried concurrently: both budgets come out of the same
`URL_SCAN_TIMEOUT_SECONDS` window rather than stacking inside the 3-second
end-to-end target. Neither provider failing can fail this function.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Sequence

from redis.asyncio import Redis

from app.clients.reputation import ProviderVerdict
from app.clients.safe_browsing import SafeBrowsingClient
from app.clients.virustotal import VirusTotalClient
from app.core.cache import JsonCache
from app.core.config import Settings, get_settings
from app.pipeline.categories import RiskLevel, worst_risk
from app.pipeline.url_extractor import ExtractedURL

logger = logging.getLogger("app.pipeline.url_safety")

CACHE_PREFIX_SAFE_BROWSING = "urlscan:safe_browsing"
CACHE_PREFIX_VIRUSTOTAL = "urlscan:virustotal"


@dataclass(frozen=True)
class UrlRisk:
    """Combined verdict for one URL."""

    url: str
    domain: str
    is_shortlink: bool
    risk: RiskLevel
    providers: tuple[ProviderVerdict, ...] = ()
    reason: str = ""

    @property
    def degraded(self) -> bool:
        """True when no provider could actually answer for this URL."""
        return not any(verdict.available for verdict in self.providers)

    def as_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "domain": self.domain,
            "is_shortlink": self.is_shortlink,
            "risk": self.risk.value,
            "reason": self.reason,
            "providers": [verdict.as_dict() for verdict in self.providers],
        }


@dataclass(frozen=True)
class UrlScanResult:
    """Result of scanning every URL in one message."""

    risk: RiskLevel
    urls: tuple[UrlRisk, ...] = ()
    skipped: int = 0
    degraded: bool = False
    signals: tuple[str, ...] = field(default_factory=tuple)

    def as_dict(self) -> dict[str, Any]:
        return {
            "risk": self.risk.value,
            "degraded": self.degraded,
            "skipped": self.skipped,
            "urls": [url.as_dict() for url in self.urls],
        }


def _combine(url: ExtractedURL, verdicts: Sequence[ProviderVerdict]) -> UrlRisk:
    answered = [verdict for verdict in verdicts if verdict.available]

    if answered:
        risk = worst_risk(*[verdict.risk for verdict in answered])
        flagged_by = [verdict.provider for verdict in answered if verdict.risk in (RiskLevel.HIGH, RiskLevel.MEDIUM)]
        reason = f"flagged_by={'+'.join(flagged_by)}" if flagged_by else "no_provider_flagged"
    else:
        risk = RiskLevel.UNKNOWN
        reason = "no_provider_available"

    if url.is_shortlink and risk in (RiskLevel.LOW, RiskLevel.UNKNOWN):
        risk = RiskLevel.MEDIUM
        reason = f"{reason};unresolved_shortlink"

    if url.is_ip_host and risk in (RiskLevel.LOW, RiskLevel.UNKNOWN):
        risk = RiskLevel.MEDIUM
        reason = f"{reason};ip_literal_host"

    return UrlRisk(
        url=url.url,
        domain=url.domain,
        is_shortlink=url.is_shortlink,
        risk=risk,
        providers=tuple(verdicts),
        reason=reason,
    )


async def scan_urls(
    urls: Sequence[ExtractedURL],
    redis: Redis | None = None,
    settings: Settings | None = None,
) -> UrlScanResult:
    """Scan up to `URL_SCAN_MAX_URLS` URLs with both providers. Never raises."""
    settings = settings or get_settings()
    if not urls:
        return UrlScanResult(risk=RiskLevel.UNKNOWN)

    checked = list(urls[: settings.url_scan_max_urls])
    skipped = len(urls) - len(checked)
    targets = [url.url for url in checked]

    safe_browsing = SafeBrowsingClient(settings, JsonCache(redis, CACHE_PREFIX_SAFE_BROWSING))
    virustotal = VirusTotalClient(settings, JsonCache(redis, CACHE_PREFIX_VIRUSTOTAL))

    sb_verdicts, vt_verdicts = await asyncio.gather(
        safe_browsing.check_urls(targets),
        virustotal.check_urls(targets),
    )

    combined = tuple(
        _combine(url, (sb_verdicts[index], vt_verdicts[index])) for index, url in enumerate(checked)
    )
    overall = worst_risk(*[item.risk for item in combined])
    degraded = all(item.degraded for item in combined)

    signals: list[str] = []
    if not safe_browsing.configured:
        signals.append("safe_browsing:not_configured")
    if not virustotal.configured:
        signals.append("virustotal:not_configured")
    if skipped:
        signals.append(f"skipped_urls:{skipped}")

    if degraded:
        logger.info(
            "url scan degraded, no provider verdict available",
            extra={"url_count": len(combined), "signals": signals},
        )

    return UrlScanResult(
        risk=overall,
        urls=combined,
        skipped=skipped,
        degraded=degraded,
        signals=tuple(signals),
    )
