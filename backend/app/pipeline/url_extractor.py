"""URL extraction from free-text WhatsApp messages ([[Implement URL Extractor]]).

Feeds two consumers: the intent router's `PHISHING_LINK` signal, and the URL
safety scanners (Safe Browsing + VirusTotal).

Scope note from the task: `.apk` files and bank-account / e-wallet numbers are
*not* extracted here. Financial-fraud verification is Post-MVP and APK static
analysis is Optional/Future — attachment detection lives in the intent router,
which reads the WAHA payload rather than the message body.
"""

import re
from dataclasses import dataclass
from urllib.parse import urlsplit

# Link shorteners hide the destination, so the pipeline has to treat them as an
# unknown-until-checked indicator rather than judging the visible domain.
SHORTENER_DOMAINS: frozenset[str] = frozenset(
    {
        "bit.ly",
        "bitly.com",
        "tinyurl.com",
        "t.co",
        "goo.gl",
        "ow.ly",
        "is.gd",
        "buff.ly",
        "cutt.ly",
        "rebrand.ly",
        "rb.gy",
        "shorturl.at",
        "s.id",
        "bit.do",
        "tiny.cc",
        "gg.gg",
        "urlz.fr",
        "shorte.st",
        "adf.ly",
        "v.gd",
        "t.ly",
        "lnkd.in",
        "trib.al",
        "chilp.it",
        "clck.ru",
        "u.to",
    }
)

# Bare-domain matching is restricted to this TLD list on purpose. Matching every
# `word.word` pattern turns Indonesian sentences into false URLs ("dll.jadi").
_TLDS = (
    "com|net|org|info|biz|id|co|xyz|top|online|site|shop|store|click|link|live|"
    "app|dev|io|me|cc|tv|ru|cn|tk|ml|ga|cf|gq|fun|icu|vip|work|website|space|pro"
)

_SCHEME_URL = re.compile(r"https?://[^\s<>\"'`]+", re.IGNORECASE)
_WWW_URL = re.compile(r"\bwww\.[^\s<>\"'`]+", re.IGNORECASE)
# Shorteners get their own exact-match pattern. Their TLDs (`ly`, `gd`, `do`,
# `to`) are ordinary Indonesian words with a dot in front, so adding them to the
# general TLD list would turn "coba.in" and "silakan.do" into URLs — but a bare
# `bit.ly/x` is exactly the link that must not be missed.
_SHORTENER_URL = re.compile(
    r"\b(?:" + "|".join(re.escape(domain) for domain in sorted(SHORTENER_DOMAINS)) + r")"
    r"(?:/[^\s<>\"'`]*)?",
    re.IGNORECASE,
)
_BARE_URL = re.compile(
    rf"\b(?:[a-z0-9](?:[a-z0-9-]{{0,61}}[a-z0-9])?\.)+(?:{_TLDS})"
    r"(?:\.[a-z]{2})?(?:/[^\s<>\"'`]*)?\b",
    re.IGNORECASE,
)

# Defanged links pasted from security advisories or typed to dodge filters.
_DEFANG_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"h(?:xx|X X)p(s?)://", re.IGNORECASE), r"http\1://"),
    (re.compile(r"\[\s*\.\s*\]"), "."),
    (re.compile(r"\(\s*\.\s*\)"), "."),
    (re.compile(r"\{\s*\.\s*\}"), "."),
    (re.compile(r"\s+dot\s+", re.IGNORECASE), "."),
)

# Sentence punctuation that WhatsApp users put straight after a link.
_TRAILING = ".,;:!?'\"”’)»]}>*_~"

_IPV4_HOST = re.compile(r"^\d{1,3}(?:\.\d{1,3}){3}$")


@dataclass(frozen=True)
class ExtractedURL:
    """One URL found in a message body."""

    url: str
    raw: str
    domain: str
    is_shortlink: bool
    is_ip_host: bool
    # True when the *message* used defanged link syntax (`hxxp`, `[.]`). Tracked
    # per URL because that is where downstream scoring reads it, but the signal
    # is message-level: someone deliberately obscuring a link is suspicious
    # regardless of which link it was.
    was_defanged: bool

    @property
    def registrable_domain(self) -> str:
        """Best-effort eTLD+1 — good enough for blocklists and cache keys.

        No PSL dependency: `.co.id`/`.go.id`-style two-label suffixes are handled
        by the special case below, everything else takes the last two labels.
        """
        parts = self.domain.split(".")
        if len(parts) <= 2:
            return self.domain
        if parts[-2] in {"co", "or", "go", "ac", "sch", "web", "my", "net", "com"} and len(parts[-1]) == 2:
            return ".".join(parts[-3:])
        return ".".join(parts[-2:])


def _strip_trailing(candidate: str) -> str:
    """Trim sentence punctuation, keeping balanced parentheses inside the URL."""
    while candidate and candidate[-1] in _TRAILING:
        if candidate[-1] == ")" and candidate.count("(") > candidate.count(")"):
            break
        candidate = candidate[:-1]
    return candidate


def _defang(text: str) -> tuple[str, bool]:
    changed = False
    for pattern, replacement in _DEFANG_PATTERNS:
        text, count = pattern.subn(replacement, text)
        changed = changed or bool(count)
    return text, changed


def _build(candidate: str, was_defanged: bool) -> ExtractedURL | None:
    raw = candidate
    candidate = _strip_trailing(candidate)
    if not candidate:
        return None

    url = candidate if "://" in candidate else f"http://{candidate}"
    host = (urlsplit(url).hostname or "").lower()
    if not host or "." not in host:
        return None

    domain = host[4:] if host.startswith("www.") else host
    return ExtractedURL(
        url=url,
        raw=raw,
        domain=domain,
        is_shortlink=domain in SHORTENER_DOMAINS,
        is_ip_host=bool(_IPV4_HOST.match(domain)),
        was_defanged=was_defanged,
    )


def extract_urls(text: str | None) -> list[ExtractedURL]:
    """Every URL in `text`, in order of appearance, de-duplicated.

    Scheme-qualified links win over bare domains covering the same span, so
    `https://bit.ly/x` is reported once rather than twice.
    """
    if not text:
        return []

    text, was_defanged = _defang(text)

    spans: list[tuple[int, int, str]] = []
    for pattern in (_SCHEME_URL, _WWW_URL, _SHORTENER_URL, _BARE_URL):
        for match in pattern.finditer(text):
            start, end = match.span()
            if any(start >= s and end <= e for s, e, _ in spans):
                continue
            spans.append((start, end, match.group(0)))

    spans.sort(key=lambda item: item[0])

    found: list[ExtractedURL] = []
    seen: set[str] = set()
    for _, _, candidate in spans:
        extracted = _build(candidate, was_defanged)
        if extracted is None or extracted.url in seen:
            continue
        seen.add(extracted.url)
        found.append(extracted)
    return found


def has_shortlink(urls: list[ExtractedURL]) -> bool:
    return any(url.is_shortlink for url in urls)
