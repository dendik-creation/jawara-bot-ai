"""TurnBackHoax / MAFINDO adapter.

Structure of the source, as probed before this was written (August 2026):

* `robots.txt` is `Disallow:` — nothing is off limits, but the crawl is kept
  to one feed request per run plus one request per genuinely new article.
* There is no public API. The site is not WordPress any more, so
  `/wp-json/...` is gone; `/feed` is a hand-rolled RSS 2.0 document. It is
  the closest thing to a structured feed the source offers, so it is
  preferred over scraping the article index, per "prefer an official feed".
* That feed carries **only** `title`, `link`, `guid` and `description`. No
  `pubDate`, no `category`, no `content:encoded`, and no pagination — always
  the 10 newest items. So the feed alone cannot answer "when was this
  published" or "what did they rule", and the poll interval has to stay
  below the source's own 10-article turnover.
* Article pages carry a `ClaimReview` JSON-LD block (`reviewRating
  .alternateName` = the verdict, `itemReviewed.datePublished` = the date)
  plus stable section classes (`article-origin` = Narasi/claim,
  `article-explanation` = Penjelasan + Kesimpulan, `article-factcheck`
  = the ruling) and a `<time datetime="...">` element.

Hence the two-stage shape: the feed is the change detector, the article page
is the record. JSON-LD is read first and the HTML sections are the fallback
— schema.org markup is a contract the site maintains for search engines,
while class names are incidental. Every one of those parsers lives in this
module; nothing outside it knows TurnBackHoax exists.
"""

import json
import logging
import re
from html import unescape
from html.parser import HTMLParser
from typing import Any
from xml.etree import ElementTree

from app.core.config import Settings, get_settings
from app.ingestion.base import (
    DEFAULT_CATEGORY,
    FactCheckSourceAdapter,
    NormalizedFactRecord,
    SourceCandidate,
    SourceParseError,
    canonical_url,
    clamp_title,
    parse_iso_date,
)
from app.ingestion.http import PoliteHttpClient

logger = logging.getLogger("app.ingestion.turnbackhoax")

# MAFINDO's ruling vocabulary → `verdict_enum`. Everything false-by-any-name
# collapses to HOAX because the enum has no finer grades; satire/parody and
# partly-true rulings are MISLEADING, which is exactly what they are — the
# content is not fabricated, the reading of it is wrong. An unrecognised
# label stays UNVERIFIED rather than being guessed into HOAX.
VERDICT_MAP = {
    "salah": "HOAX",
    "hoaks": "HOAX",
    "hoax": "HOAX",
    "penipuan": "HOAX",
    "fitnah": "HOAX",
    "disinformasi": "HOAX",
    "misinformasi": "HOAX",
    "konten palsu": "HOAX",
    "konten tiruan": "HOAX",
    "konten yang dimanipulasi": "HOAX",
    "konten yang menyesatkan": "MISLEADING",
    "menyesatkan": "MISLEADING",
    "sebagian benar": "MISLEADING",
    "parodi": "MISLEADING",
    "satire": "MISLEADING",
    "konteks keliru": "MISLEADING",
    "benar": "FACT",
    "fakta": "FACT",
}

# Keyword → `category_enum`. Ordered: the first bucket whose keywords appear
# wins, so the narrow, high-consequence categories are checked before the
# broad ones (an APK-delivery scam is FILE_APK, not FINANCIAL_FRAUD).
CATEGORY_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("FILE_APK", ("apk", ".apk", "aplikasi undangan", "file undangan", "resi paket")),
    (
        "PHISHING_LINK",
        ("phishing", "tautan palsu", "situs palsu", "link palsu", "pendaftaran online", "login", "tautan pendaftaran"),
    ),
    (
        "FINANCIAL_FRAUD",
        (
            "penipuan",
            "bansos",
            "bantuan sosial",
            "uang",
            "rekening",
            "transfer",
            "investasi",
            "saldo",
            "hadiah",
            "undian",
            "pinjaman",
            "lowongan",
            "gaji",
        ),
    ),
    (
        "HEALTH_HOAX",
        (
            "kesehatan",
            "vaksin",
            "obat",
            "kanker",
            "virus",
            "penyakit",
            "dokter",
            "rumah sakit",
            "bpjs",
            "covid",
            "stunting",
        ),
    ),
)

_LABEL_PREFIX = re.compile(r"^\s*\[([^\]]{1,40})\]\s*")
# Sections are matched by class name, so the pattern is a template rather than
# a compiled regex. `</section>` is safe as a terminator here because the
# article body nests no sections inside these blocks.
_SECTION_TEMPLATE = r"<section[^>]*class=\"[^\"]*\b{cls}\b[^\"]*\"[^>]*>(.*?)</section>"
_LD_JSON = re.compile(
    r"<script[^>]*type=\"application/ld\+json\"[^>]*>(.*?)</script>", re.IGNORECASE | re.DOTALL
)
_TIME_TAG = re.compile(r"<time[^>]*datetime=\"([^\"]+)\"", re.IGNORECASE)
_CATEGORY_LINK = re.compile(r"href=\"/articles\?category=([^\"&]+)\"", re.IGNORECASE)
_LEADING_LABEL = re.compile(r"^\s*(Narasi|Penjelasan|Kesimpulan|Hasil Periksa fakta)\s*", re.IGNORECASE)


class TurnBackHoaxAdapter(FactCheckSourceAdapter):
    slug = "turnbackhoax"
    source_name = "TurnBackHoax"
    base_url = "https://turnbackhoax.id"
    is_trusted = True
    # MAFINDO is an IFCN-verified signatory and every article publishes its own
    # method and references — the highest score any source in this system
    # currently earns. Not 1.0: nothing is beyond correction.
    reliability = 0.95

    def __init__(self, settings: Settings | None = None, client: PoliteHttpClient | None = None) -> None:
        self._settings = settings or get_settings()
        self._client = client or PoliteHttpClient(self._settings)

    async def list_candidates(self, limit: int) -> list[SourceCandidate]:
        xml = await self._client.get_text(self._settings.turnbackhoax_feed_url)
        return parse_feed(xml)[:limit]

    async def fetch_record(self, candidate: SourceCandidate) -> NormalizedFactRecord:
        html = await self._client.get_text(candidate.url)
        return self._build_record(candidate, html)

    def _build_record(self, candidate: SourceCandidate, html: str) -> NormalizedFactRecord:
        claim_review = _extract_claim_review(html)
        sections = _extract_sections(html)

        # Claim: the article's own Narasi section, the feed excerpt second.
        # The feed's `description` is that same narrative truncated, so it is
        # a genuine fallback rather than a different field wearing the name.
        claim_text = sections.get("claim") or candidate.summary or ""
        explanation = sections.get("explanation") or ""

        verdict_label = (
            _rating_label(claim_review)
            or sections.get("verdict_label")
            or _title_label(candidate.title)
            or ""
        )
        published_at = (
            parse_iso_date(_claim_review_date(claim_review))
            or parse_iso_date(_first_match(_TIME_TAG, html))
            or candidate.published_at
        )
        site_category = _first_match(_CATEGORY_LINK, html) or ""

        raw_metadata: dict[str, Any] = {
            "source_slug": self.slug,
            "external_id": candidate.external_id,
            "feed_title": candidate.title,
            "site_category": site_category,
            "verdict_label": verdict_label,
            "claim_review": claim_review or None,
        }

        return NormalizedFactRecord(
            source_slug=self.slug,
            source_name=self.source_name,
            external_id=candidate.external_id,
            source_url=canonical_url(candidate.url),
            # The `[SALAH]` prefix stays: operators read these titles in the
            # Knowledge Base screen, and it is how MAFINDO's own readers
            # recognise a ruling at a glance.
            title=clamp_title(candidate.title),
            claim_text=claim_text,
            fact_explanation=explanation,
            verdict=map_verdict(verdict_label),
            category=map_category(candidate.title, claim_text, site_category),
            published_at=published_at,
            updated_at=published_at,
            raw_metadata=raw_metadata,
        )


def parse_feed(xml: str) -> list[SourceCandidate]:
    """RSS 2.0 → candidates. Raises `SourceParseError` on malformed XML.

    Items missing a link or an id are dropped with a warning rather than
    failing the run: one broken entry in a feed of ten is a source-side
    glitch, not a reason to lose the other nine.
    """
    try:
        root = ElementTree.fromstring(xml.strip())
    except ElementTree.ParseError as exc:
        raise SourceParseError(f"malformed RSS: {exc}") from exc

    items = root.findall(".//item")
    if not items and root.find(".//channel") is None:
        raise SourceParseError("response is not an RSS document")

    candidates: list[SourceCandidate] = []
    for item in items:
        link = (item.findtext("link") or "").strip()
        guid = (item.findtext("guid") or "").strip()
        title = (item.findtext("title") or "").strip()
        external_id = guid or (canonical_url(link) if link else "")
        if not link or not external_id or not title:
            logger.warning(
                "skipping malformed feed item",
                extra={"has_link": bool(link), "has_id": bool(external_id), "has_title": bool(title)},
            )
            continue
        candidates.append(
            SourceCandidate(
                external_id=external_id,
                url=link,
                title=title,
                summary=html_to_text(item.findtext("description") or ""),
                published_at=parse_iso_date(item.findtext("pubDate")),
                raw={"guid": guid},
            )
        )
    return candidates


def map_verdict(label: str) -> str:
    """MAFINDO ruling → `verdict_enum`. Unknown label → UNVERIFIED."""
    text = (label or "").strip().casefold()
    if not text:
        return "UNVERIFIED"
    if text in VERDICT_MAP:
        return VERDICT_MAP[text]
    # Labels arrive as phrases too ("Konten yang Menyesatkan"); longest key
    # first so "konten yang menyesatkan" is not shadowed by "menyesatkan".
    for key in sorted(VERDICT_MAP, key=len, reverse=True):
        if key in text:
            return VERDICT_MAP[key]
    return "UNVERIFIED"


def map_category(title: str, claim_text: str, site_category: str = "") -> str:
    """Keyword mapping onto `category_enum`.

    The source's own categories ("Other", "Politik", "Lowongan") do not line
    up with the enum, so they are one signal among the text rather than the
    decision. Nothing matching lands in GENERAL_NEWS, which is the honest
    answer, not a fallback dressed as a classification.
    """
    haystack = " ".join((title, claim_text, site_category)).casefold()
    for category, keywords in CATEGORY_KEYWORDS:
        if any(keyword in haystack for keyword in keywords):
            return category
    return DEFAULT_CATEGORY


class _TextExtractor(HTMLParser):
    """Tags out, text in, block boundaries kept as whitespace."""

    _BLOCK_TAGS = frozenset({"p", "div", "br", "li", "tr", "section", "h1", "h2", "h3", "h4", "strong"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._chunks: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style"}:
            self._skip_depth += 1
        elif tag in self._BLOCK_TAGS:
            self._chunks.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"} and self._skip_depth:
            self._skip_depth -= 1
        elif tag in self._BLOCK_TAGS:
            self._chunks.append(" ")

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self._chunks.append(data)

    @property
    def text(self) -> str:
        return re.sub(r"\s+", " ", "".join(self._chunks)).strip()


def html_to_text(fragment: str) -> str:
    """Readable plain text from an HTML fragment.

    Feed descriptions arrive escaped, so they are unescaped once before
    parsing; a stray malformed tag degrades to text instead of raising,
    because a half-readable claim is still worth ingesting.
    """
    if not fragment:
        return ""
    parser = _TextExtractor()
    try:
        parser.feed(unescape(fragment))
        parser.close()
    except Exception:  # noqa: BLE001 — html.parser is lenient, but never fatal here
        logger.warning("html parse degraded to tag stripping")
        return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", unescape(fragment))).strip()
    return parser.text


def _extract_sections(html: str) -> dict[str, str]:
    """Claim / explanation / ruling from the article's own section classes."""
    sections: dict[str, str] = {}

    claim = _section_text(html, "article-origin")
    if claim:
        sections["claim"] = claim

    # Penjelasan and Kesimpulan are two sections sharing one class. Both are
    # the debunk, and the conclusion is the part the LLM will quote, so they
    # are joined rather than one being picked.
    explanation_parts = [_clean_section(match) for match in _findall_sections(html, "article-explanation")]
    explanation = " ".join(part for part in explanation_parts if part).strip()
    if explanation:
        sections["explanation"] = explanation

    ruling = _section_text(html, "article-factcheck")
    if ruling:
        sections["verdict_label"] = ruling.split(":")[-1].strip() if ":" in ruling else ruling

    return sections


def _findall_sections(html: str, class_name: str) -> list[str]:
    return re.findall(_SECTION_TEMPLATE.format(cls=re.escape(class_name)), html, re.IGNORECASE | re.DOTALL)


def _section_text(html: str, class_name: str) -> str:
    matches = _findall_sections(html, class_name)
    return _clean_section(matches[0]) if matches else ""


def _clean_section(fragment: str) -> str:
    return _LEADING_LABEL.sub("", html_to_text(fragment)).strip()


def _extract_claim_review(html: str) -> dict[str, Any]:
    """The page's `ClaimReview` JSON-LD, or `{}`.

    Unparseable JSON-LD is not an error: the HTML fallbacks cover the same
    fields, and a source-side typo in a `<script>` block should not cost us
    the article.
    """
    for raw in _LD_JSON.findall(html):
        try:
            data = json.loads(raw.strip())
        except (ValueError, TypeError):
            logger.warning("unparseable ld+json block skipped")
            continue
        for block in data if isinstance(data, list) else [data]:
            if isinstance(block, dict) and "claimreview" in str(block.get("@type", "")).casefold():
                return block
    return {}


def _rating_label(claim_review: dict[str, Any]) -> str:
    rating = claim_review.get("reviewRating")
    if isinstance(rating, dict):
        return str(rating.get("alternateName") or "").strip()
    return ""


def _claim_review_date(claim_review: dict[str, Any]) -> str:
    for key in ("datePublished", "dateModified"):
        value = claim_review.get(key)
        if value:
            return str(value)
    reviewed = claim_review.get("itemReviewed")
    if isinstance(reviewed, dict) and reviewed.get("datePublished"):
        return str(reviewed["datePublished"])
    return ""


def _title_label(title: str) -> str:
    """`[SALAH] Judul` → `SALAH`."""
    match = _LABEL_PREFIX.match(title or "")
    return match.group(1).strip() if match else ""


def _first_match(pattern: re.Pattern[str], text: str) -> str:
    match = pattern.search(text)
    return match.group(1).strip() if match else ""
