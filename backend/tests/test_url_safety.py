"""Safe Browsing + VirusTotal clients and the combined verdict."""

import pytest

from app.clients.safe_browsing import SafeBrowsingClient
from app.clients.virustotal import VirusTotalClient, url_identifier
from app.core.config import Settings
from app.pipeline.categories import RiskLevel
from app.pipeline.url_extractor import extract_urls
from app.pipeline.url_safety import scan_urls
from tests.http_stub import FakeResponse, patch_httpx, raise_timeout

MALICIOUS = "http://bansos-pemerintah-2026.com/klaim"
CLEAN = "https://kemkes.go.id/berita"


def settings_with(**overrides) -> Settings:
    base = {
        "google_safe_browsing_api_key": "sb-test-key",
        "virustotal_api_key": "vt-test-key",
        "url_scan_timeout_seconds": 1.0,
        "url_scan_max_urls": 5,
    }
    base.update(overrides)
    return Settings(**base)


# --------------------------------------------------------------------------
# Google Safe Browsing
# --------------------------------------------------------------------------


async def test_safe_browsing_flags_known_malicious_url(monkeypatch):
    def handler(**kwargs):
        return FakeResponse(
            200,
            {
                "matches": [
                    {"threatType": "SOCIAL_ENGINEERING", "threat": {"url": MALICIOUS}},
                ]
            },
        )

    patch_httpx(monkeypatch, "app.clients.safe_browsing", handler)
    verdicts = await SafeBrowsingClient(settings_with()).check_urls([MALICIOUS, CLEAN])

    assert verdicts[0].risk is RiskLevel.HIGH
    assert verdicts[1].risk is RiskLevel.LOW  # answered and clean, not unknown


async def test_safe_browsing_never_puts_the_api_key_in_the_body(monkeypatch):
    calls = patch_httpx(monkeypatch, "app.clients.safe_browsing", lambda **_: FakeResponse(200, {}))
    await SafeBrowsingClient(settings_with()).check_urls([CLEAN])

    assert calls[0]["params"]["key"] == "sb-test-key"
    assert "sb-test-key" not in str(calls[0]["json"])


async def test_safe_browsing_timeout_degrades_to_unknown(monkeypatch):
    patch_httpx(monkeypatch, "app.clients.safe_browsing", raise_timeout)
    verdicts = await SafeBrowsingClient(settings_with()).check_urls([MALICIOUS])

    assert verdicts[0].risk is RiskLevel.UNKNOWN
    assert verdicts[0].available is False
    assert verdicts[0].reason == "timeout"


async def test_safe_browsing_quota_exceeded_is_reported_not_retried(monkeypatch):
    calls = patch_httpx(monkeypatch, "app.clients.safe_browsing", lambda **_: FakeResponse(429))
    verdicts = await SafeBrowsingClient(settings_with()).check_urls([MALICIOUS])

    assert verdicts[0].reason == "quota_exceeded"
    assert len(calls) == 1


async def test_safe_browsing_without_api_key_is_unavailable_not_clean(monkeypatch):
    client = SafeBrowsingClient(settings_with(google_safe_browsing_api_key=""))
    verdicts = await client.check_urls([MALICIOUS])

    assert client.configured is False
    assert verdicts[0].available is False
    assert verdicts[0].risk is RiskLevel.UNKNOWN


# --------------------------------------------------------------------------
# VirusTotal
# --------------------------------------------------------------------------


def test_virustotal_url_identifier_is_unpadded_base64url():
    assert "=" not in url_identifier(MALICIOUS)


async def test_virustotal_maps_detections_to_risk(monkeypatch):
    def handler(**_):
        return FakeResponse(200, {"data": {"attributes": {"last_analysis_stats": {"malicious": 5}}}})

    patch_httpx(monkeypatch, "app.clients.virustotal", handler)
    verdicts = await VirusTotalClient(settings_with()).check_urls([MALICIOUS])
    assert verdicts[0].risk is RiskLevel.HIGH


async def test_virustotal_single_detection_is_medium_not_high(monkeypatch):
    def handler(**_):
        return FakeResponse(
            200, {"data": {"attributes": {"last_analysis_stats": {"malicious": 1, "suspicious": 0}}}}
        )

    patch_httpx(monkeypatch, "app.clients.virustotal", handler)
    verdicts = await VirusTotalClient(settings_with()).check_urls([MALICIOUS])
    assert verdicts[0].risk is RiskLevel.MEDIUM


async def test_virustotal_unseen_url_is_unknown_not_clean(monkeypatch):
    patch_httpx(monkeypatch, "app.clients.virustotal", lambda **_: FakeResponse(404))
    verdicts = await VirusTotalClient(settings_with()).check_urls([CLEAN])

    assert verdicts[0].available is False
    assert verdicts[0].reason == "not_analyzed"


async def test_virustotal_sends_key_in_header_only(monkeypatch):
    def handler(**_):
        return FakeResponse(200, {"data": {"attributes": {"last_analysis_stats": {"malicious": 0}}}})

    calls = patch_httpx(monkeypatch, "app.clients.virustotal", handler)
    await VirusTotalClient(settings_with()).check_urls([CLEAN])

    assert calls[0]["headers"]["x-apikey"] == "vt-test-key"
    assert "vt-test-key" not in calls[0]["url"]


async def test_virustotal_stops_calling_after_quota_hit(monkeypatch):
    calls = patch_httpx(monkeypatch, "app.clients.virustotal", lambda **_: FakeResponse(429))
    verdicts = await VirusTotalClient(settings_with()).check_urls([MALICIOUS, CLEAN])

    assert len(calls) == 1  # second URL is short-circuited
    assert all(verdict.reason == "quota_exceeded" for verdict in verdicts)


# --------------------------------------------------------------------------
# Combined verdict
# --------------------------------------------------------------------------


@pytest.fixture
def stub_providers(monkeypatch):
    """Drive both providers from one handler, dispatched on the target host.

    Both clients build their own `httpx.AsyncClient`, so a single patch covers
    them — the handler routes by URL rather than by module.
    """

    def configure(safe_browsing: FakeResponse, virustotal: FakeResponse):
        def handler(url: str = "", **_):
            return safe_browsing if "safebrowsing.googleapis.com" in url else virustotal

        patch_httpx(monkeypatch, "app.clients.safe_browsing", handler)

    return configure


async def test_flagged_by_one_provider_is_still_high_risk(stub_providers):
    stub_providers(
        safe_browsing=FakeResponse(
            200, {"matches": [{"threatType": "SOCIAL_ENGINEERING", "threat": {"url": MALICIOUS}}]}
        ),
        virustotal=FakeResponse(200, {"data": {"attributes": {"last_analysis_stats": {"malicious": 0}}}}),
    )

    result = await scan_urls(extract_urls(MALICIOUS), settings=settings_with())
    assert result.risk is RiskLevel.HIGH
    assert "safe_browsing" in result.urls[0].reason


async def test_both_providers_clean_is_low_risk(stub_providers):
    stub_providers(
        safe_browsing=FakeResponse(200, {}),
        virustotal=FakeResponse(200, {"data": {"attributes": {"last_analysis_stats": {"malicious": 0}}}}),
    )

    result = await scan_urls(extract_urls(CLEAN), settings=settings_with())
    assert result.risk is RiskLevel.LOW
    assert result.degraded is False


async def test_both_providers_down_degrades_without_raising(stub_providers):
    stub_providers(safe_browsing=FakeResponse(503), virustotal=FakeResponse(503))

    result = await scan_urls(extract_urls(MALICIOUS), settings=settings_with())
    assert result.risk is RiskLevel.UNKNOWN
    assert result.degraded is True


async def test_unresolvable_shortlink_is_medium_not_low(stub_providers):
    stub_providers(
        safe_browsing=FakeResponse(200, {}),
        virustotal=FakeResponse(404),
    )

    result = await scan_urls(extract_urls("bit.ly/hadiah"), settings=settings_with())
    assert result.risk is RiskLevel.MEDIUM
    assert "unresolved_shortlink" in result.urls[0].reason


async def test_url_count_is_capped_per_message(stub_providers):
    stub_providers(
        safe_browsing=FakeResponse(200, {}),
        virustotal=FakeResponse(200, {"data": {"attributes": {"last_analysis_stats": {"malicious": 0}}}}),
    )
    urls = extract_urls(" ".join(f"https://contoh{index}.com" for index in range(8)))

    result = await scan_urls(urls, settings=settings_with(url_scan_max_urls=3))
    assert len(result.urls) == 3
    assert result.skipped == 5


async def test_no_urls_returns_unknown_without_calling_providers():
    result = await scan_urls([], settings=settings_with())
    assert result.risk is RiskLevel.UNKNOWN
    assert result.urls == ()
