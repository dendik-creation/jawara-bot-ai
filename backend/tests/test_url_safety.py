"""Safe Browsing + VirusTotal clients and the combined verdict."""

import pytest

from app.clients.safe_browsing import SafeBrowsingClient
from app.clients.virustotal import VirusTotalClient, url_identifier
from app.core.config import Settings
from app.pipeline.categories import RiskLevel
from app.pipeline.url_extractor import extract_urls
from app.pipeline.url_safety import scan_urls
from app.services.knowledge import TrustedSource
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


# --------------------------------------------------------------------------
# Trusted Knowledge Base domains (`!link` false-positive fix, Parts 4/8/10/12)
#
# `trusted_lookup` is injected directly rather than going through a real
# Postgres — `scan_urls`'s default (`app.services.knowledge.
# lookup_trusted_sources`) is exercised separately in
# `test_knowledge_trusted_sources.py`. What matters here is the precedence
# rule in `_combine`, independent of how the trust signal was sourced.
# --------------------------------------------------------------------------


def _trusted_lookup(**domain_to_source: TrustedSource):
    """Exact-or-subdomain match, mirroring `knowledge.lookup_trusted_sources`'s
    own semantics — the point of these tests is `_combine`'s precedence
    logic, not re-deriving domain matching."""

    async def lookup(domains, settings):  # noqa: ANN001, ARG001 — matches TrustedLookup's shape
        matched = {}
        for domain in domains:
            for trusted_domain, source in domain_to_source.items():
                if domain == trusted_domain or domain.endswith(f".{trusted_domain}"):
                    matched[domain] = source
                    break
        return matched

    return lookup


PLN = TrustedSource(id=1, name="PLN", normalized_domain="pln.co.id")


async def test_trusted_domain_with_no_provider_evidence_is_low_not_high(stub_providers):
    # Case 1 / Case 5: PLN, no confirmed threat anywhere — must not be HIGH,
    # must not be HOAX-shaped either; it becomes LOW ("official, no threat
    # evidence found"), never a bare guess. Both providers unavailable (not
    # merely "clean"), so the pre-trust risk is genuinely UNKNOWN.
    stub_providers(safe_browsing=FakeResponse(503), virustotal=FakeResponse(503))

    result = await scan_urls(
        extract_urls("https://www.pln.co.id"),
        settings=settings_with(),
        trusted_lookup=_trusted_lookup(**{"pln.co.id": PLN}),
    )

    assert result.risk is RiskLevel.LOW
    assert result.urls[0].is_trusted is True
    assert result.urls[0].trusted_source_name == "PLN"
    assert "trusted_official_domain" in result.urls[0].reason


async def test_unknown_domain_with_no_kb_entry_and_no_reputation_stays_unknown(stub_providers):
    # Case 2: nothing in the KB, nothing from the providers — UNKNOWN, not HIGH.
    stub_providers(safe_browsing=FakeResponse(503), virustotal=FakeResponse(503))

    result = await scan_urls(
        extract_urls("https://contoh-domain-baru.com"),
        settings=settings_with(),
        trusted_lookup=_trusted_lookup(),
    )

    assert result.risk is RiskLevel.UNKNOWN
    assert result.urls[0].is_trusted is False


async def test_subdomain_of_a_trusted_registrable_domain_is_recognised(stub_providers):
    # Case 7: `rekrutmen.pln.co.id` belongs to the trusted `pln.co.id`.
    stub_providers(safe_browsing=FakeResponse(503), virustotal=FakeResponse(503))

    result = await scan_urls(
        extract_urls("https://rekrutmen.pln.co.id/loker"),
        settings=settings_with(),
        trusted_lookup=_trusted_lookup(**{"pln.co.id": PLN}),
    )

    assert result.urls[0].is_trusted is True
    assert result.risk is RiskLevel.LOW


async def test_lookalike_domain_is_not_trusted(stub_providers):
    # Case 8: the text "pln.co.id" merely appears inside another domain —
    # must not be trusted by substring matching.
    stub_providers(safe_browsing=FakeResponse(503), virustotal=FakeResponse(503))

    result = await scan_urls(
        extract_urls("https://pln-co-id.example.com"),
        settings=settings_with(),
        trusted_lookup=_trusted_lookup(**{"pln.co.id": PLN}),
    )

    assert result.urls[0].is_trusted is False
    assert result.risk is RiskLevel.UNKNOWN


async def test_confirmed_malicious_provider_result_overrides_trust(stub_providers):
    # Case 9: a trusted domain is not a blank check — a provider that actually
    # confirms a threat must still win. (Hypothetical: the site is compromised.)
    stub_providers(
        safe_browsing=FakeResponse(
            200, {"matches": [{"threatType": "SOCIAL_ENGINEERING", "threat": {"url": "https://www.pln.co.id"}}]}
        ),
        virustotal=FakeResponse(404),
    )

    result = await scan_urls(
        extract_urls("https://www.pln.co.id"),
        settings=settings_with(),
        trusted_lookup=_trusted_lookup(**{"pln.co.id": PLN}),
    )

    assert result.risk is RiskLevel.HIGH
    assert result.urls[0].is_trusted is True  # recognition and safety are reported separately


async def test_trusted_domain_does_not_downgrade_a_medium_signal(stub_providers):
    # Trust only fills in for UNKNOWN (no evidence). A provider that actually
    # answered MEDIUM found *something* — trust must not silently launder it.
    stub_providers(
        safe_browsing=FakeResponse(200, {}),
        virustotal=FakeResponse(200, {"data": {"attributes": {"last_analysis_stats": {"malicious": 1}}}}),
    )

    result = await scan_urls(
        extract_urls("https://www.pln.co.id"),
        settings=settings_with(),
        trusted_lookup=_trusted_lookup(**{"pln.co.id": PLN}),
    )

    assert result.risk is RiskLevel.MEDIUM
