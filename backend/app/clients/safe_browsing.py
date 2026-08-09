"""Google Safe Browsing v4 client ([[Integrate Safe Browsing]]).

Primary URL-reputation source for the phishing domain (bansos, banking, promo
scams). Lookup API `threatMatches:find`, one HTTP call for a batch of URLs.

Quota handling (documented before production traffic, as the task asks): the
free Lookup API allows ~10k requests/day. Two measures keep JAWARA inside it —
verdicts are cached in Redis for `URL_SCAN_CACHE_TTL_SECONDS` (a forwarded link
arrives dozens of times), and at most `URL_SCAN_MAX_URLS` URLs per message are
checked. On HTTP 429 the provider is reported unavailable for that message
rather than retried; retrying into a quota wall only deepens the hole.

The API key is read from the environment and never logged — not in the request
URL that appears in exception text, and not in error paths (see `_scrub`).
"""

import logging
from typing import Any, Sequence

import httpx

from app.clients.reputation import ProviderVerdict
from app.core.cache import JsonCache
from app.core.config import Settings, get_settings
from app.pipeline.categories import RiskLevel

logger = logging.getLogger("app.clients.safe_browsing")

PROVIDER = "safe_browsing"
API_URL = "https://safebrowsing.googleapis.com/v4/threatMatches:find"

CLIENT_ID = "jawara"
CLIENT_VERSION = "1.0.0"

THREAT_TYPES = [
    "MALWARE",
    "SOCIAL_ENGINEERING",
    "UNWANTED_SOFTWARE",
    "POTENTIALLY_HARMFUL_APPLICATION",
]

# Every Safe Browsing threat type is a "do not open this" verdict; the API does
# not express degrees. Mapping them all to HIGH is the honest translation.
_THREAT_RISK = RiskLevel.HIGH


class SafeBrowsingClient:
    def __init__(self, settings: Settings | None = None, cache: JsonCache | None = None) -> None:
        self._settings = settings or get_settings()
        self._cache = cache

    @property
    def configured(self) -> bool:
        return bool(self._settings.google_safe_browsing_api_key)

    async def check_urls(self, urls: Sequence[str]) -> list[ProviderVerdict]:
        """Verdict per URL, in input order. Never raises."""
        if not urls:
            return []
        if not self.configured:
            return [ProviderVerdict.unavailable(PROVIDER, url, "api_key_missing") for url in urls]

        cached: dict[str, ProviderVerdict] = {}
        to_check: list[str] = []
        for url in urls:
            hit = await self._cached(url)
            if hit is not None:
                cached[url] = hit
            else:
                to_check.append(url)

        fresh: dict[str, ProviderVerdict] = {}
        if to_check:
            fresh = await self._lookup(to_check)
            for url, verdict in fresh.items():
                if verdict.available:
                    await self._store(url, verdict)

        return [
            cached.get(url)
            or fresh.get(url)
            or ProviderVerdict.unavailable(PROVIDER, url, "no_result")
            for url in urls
        ]

    async def _lookup(self, urls: list[str]) -> dict[str, ProviderVerdict]:
        body: dict[str, Any] = {
            "client": {"clientId": CLIENT_ID, "clientVersion": CLIENT_VERSION},
            "threatInfo": {
                "threatTypes": THREAT_TYPES,
                "platformTypes": ["ANY_PLATFORM"],
                "threatEntryTypes": ["URL"],
                "threatEntries": [{"url": url} for url in urls],
            },
        }

        try:
            async with httpx.AsyncClient(timeout=self._settings.url_scan_timeout_seconds) as client:
                response = await client.post(
                    API_URL,
                    params={"key": self._settings.google_safe_browsing_api_key},
                    json=body,
                )
        except httpx.TimeoutException:
            logger.warning("safe browsing timeout", extra={"url_count": len(urls)})
            return {url: ProviderVerdict.unavailable(PROVIDER, url, "timeout") for url in urls}
        except httpx.HTTPError as exc:
            logger.warning("safe browsing unreachable", extra={"error": _scrub(str(exc))})
            return {url: ProviderVerdict.unavailable(PROVIDER, url, "unreachable") for url in urls}

        if response.status_code == 429:
            logger.warning("safe browsing quota exceeded")
            return {url: ProviderVerdict.unavailable(PROVIDER, url, "quota_exceeded") for url in urls}
        if response.status_code >= 400:
            logger.warning("safe browsing error response", extra={"status": response.status_code})
            return {
                url: ProviderVerdict.unavailable(PROVIDER, url, f"http_{response.status_code}")
                for url in urls
            }

        try:
            matches = response.json().get("matches") or []
        except ValueError:
            return {url: ProviderVerdict.unavailable(PROVIDER, url, "malformed_response") for url in urls}

        flagged: dict[str, str] = {}
        for match in matches:
            matched_url = (match.get("threat") or {}).get("url")
            if matched_url:
                flagged[matched_url] = match.get("threatType", "UNKNOWN_THREAT")

        # An empty `matches` array is a real answer: Safe Browsing has no record
        # of these URLs. That is LOW, not UNKNOWN.
        return {
            url: ProviderVerdict(
                provider=PROVIDER,
                url=url,
                risk=_THREAT_RISK if url in flagged else RiskLevel.LOW,
                reason=flagged.get(url, "no_match"),
                details={"threat_type": flagged[url]} if url in flagged else {},
            )
            for url in urls
        }

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


def _scrub(message: str) -> str:
    """Drop anything that could carry the API key into a log line."""
    return message.split("?")[0]
