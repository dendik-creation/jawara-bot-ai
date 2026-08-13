"""TurnBackHoax adapter and the polite HTTP layer behind it.

Fixtures mirror the real documents as probed in August 2026: an RSS feed
carrying only title/link/guid/description, and an article page carrying a
`ClaimReview` JSON-LD block plus `article-origin`/`article-explanation`/
`article-factcheck` sections. The point of these tests is that the parsers
survive what a live site actually does — missing fields, an extra section,
broken JSON-LD, a truncated feed — without the pipeline having to know any
of it.
"""

import asyncio

import pytest

from app.core.config import Settings
from app.ingestion.base import SourceCandidate, SourceFetchError, SourceParseError, canonical_url
from app.ingestion.http import PoliteHttpClient
from app.ingestion.turnbackhoax import (
    TurnBackHoaxAdapter,
    html_to_text,
    map_category,
    map_verdict,
    parse_feed,
)
from tests.http_stub import FakeResponse, patch_httpx, raise_timeout

FEED = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>TurnBackHoax.id</title>
    <item>
      <title>[SALAH] Uni Eropa Larang Indonesia Produksi BBM B50</title>
      <link>https://turnbackhoax.id/articles/36110-salah-uni-eropa-larang-b50?utm_source=rss</link>
      <guid isPermaLink="false">36110</guid>
      <description>&lt;p&gt;Beredar &lt;a href="#"&gt;unggahan&lt;/a&gt; berisi klaim Uni Eropa melarang B50.&lt;/p&gt;</description>
    </item>
    <item>
      <title>[PENIPUAN] Tautan Pendaftaran Upacara 17 Agustus di Istana</title>
      <link>https://turnbackhoax.id/articles/36113-penipuan-tautan-pendaftaran-upacara</link>
      <guid isPermaLink="false">36113</guid>
      <description>Beredar tautan pendaftaran upacara.</description>
    </item>
  </channel>
</rss>
"""

FEED_WITH_BROKEN_ITEM = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <item>
      <title>[SALAH] Judul yang baik</title>
      <link>https://turnbackhoax.id/articles/1-judul-yang-baik</link>
      <guid isPermaLink="false">1</guid>
      <description>Klaim.</description>
    </item>
    <item>
      <title>[SALAH] Tanpa tautan</title>
      <guid isPermaLink="false">2</guid>
    </item>
    <item>
      <link>https://turnbackhoax.id/articles/3-tanpa-judul</link>
      <guid isPermaLink="false">3</guid>
    </item>
  </channel>
</rss>
"""

ARTICLE = """<html><head>
<script type="application/ld+json">
{
    "@context": "https://schema.org",
    "@type": "ClaimReview",
    "url": "https://turnbackhoax.id/articles/36110-salah-uni-eropa-larang-b50",
    "claimReviewed": "[SALAH] Uni Eropa Larang Indonesia Produksi BBM B50",
    "itemReviewed": {"@type": "Claim", "datePublished": "2026-08-12"},
    "author": {"@type": "Organization", "name": "Mafindo"},
    "reviewRating": {"@type": "Rating", "ratingValue": "1", "alternateName": "Salah"}
}
</script></head>
<body>
<h1>[SALAH] Uni Eropa Larang Indonesia Produksi BBM B50</h1>
<p><span><a class="text-light-blue" href="/articles?category=Politik">Politik</a></span>
<time datetime="2026-08-12">12/08/2026</time><span>Mafindo</span></p>
<section class="article-origin custom-styling-editor">
    <strong class="block mb-4">Narasi</strong>
    <div class="quoted"><p>Beredar unggahan berisi klaim Uni Eropa melarang Indonesia memproduksi BBM B50.</p></div>
</section>
<section class="article-explanation custom-styling-editor">
    <strong class="block mb-4">Penjelasan</strong>
    <div><p>Tidak ditemukan kebijakan Uni Eropa yang melarang produksi B50.</p></div>
</section>
<section class="article-explanation">
    <strong class="block mb-4">Kesimpulan</strong>
    <div>Faktanya klaim tersebut tidak benar.</div>
</section>
<section class="article-factcheck">
    <strong class="block mb-4">Hasil Periksa fakta</strong>
    <div class="quoted"><span class="factcheck-result"><strong>Salah</strong></span></div>
</section>
</body></html>
"""

CANDIDATE = SourceCandidate(
    external_id="36110",
    url="https://turnbackhoax.id/articles/36110-salah-uni-eropa-larang-b50?utm_source=rss",
    title="[SALAH] Uni Eropa Larang Indonesia Produksi BBM B50",
    summary="Beredar unggahan berisi klaim Uni Eropa melarang B50.",
)


def _adapter() -> TurnBackHoaxAdapter:
    return TurnBackHoaxAdapter(Settings(fact_ingestion_max_attempts=1, fact_ingestion_request_delay_seconds=0.0))


# --------------------------------------------------------------------------
# Feed parsing
# --------------------------------------------------------------------------


def test_feed_parses_every_valid_item():
    candidates = parse_feed(FEED)

    assert [c.external_id for c in candidates] == ["36110", "36113"]
    assert candidates[0].title.startswith("[SALAH]")
    assert "Uni Eropa melarang B50" in candidates[0].summary
    # The description arrives as escaped HTML; what reaches the pipeline is text.
    assert "<p>" not in candidates[0].summary


def test_feed_items_missing_link_or_title_are_skipped_not_fatal():
    candidates = parse_feed(FEED_WITH_BROKEN_ITEM)

    assert [c.external_id for c in candidates] == ["1"]


def test_malformed_feed_raises_parse_error():
    with pytest.raises(SourceParseError):
        parse_feed("<rss><channel><item><title>unclosed")


def test_html_response_where_a_feed_was_expected_raises_parse_error():
    with pytest.raises(SourceParseError):
        parse_feed("<html><body>maintenance</body></html>")


# --------------------------------------------------------------------------
# Article normalization
# --------------------------------------------------------------------------


def test_article_normalizes_into_a_complete_record():
    record = _adapter()._build_record(CANDIDATE, ARTICLE)

    assert record.missing_fields() == []
    assert record.external_id == "36110"
    # Tracking parameters are not part of the document's identity.
    assert record.source_url == "https://turnbackhoax.id/articles/36110-salah-uni-eropa-larang-b50"
    assert record.verdict == "HOAX"
    assert "Uni Eropa melarang Indonesia memproduksi BBM B50" in record.claim_text
    # Penjelasan *and* Kesimpulan — the conclusion is what the LLM will quote.
    assert "Tidak ditemukan kebijakan" in record.fact_explanation
    assert "Faktanya klaim tersebut tidak benar" in record.fact_explanation
    # Section labels are not content.
    assert not record.fact_explanation.startswith("Penjelasan")
    assert record.published_at is not None
    assert record.published_at.isoformat().startswith("2026-08-12")
    assert record.raw_metadata["site_category"] == "Politik"
    assert record.raw_metadata["verdict_label"] == "Salah"


def test_article_without_json_ld_falls_back_to_html_sections():
    stripped = ARTICLE[ARTICLE.index("</script>") + len("</script>") :]

    record = _adapter()._build_record(CANDIDATE, stripped)

    assert record.verdict == "HOAX"  # from the article-factcheck section
    assert record.published_at.isoformat().startswith("2026-08-12")  # from <time datetime>


def test_broken_json_ld_does_not_lose_the_article():
    broken = ARTICLE.replace('"@type": "ClaimReview",', '"@type": "ClaimReview",,,')

    record = _adapter()._build_record(CANDIDATE, broken)

    assert record.missing_fields() == []
    assert record.verdict == "HOAX"


def test_article_without_an_explanation_is_reported_as_incomplete():
    """A fact item with no debunk would still embed and still be retrieved —
    the LLM would then cite an explanation that says nothing."""
    empty = "<html><body><section class=\"article-origin\">Narasi Klaim saja.</section></body></html>"

    record = _adapter()._build_record(CANDIDATE, empty)

    assert record.missing_fields() == ["fact_explanation"]


def test_claim_falls_back_to_the_feed_excerpt_when_the_page_has_no_narasi():
    without_claim = ARTICLE.replace("article-origin custom-styling-editor", "article-unknown")

    record = _adapter()._build_record(CANDIDATE, without_claim)

    assert record.claim_text == CANDIDATE.summary


def test_fingerprint_changes_only_when_content_changes():
    adapter = _adapter()
    original = adapter._build_record(CANDIDATE, ARTICLE)
    reformatted = adapter._build_record(CANDIDATE, ARTICLE.replace("\n", "\n   "))
    edited = adapter._build_record(CANDIDATE, ARTICLE.replace("tidak benar", "keliru"))

    assert original.fingerprint() == reformatted.fingerprint()
    assert original.fingerprint() != edited.fingerprint()


# --------------------------------------------------------------------------
# Vocabulary mapping
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "label,expected",
    [
        ("Salah", "HOAX"),
        ("PENIPUAN", "HOAX"),
        ("Konten yang Menyesatkan", "MISLEADING"),
        ("Parodi", "MISLEADING"),
        ("Benar", "FACT"),
        ("", "UNVERIFIED"),
        ("Kategori Baru Yang Belum Ada", "UNVERIFIED"),
    ],
)
def test_verdict_mapping(label, expected):
    assert map_verdict(label) == expected


@pytest.mark.parametrize(
    "title,claim,expected",
    [
        ("[PENIPUAN] Tautan pendaftaran bansos", "", "PHISHING_LINK"),
        ("[SALAH] File APK undangan pernikahan", "", "FILE_APK"),
        ("[PENIPUAN] Undian berhadiah mengatasnamakan bank", "", "FINANCIAL_FRAUD"),
        ("[SALAH] Vaksin menyebabkan kanker", "", "HEALTH_HOAX"),
        ("[SALAH] Presiden mengunjungi kota X", "kunjungan kenegaraan", "GENERAL_NEWS"),
    ],
)
def test_category_mapping(title, claim, expected):
    assert map_category(title, claim) == expected


def test_html_to_text_strips_scripts_and_collapses_whitespace():
    text = html_to_text("<div>Halo <script>evil()</script>  <b>dunia</b></div>")

    assert "evil" not in text
    assert text == "Halo dunia"


def test_canonical_url_drops_query_and_fragment_and_trailing_slash():
    assert canonical_url("HTTPS://TurnBackHoax.id/articles/1-x/?utm=a#top") == (
        "https://turnbackhoax.id/articles/1-x"
    )


# --------------------------------------------------------------------------
# HTTP failure handling — everything the source can do to us
# --------------------------------------------------------------------------


def _client(**overrides) -> PoliteHttpClient:
    # No delay, no backoff: the politeness pauses are configuration, and a
    # suite that actually slept through them would test `asyncio.sleep`.
    config = {
        "fact_ingestion_max_attempts": 1,
        "fact_ingestion_request_delay_seconds": 0.0,
        "fact_ingestion_retry_backoff_seconds": 0.0,
        **overrides,
    }
    return PoliteHttpClient(Settings(**config))


def test_timeout_is_a_retryable_fetch_error(monkeypatch):
    patch_httpx(monkeypatch, "app.ingestion.http", raise_timeout)

    with pytest.raises(SourceFetchError) as excinfo:
        asyncio.run(_client().get_text("https://turnbackhoax.id/feed"))

    assert excinfo.value.retryable is True


@pytest.mark.parametrize("status_code,retryable", [(429, True), (500, True), (503, True), (403, False), (404, False)])
def test_status_codes_map_to_the_right_retryability(monkeypatch, status_code, retryable):
    patch_httpx(monkeypatch, "app.ingestion.http", lambda **_: FakeResponse(status_code=status_code))

    with pytest.raises(SourceFetchError) as excinfo:
        asyncio.run(_client().get_text("https://turnbackhoax.id/feed"))

    assert excinfo.value.status_code == status_code
    assert excinfo.value.retryable is retryable


def test_retryable_status_is_retried_up_to_the_configured_attempts(monkeypatch):
    calls = patch_httpx(monkeypatch, "app.ingestion.http", lambda **_: FakeResponse(status_code=503))

    with pytest.raises(SourceFetchError):
        asyncio.run(_client(fact_ingestion_max_attempts=3).get_text("https://turnbackhoax.id/feed"))

    assert len(calls) == 3


def test_permanent_status_is_not_retried(monkeypatch):
    calls = patch_httpx(monkeypatch, "app.ingestion.http", lambda **_: FakeResponse(status_code=403))

    with pytest.raises(SourceFetchError):
        asyncio.run(_client(fact_ingestion_max_attempts=3).get_text("https://turnbackhoax.id/feed"))

    assert len(calls) == 1


def test_crawler_identifies_itself(monkeypatch):
    calls = patch_httpx(monkeypatch, "app.ingestion.http", lambda **_: FakeResponse(text="ok"))

    asyncio.run(_client().get_text("https://turnbackhoax.id/feed"))

    assert "JAWARA" in calls[0]["headers"]["User-Agent"]


def test_adapter_lists_candidates_over_http(monkeypatch):
    patch_httpx(monkeypatch, "app.ingestion.http", lambda **_: FakeResponse(text=FEED))

    candidates = asyncio.run(_adapter().list_candidates(limit=10))

    assert [c.external_id for c in candidates] == ["36110", "36113"]


def test_adapter_respects_the_per_run_item_cap(monkeypatch):
    patch_httpx(monkeypatch, "app.ingestion.http", lambda **_: FakeResponse(text=FEED))

    assert len(asyncio.run(_adapter().list_candidates(limit=1))) == 1


def test_adapter_fetches_and_normalizes_one_article(monkeypatch):
    patch_httpx(monkeypatch, "app.ingestion.http", lambda **_: FakeResponse(text=ARTICLE))

    record = asyncio.run(_adapter().fetch_record(CANDIDATE))

    assert record.verdict == "HOAX"
    assert record.source_name == "TurnBackHoax"
    assert record.source_slug == "turnbackhoax"
