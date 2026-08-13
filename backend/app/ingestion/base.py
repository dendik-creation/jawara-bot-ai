"""The source-adapter boundary.

Two calls, deliberately split:

    list_candidates()   cheap — one feed/index request, no per-article cost
    fetch_record(c)     expensive — one request per article

The pipeline filters candidates against what it already stored *between*
those two calls, so a scheduled run that finds nothing new costs exactly one
HTTP request. That is the whole reason the interface is not a single
`fetch_all()`: incremental behaviour has to be expressible without the
adapter knowing what the database contains.

Normalization, verdict/category mapping and every HTML quirk stay behind
this boundary. What comes out is a `NormalizedFactRecord`, which is already
in the vocabulary `fact_items` speaks.
"""

import hashlib
import re
import unicodedata
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, ClassVar
from urllib.parse import urlsplit, urlunsplit

# `fact_items.category`/`verdict` — 001_init_schema.sql's enums. An adapter
# maps the source's own vocabulary onto these; there is no "other" bucket, so
# a mapping that fails falls back to the honest defaults below.
Category = str
Verdict = str

DEFAULT_CATEGORY = "GENERAL_NEWS"
DEFAULT_VERDICT = "UNVERIFIED"

VALID_CATEGORIES = frozenset({"HEALTH_HOAX", "FINANCIAL_FRAUD", "GENERAL_NEWS", "PHISHING_LINK", "FILE_APK"})
VALID_VERDICTS = frozenset({"HOAX", "FACT", "MISLEADING", "UNVERIFIED"})

# `fact_items.title` is VARCHAR(255); truncating here beats a 22001 from
# Postgres in the middle of a run.
TITLE_MAX_LENGTH = 255


class IngestionError(Exception):
    """Base for every adapter-level failure."""


class SourceFetchError(IngestionError):
    """The source could not be reached, or answered with an error status.

    `retryable` distinguishes "come back later" (timeout, 429, 5xx) from
    "this will fail identically next time" (403, 404). The pipeline records
    both; Celery only retries the first kind.
    """

    def __init__(self, message: str, *, status_code: int | None = None, retryable: bool = True) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retryable = retryable


class SourceParseError(IngestionError):
    """The response arrived but could not be understood (malformed feed/HTML)."""


@dataclass(frozen=True)
class SourceCandidate:
    """One entry from the source's index/feed, before the detail fetch.

    Carries only what an index page can be trusted to have. `external_id` is
    the source's own stable identifier — the primary dedup key.
    """

    external_id: str
    url: str
    title: str
    summary: str = ""
    published_at: datetime | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class NormalizedFactRecord:
    """A fact-check in `fact_items` vocabulary, ready to persist."""

    source_slug: str
    source_name: str
    external_id: str
    source_url: str
    title: str
    claim_text: str
    fact_explanation: str
    verdict: Verdict = DEFAULT_VERDICT
    category: Category = DEFAULT_CATEGORY
    published_at: datetime | None = None
    updated_at: datetime | None = None
    raw_metadata: dict[str, Any] = field(default_factory=dict)

    def missing_fields(self) -> list[str]:
        """Fields without which the record is not ingestible.

        `fact_explanation` is required, not optional-with-a-default: a fact
        item whose explanation is empty would still be embedded and still be
        retrieved, and the LLM would then cite a debunk that says nothing.
        Better rejected and counted than silently thin.
        """
        missing = [
            name
            for name in ("external_id", "source_url", "title", "claim_text", "fact_explanation")
            if not (getattr(self, name) or "").strip()
        ]
        if self.verdict not in VALID_VERDICTS:
            missing.append("verdict")
        if self.category not in VALID_CATEGORIES:
            missing.append("category")
        return missing

    def fingerprint(self) -> str:
        """Deterministic content identity.

        Used two ways: as the dedup key of last resort for sources with no
        stable id, and as the change detector for sources that have one —
        same `external_id`, different fingerprint means the source edited the
        article, which is an update rather than a duplicate. Whitespace and
        Unicode form are normalized first so a cosmetic re-render of the same
        text does not read as a content change.
        """
        parts = [self.source_slug, self.title, self.claim_text, self.fact_explanation, self.verdict]
        blob = "\x1f".join(_normalize_text(part) for part in parts)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()


class FactCheckSourceAdapter(ABC):
    """One external fact-check source.

    Subclasses declare their identity as class attributes so the pipeline can
    provision the `fact_sources` row without instantiating anything
    source-specific, and implement the two fetch calls.
    """

    slug: ClassVar[str]
    source_name: ClassVar[str]
    base_url: ClassVar[str]
    is_trusted: ClassVar[bool] = True
    # Seeds `fact_sources.reliability_score` the first time this source is
    # provisioned, and only then — an operator's later judgement about a
    # publisher must not be overwritten by a redeploy of the adapter.
    reliability: ClassVar[float] = 0.80

    @abstractmethod
    async def list_candidates(self, limit: int) -> list[SourceCandidate]:
        """Newest-first index entries. Raises `SourceFetchError`/`SourceParseError`."""

    @abstractmethod
    async def fetch_record(self, candidate: SourceCandidate) -> NormalizedFactRecord:
        """Hydrate one candidate into a normalized record."""

    async def aclose(self) -> None:
        """Release per-run resources. Overridden by adapters holding a client."""


def canonical_url(url: str) -> str:
    """Strip the parts of a URL that do not identify the document.

    Query strings on these sites are tracking/campaign parameters and
    fragments are in-page anchors; leaving either in would let the same
    article arrive twice under two "different" URLs.
    """
    parts = urlsplit(url.strip())
    netloc = parts.netloc.lower()
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), netloc, path, "", ""))


def parse_iso_date(value: str | None) -> datetime | None:
    """`2026-08-13` / `2026-08-13T04:05:06+07:00` → aware UTC datetime, or None.

    Naive values are read as UTC rather than guessed at: a fact-check's
    freshness is measured in days, and inventing a timezone to gain hours
    would be a fabricated precision.
    """
    if not value:
        return None
    text = value.strip().replace("Z", "+00:00")
    for candidate in (text, text[:10]):
        try:
            parsed = datetime.fromisoformat(candidate)
        except ValueError:
            continue
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return None


def clamp_title(title: str) -> str:
    title = title.strip()
    return title if len(title) <= TITLE_MAX_LENGTH else title[: TITLE_MAX_LENGTH - 1].rstrip() + "…"


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", value or "")).strip().casefold()
