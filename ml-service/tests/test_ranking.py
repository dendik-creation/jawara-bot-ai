"""Re-ranking: source reliability and freshness on top of cosine similarity.

The properties that matter here are the ones an operator would be told about:
weights of 0 change nothing, re-ranking only ever demotes, membership never
changes, and the raw similarity survives untouched into the audit trail.
"""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import app
from app.rag.ranking import rerank

NOW = datetime(2026, 8, 13, tzinfo=timezone.utc)
HEADERS = {"X-Internal-Api-Key": get_settings().ml_service_api_key}


def _match(fact_id: str, score: float, reliability=None, published_at=None, **extra) -> dict:
    return {
        "fact_item_id": fact_id,
        "title": f"fakta {fact_id}",
        "score": score,
        "source_reliability": reliability,
        "published_at": published_at,
        **extra,
    }


def _rerank(matches, *, top_k=3, reliability_weight=0.4, recency_weight=0.25, half_life_days=180.0):
    return rerank(
        matches,
        top_k=top_k,
        reliability_weight=reliability_weight,
        recency_weight=recency_weight,
        half_life_days=half_life_days,
        now=NOW,
    )


def _iso(days_ago: float) -> str:
    return (NOW - timedelta(days=days_ago)).isoformat()


# --------------------------------------------------------------------------
# Ordering
# --------------------------------------------------------------------------


def test_reliability_breaks_a_similarity_tie():
    ranked = _rerank(
        [
            _match("shaky", 0.90, reliability=0.30, published_at=_iso(1)),
            _match("solid", 0.90, reliability=0.95, published_at=_iso(1)),
        ]
    )

    assert [m["fact_item_id"] for m in ranked] == ["solid", "shaky"]


def test_recency_breaks_a_tie_between_equally_trusted_sources():
    ranked = _rerank(
        [
            _match("old", 0.90, reliability=0.9, published_at=_iso(720)),
            _match("fresh", 0.90, reliability=0.9, published_at=_iso(1)),
        ]
    )

    assert [m["fact_item_id"] for m in ranked] == ["fresh", "old"]


def test_a_trustworthy_fourth_match_can_overtake_a_shaky_third():
    """The whole reason retrieval overfetches — without this, re-ranking a
    list of exactly `top_k` could never change which facts the user is told."""
    ranked = _rerank(
        [
            _match("a", 0.95, reliability=0.95, published_at=_iso(5)),
            _match("b", 0.93, reliability=0.95, published_at=_iso(5)),
            _match("junk", 0.92, reliability=0.05, published_at=_iso(900)),
            _match("good", 0.88, reliability=0.98, published_at=_iso(2)),
        ],
        top_k=3,
    )

    assert [m["fact_item_id"] for m in ranked] == ["a", "b", "good"]


def test_between_equally_trusted_fresh_sources_similarity_decides():
    """Weighting adds a signal; it does not replace the embedder. With the
    trust and freshness factors equal, the ordering is exactly Qdrant's."""
    ranked = _rerank(
        [
            _match("weaker", 0.83, reliability=0.95, published_at=_iso(1)),
            _match("stronger", 0.95, reliability=0.95, published_at=_iso(1)),
        ]
    )

    assert [m["fact_item_id"] for m in ranked] == ["stronger", "weaker"]


def test_a_pristine_fresh_source_can_outrank_a_closer_but_older_mid_trust_match():
    """Intended, and worth stating plainly: every candidate here already
    cleared the 0.80 similarity threshold, so they are all plausibly *the same
    claim*. Among those, who published it and when is the better tiebreaker
    than a few hundredths of cosine distance.

    0.95 × 0.8 (reliability 0.5) × 0.80 (400 days old) = 0.61
    0.81 × 1.0 × 1.0                                   = 0.81
    """
    ranked = _rerank(
        [
            _match("closer_but_stale", 0.95, reliability=0.5, published_at=_iso(400)),
            _match("pristine_and_fresh", 0.81, reliability=1.0, published_at=_iso(0)),
        ]
    )

    assert ranked[0]["fact_item_id"] == "pristine_and_fresh"


def test_ties_keep_qdrant_ordering():
    ranked = _rerank([_match("first", 0.9), _match("second", 0.9)])

    assert [m["fact_item_id"] for m in ranked] == ["first", "second"]


# --------------------------------------------------------------------------
# Bounds and invariants
# --------------------------------------------------------------------------


def test_zero_weights_leave_the_score_untouched():
    ranked = _rerank(
        [_match("x", 0.9, reliability=0.1, published_at=_iso(2000))],
        reliability_weight=0.0,
        recency_weight=0.0,
    )

    assert ranked[0]["rerank_score"] == pytest.approx(0.9)


def test_reranking_never_raises_a_score_above_its_similarity():
    ranked = _rerank(
        [
            _match("perfect", 0.80, reliability=1.0, published_at=_iso(0)),
            _match("mid", 0.80, reliability=0.5, published_at=_iso(180)),
        ]
    )

    for match in ranked:
        assert match["rerank_score"] <= match["score"] + 1e-9


def test_the_raw_similarity_is_preserved_for_the_audit_row():
    ranked = _rerank([_match("x", 0.9123, reliability=0.2, published_at=_iso(500))])

    assert ranked[0]["score"] == 0.9123
    assert ranked[0]["rerank_score"] < 0.9123


def test_membership_is_never_changed_only_order_and_count():
    matches = [_match(str(i), 0.9 - i / 100, reliability=0.1) for i in range(5)]

    ranked = _rerank(matches, top_k=5)

    assert {m["fact_item_id"] for m in ranked} == {m["fact_item_id"] for m in matches}


def test_top_k_is_respected():
    assert len(_rerank([_match(str(i), 0.9) for i in range(10)], top_k=2)) == 2


def test_empty_input_stays_empty():
    assert _rerank([]) == []


# --------------------------------------------------------------------------
# Missing and malformed metadata
# --------------------------------------------------------------------------


def test_facts_without_a_reliability_score_are_neutral_not_suspect():
    """Everything already in the knowledge base predates the column; treating
    an absent score as 0 would have demoted the whole curated KB on deploy."""
    ranked = _rerank([_match("legacy", 0.9, published_at=_iso(0))])

    assert ranked[0]["reliability"] == 1.0
    assert ranked[0]["rerank_score"] == pytest.approx(0.9)


def test_facts_without_any_date_are_neutral_not_ancient():
    ranked = _rerank([_match("undated", 0.9, reliability=1.0)])

    assert ranked[0]["age_days"] is None
    assert ranked[0]["rerank_score"] == pytest.approx(0.9)


def test_updated_at_is_the_fallback_when_publication_is_unknown():
    ranked = _rerank([_match("x", 0.9, reliability=1.0, updated_at=_iso(180))])

    assert ranked[0]["age_days"] == pytest.approx(180.0)


def test_a_garbled_reliability_value_does_not_break_the_ranking():
    ranked = _rerank([_match("x", 0.9, reliability="not-a-number", published_at="yesterday")])

    assert ranked[0]["reliability"] == 1.0
    assert ranked[0]["age_days"] is None


def test_out_of_range_reliability_is_clamped():
    ranked = _rerank([_match("high", 0.9, reliability=5.0), _match("low", 0.9, reliability=-3.0)])

    assert ranked[0]["reliability"] == 1.0
    assert ranked[1]["reliability"] == 0.0


def test_a_future_dated_source_earns_no_bonus():
    ranked = _rerank([_match("future", 0.9, reliability=1.0, published_at=_iso(-30))])

    assert ranked[0]["age_days"] == 0.0
    assert ranked[0]["rerank_score"] == pytest.approx(0.9)


def test_half_life_halves_the_recency_factor():
    ranked = _rerank(
        [_match("x", 1.0, reliability=1.0, published_at=_iso(180))],
        reliability_weight=0.0,
        recency_weight=1.0,
        half_life_days=180.0,
    )

    assert ranked[0]["recency_factor"] == pytest.approx(0.5)


def test_an_old_fact_never_decays_to_zero():
    """A ten-year-old debunk of a recirculating hoax must stay retrievable."""
    ranked = _rerank(
        [_match("ancient", 0.9, reliability=1.0, published_at=_iso(3650))],
        recency_weight=1.0,
    )

    assert ranked[0]["rerank_score"] > 0


# --------------------------------------------------------------------------
# Endpoint integration
# --------------------------------------------------------------------------


class RerankRepository:
    def __init__(self, hits):
        self.hits = hits
        self.last_query = {}

    async def search(self, vector, category=None, top_k=None, score_threshold=None):
        self.last_query = {"category": category, "top_k": top_k, "score_threshold": score_threshold}
        return self.hits

    async def health(self):
        return {"collection": "test", "vector_size": 1536, "points_count": len(self.hits)}

    async def close(self):
        return None


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


def test_rag_query_returns_reranked_matches_with_their_ranking_fields(client):
    client.app.state.qdrant = RerankRepository(
        [
            _match("junk", 0.94, reliability=0.05, published_at=_iso(900)),
            _match("good", 0.90, reliability=0.95, published_at=_iso(1)),
        ]
    )

    body = client.post(
        "/v1/rag-query",
        json={"request_id": "req-1", "payload": {"query": "klaim apa pun"}, "metadata": {}},
        headers=HEADERS,
    ).json()

    result = body["result"]
    assert result["reranked"] is True
    assert result["candidates_considered"] == 2
    assert [m["fact_item_id"] for m in result["matches"]] == ["good", "junk"]
    assert result["matches"][0]["rerank_score"] < result["matches"][0]["score"] + 1e-9
    # Confidence is the raw similarity of the returned top match, not the
    # discounted one — the audit row records how well retrieval actually matched.
    assert body["confidence"] == 0.90


def test_rerank_can_be_disabled_per_request_for_raw_retrieval(client):
    client.app.state.qdrant = RerankRepository(
        [
            _match("junk", 0.94, reliability=0.05, published_at=_iso(900)),
            _match("good", 0.90, reliability=0.95, published_at=_iso(1)),
        ]
    )

    body = client.post(
        "/v1/rag-query",
        json={"request_id": "req-1", "payload": {"query": "klaim apa pun", "rerank": False}, "metadata": {}},
        headers=HEADERS,
    ).json()

    assert [m["fact_item_id"] for m in body["result"]["matches"]] == ["junk", "good"]
    assert "rerank_score" not in body["result"]["matches"][0]
