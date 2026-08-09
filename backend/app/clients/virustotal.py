"""VirusTotal API v3 client ([[Integrate VirusTotal]]).

Second URL-reputation source. VirusTotal aggregates ~90 scanning engines and
reports counts, so the mapping to `risk_level_enum` is a threshold decision, not
a direct translation: one detection out of ninety is frequently a false
positive, two or more is a signal (`VIRUSTOTAL_HIGH_THRESHOLD`).

Quota handling (documented before production traffic, as the task asks): the
public API allows 4 requests/minute and 500/day. JAWARA stays inside it by
caching verdicts in Redis for `URL_SCAN_CACHE_TTL_SECONDS`, capping URLs per
message at `URL_SCAN_MAX_URLS`, and treating HTTP 429 as "provider unavailable
for this message" instead of retrying — VirusTotal's limit is a rolling window,
so an immediate retry is guaranteed to fail again.

Only the *lookup* endpoint is used. Submitting URLs for scanning would publish
the links our users forward to a third party, which the privacy model does not
allow (09_Security/01_Threat_Model_and_Data_Protection.md).

The API key is read from the environment, sent in the `x-apikey` header, and
never logged.
"""

import base64
import logging
from typing import Sequence

import httpx

from app.clients.reputation import ProviderVerdict
from app.core.cache import JsonCache
from app.core.config import Settings, get_settings
from app.pipeline.categories import RiskLevel

logger = logging.getLogger("app.clients.virustotal")

PROVIDER = "virustotal"
API_BASE = "https://www.virustotal.com/api/v3"


def url_identifier(url: str) -> str:
    """VirusTotal's URL id: unpadded base64url of the URL itself."""
    return base64.urlsafe_b64encode(url.encode()).decode().rstrip("=")


class VirusTotalClient:
    def __init__(self, settings: Settings | None = None, cache: JsonCache | None = None) -> None:
        self._settings = settings or get_settings()
        self._cache = cache

    @property
    def configured(self) -> bool:
        return bool(self._settings.virustotal_api_key)

    async def check_urls(self, urls: Sequence[str]) -> list[ProviderVerdict]:
        """Verdict per URL, in input order. Never raises.

        v3 has no batch lookup, so this is one request per URL — the reason the
        per-message URL cap matters more here than for Safe Browsing.
        """
        if not urls:
            return []
        if not self.configured:
            return [ProviderVerdict.unavailable(PROVIDER, url, "api_key_missing") for url in urls]

        verdicts: list[ProviderVerdict] = []
        quota_hit = False
        for url in urls:
            if quota_hit:
                verdicts.append(ProviderVerdict.unavailable(PROVIDER, url, "quota_exceeded"))
                continue

            cached = await self._cached(url)
            if cached is not None:
                verdicts.append(cached)
                continue

            verdict = await self._lookup(url)
            if verdict.reason == "quota_exceeded":
                quota_hit = True
            if verdict.available:
                await self._store(url, verdict)
            verdicts.append(verdict)
        return verdicts

    async def _lookup(self, url: str) -> ProviderVerdict:
        endpoint = f"{API_BASE}/urls/{url_identifier(url)}"
        try:
            async with httpx.AsyncClient(timeout=self._settings.url_scan_timeout_seconds) as client:
                response = await client.get(
                    endpoint, headers={"x-apikey": self._settings.virustotal_api_key}
                )
        except httpx.TimeoutException:
            logger.warning("virustotal timeout")
            return ProviderVerdict.unavailable(PROVIDER, url, "timeout")
        except httpx.HTTPError:
            logger.warning("virustotal unreachable")
            return ProviderVerdict.unavailable(PROVIDER, url, "unreachable")

        if response.status_code == 404:
            # VirusTotal has simply never seen this URL. That is not "clean".
            return ProviderVerdict.unavailable(PROVIDER, url, "not_analyzed")
        if response.status_code == 429:
            logger.warning("virustotal quota exceeded")
            return ProviderVerdict.unavailable(PROVIDER, url, "quota_exceeded")
        if response.status_code in (401, 403):
            logger.warning("virustotal rejected credentials", extra={"status": response.status_code})
            return ProviderVerdict.unavailable(PROVIDER, url, "unauthorized")
        if response.status_code >= 400:
            return ProviderVerdict.unavailable(PROVIDER, url, f"http_{response.status_code}")

        try:
            attributes = response.json()["data"]["attributes"]
        except (ValueError, KeyError, TypeError):
            return ProviderVerdict.unavailable(PROVIDER, url, "malformed_response")

        stats = attributes.get("last_analysis_stats") or {}
        malicious = int(stats.get("malicious", 0))
        suspicious = int(stats.get("suspicious", 0))
        risk = self._risk_from_stats(malicious, suspicious)

        return ProviderVerdict(
            provider=PROVIDER,
            url=url,
            risk=risk,
            reason=f"malicious={malicious},suspicious={suspicious}",
            details={"malicious": malicious, "suspicious": suspicious},
        )

    def _risk_from_stats(self, malicious: int, suspicious: int) -> RiskLevel:
        if malicious >= self._settings.virustotal_high_threshold:
            return RiskLevel.HIGH
        if malicious >= 1 or suspicious >= 1:
            return RiskLevel.MEDIUM
        return RiskLevel.LOW

    async def _cached(self, url: str) -> ProviderVerdict | None:
        if self._cache is None:
            return None
        payload = await self._cache.get(url)
        if not isinstance(payload, dict):
            return None
        return ProviderVerdict(
            provider=PROVIDER,
            url=url,
            risk=RiskLevel(payload.get("risk", RiskLevel.UNKNOWN.value)),
            available=True,
            cached=True,
            reason=payload.get("reason", ""),
        )

    async def _store(self, url: str, verdict: ProviderVerdict) -> None:
        if self._cache is None:
            return
        await self._cache.set(
            url,
            {"risk": verdict.risk.value, "reason": verdict.reason},
            self._settings.url_scan_cache_ttl_seconds,
        )
