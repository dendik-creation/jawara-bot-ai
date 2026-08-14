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
from typing import Any, Awaitable, Callable, Sequence

from redis.asyncio import Redis

from app.clients.reputation import ProviderVerdict
from app.clients.safe_browsing import SafeBrowsingClient
from app.clients.virustotal import VirusTotalClient
from app.core.cache import JsonCache
from app.core.config import Settings, get_settings
from app.pipeline.categories import RiskLevel, worst_risk
from app.pipeline.url_extractor import ExtractedURL
from app.services.knowledge import TrustedSource, lookup_trusted_sources

logger = logging.getLogger("app.pipeline.url_safety")

TrustedLookup = Callable[[Sequence[str], Settings], Awaitable[dict[str, TrustedSource]]]

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
    # Set when `domain` matches a `fact_sources` row with `is_trusted = TRUE`
    # (Knowledge Base "Sumber Fakta" — see `app.services.knowledge`). This is a
    # domain-recognition signal, not a safety guarantee: it can only pull an
    # otherwise-unknown verdict up to LOW, never suppress a HIGH a provider
    # actually flagged (`_apply_trust` below).
    is_trusted: bool = False
    trusted_source_id: int | None = None
    trusted_source_name: str | None = None

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
            "is_trusted": self.is_trusted,
            "trusted_source_name": self.trusted_source_name,
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


def _combine(url: ExtractedURL, verdicts: Sequence[ProviderVerdict], trusted: TrustedSource | None = None) -> UrlRisk:
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

    # Trust precedence (Part 10 of the false-positive fix task): a confirmed
    # threat — HIGH or MEDIUM from an actual provider answer, or the
    # shortlink/IP-literal caution above — always stands; an official site can
    # in principle be compromised, so recognition never suppresses evidence.
    # Trust can only turn "no evidence either way" (UNKNOWN) into LOW. A
    # provider that *answered* LOW already agrees, so there is nothing to
    # override there either — this is strictly the UNKNOWN -> LOW case.
    if trusted is not None and risk is RiskLevel.UNKNOWN:
        risk = RiskLevel.LOW
        reason = f"{reason};trusted_official_domain={trusted.name}"

    return UrlRisk(
        url=url.url,
        domain=url.domain,
        is_shortlink=url.is_shortlink,
        risk=risk,
        providers=tuple(verdicts),
        reason=reason,
        is_trusted=trusted is not None,
        trusted_source_id=trusted.id if trusted else None,
        trusted_source_name=trusted.name if trusted else None,
    )


async def scan_urls(
    urls: Sequence[ExtractedURL],
    redis: Redis | None = None,
    settings: Settings | None = None,
    trusted_lookup: TrustedLookup | None = None,
    request_id: str | None = None,
) -> UrlScanResult:
    """Scan up to `URL_SCAN_MAX_URLS` URLs with both providers. Never raises.

    `trusted_lookup` defaults to the real Knowledge Base query
    (`app.services.knowledge.lookup_trusted_sources`); tests inject a stub so
    they never need a live Postgres to exercise provider-only behaviour.
    """
    settings = settings or get_settings()
    if not urls:
        return UrlScanResult(risk=RiskLevel.UNKNOWN)

    checked = list(urls[: settings.url_scan_max_urls])
    skipped = len(urls) - len(checked)
    targets = [url.url for url in checked]

    safe_browsing = SafeBrowsingClient(settings, JsonCache(redis, CACHE_PREFIX_SAFE_BROWSING))
    virustotal = VirusTotalClient(settings, JsonCache(redis, CACHE_PREFIX_VIRUSTOTAL))
    lookup = trusted_lookup or lookup_trusted_sources

    (sb_verdicts, vt_verdicts), trusted_map = await asyncio.gather(
        asyncio.gather(
            safe_browsing.check_urls(targets),
            virustotal.check_urls(targets),
        ),
        lookup([url.domain for url in checked], settings),
    )

    combined = tuple(
        _combine(url, (sb_verdicts[index], vt_verdicts[index]), trusted_map.get(url.domain))
        for index, url in enumerate(checked)
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

    # One line per URL, deliberately verbose: this is the log a false
    # positive gets diagnosed from (task §15) — "computed_risk=LOW but
    # final_status=HIGH" points straight at the LLM layer, not this one.
    for item in combined:
        logger.info(
            "url safety evaluated",
            extra={
                "request_id": request_id,
                "url": item.url,
                "domain": item.domain,
                "trusted_source_found": item.is_trusted,
                "trusted_source_id": item.trusted_source_id,
                "trusted_source_name": item.trusted_source_name,
                "provider_results": {verdict.provider: verdict.risk.value for verdict in item.providers},
                "computed_risk": item.risk.value,
                "reason": item.reason,
            },
        )

    return UrlScanResult(
        risk=overall,
        urls=combined,
        skipped=skipped,
        degraded=degraded,
        signals=tuple(signals),
    )
