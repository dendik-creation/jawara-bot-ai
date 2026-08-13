"""Re-ranking retrieved knowledge by source reliability and freshness.

Cosine similarity answers "which stored claim is worded most like this one".
It does not answer "which of these should the user be told about". Two matches
can be equally similar while one comes from a fact-check organisation and was
published yesterday and the other from a low-trust source two years ago. That
choice is what this module makes.

    final = similarity × reliability_factor × recency_factor

Both factors live in `[1 - weight, 1]`, so a weight of 0 disables that signal
exactly and no factor can ever *raise* a score above its raw similarity —
re-ranking only ever expresses doubt, never confidence the embedder did not
find. Multiplicative and monotone, so the ordering it produces can be
explained to an operator in one sentence.

Membership is deliberately not changed. Qdrant has already applied the
documented `score_threshold` to the raw similarity
(03_Database/02_VectorDB_Specifications.md §3); re-ranking reorders that set
and cuts it to `top_k`. Dropping a match whose *reranked* score fell below the
threshold would quietly redefine a contract that lives in another document,
and `score` — the number the audit row and the operator UI show — stays the
true cosine similarity throughout. The derived numbers ride alongside it as
`rerank_score`, `reliability`, and `age_days`.

Overfetch is what makes this meaningful: retrieving exactly `top_k` and then
reordering them cannot promote the trustworthy fourth match over the shaky
third. The endpoint asks Qdrant for `top_k × overfetch` and trims afterwards.
"""

from datetime import datetime, timezone
from typing import Any

# Facts that predate the reliability column (or came from a source nobody has
# scored yet) are treated as ordinary, not as suspect: an unscored source is an
# absence of information, and penalising it would silently demote the entire
# hand-curated knowledge base the day this shipped.
NEUTRAL_RELIABILITY = 1.0


def rerank(
    matches: list[dict[str, Any]],
    *,
    top_k: int,
    reliability_weight: float,
    recency_weight: float,
    half_life_days: float,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Reorder `matches` newest-and-most-trusted-first and cut to `top_k`.

    Input dicts are not mutated; each output carries the extra ranking fields.
    A stable sort is used, so matches that tie on the final score keep Qdrant's
    own similarity ordering rather than shuffling between identical requests.
    """
    if not matches:
        return []

    now = now or datetime.now(timezone.utc)
    scored: list[dict[str, Any]] = []

    for match in matches:
        similarity = float(match.get("score") or 0.0)
        reliability = _reliability_of(match)
        age_days = _age_days(match, now)

        reliability_factor = 1.0 - reliability_weight * (1.0 - reliability)
        recency_factor = 1.0 - recency_weight * (1.0 - _recency(age_days, half_life_days))

        scored.append(
            {
                **match,
                "reliability": round(reliability, 4),
                "age_days": None if age_days is None else round(age_days, 2),
                "reliability_factor": round(reliability_factor, 4),
                "recency_factor": round(recency_factor, 4),
                "rerank_score": round(similarity * reliability_factor * recency_factor, 6),
            }
        )

    scored.sort(key=lambda item: item["rerank_score"], reverse=True)
    return scored[:top_k]


def _reliability_of(match: dict[str, Any]) -> float:
    raw = match.get("source_reliability")
    if raw is None or raw == "":
        return NEUTRAL_RELIABILITY
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return NEUTRAL_RELIABILITY
    return min(max(value, 0.0), 1.0)


def _age_days(match: dict[str, Any], now: datetime) -> float | None:
    """Age from the source's publication date.

    `published_at` first, `updated_at` only as a fallback: publication is a
    fact about the claim, while `updated_at` is a fact about our own row and
    would make every re-sync look like fresh news. Neither present → unknown,
    which the caller treats as neutral rather than as old.
    """
    for key in ("published_at", "updated_at"):
        parsed = _parse_timestamp(match.get(key))
        if parsed is not None:
            # Clamped at zero: a source dated tomorrow (timezone slop, a typo in
            # their CMS) must not earn a bonus over one dated today.
            return max((now - parsed).total_seconds() / 86400.0, 0.0)
    return None


def _recency(age_days: float | None, half_life_days: float) -> float:
    """Exponential decay in `(0, 1]`. Unknown age is neutral (`1.0`).

    Half-life rather than a cliff: misinformation does not become irrelevant on
    a particular day, it fades. At `half_life_days` the factor is 0.5, at twice
    that 0.25, and it never reaches zero — an old fact-check that is still the
    only match must remain retrievable.
    """
    if age_days is None or half_life_days <= 0:
        return 1.0
    return 0.5 ** (age_days / half_life_days)


def _parse_timestamp(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    for candidate in (text, text[:10]):
        try:
            parsed = datetime.fromisoformat(candidate)
        except ValueError:
            continue
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return None
