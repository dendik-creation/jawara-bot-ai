"""Source reliability against a live PostgreSQL.

The column has a default, a CHECK constraint and a denormalisation path into
Qdrant payloads; all three are database facts a mocked connection could only
pretend to have. Skipped when Postgres is unreachable, same as the other
integration suites.
"""

import asyncpg
import pytest

from app.core.config import Settings
from app.services import knowledge

pytestmark = pytest.mark.integration

NAME = "Pytest Reliability Source"


@pytest.fixture
def reliability_settings(postgres_dsn):
    return Settings(database_url=postgres_dsn)


@pytest.fixture
async def source(reliability_settings):
    """A throwaway source with one fact, cleaned up afterwards."""
    conn = await asyncpg.connect(reliability_settings.database_url)
    source_id = await conn.fetchval(
        "INSERT INTO fact_sources (name, base_url, is_trusted) VALUES ($1, $2, TRUE) RETURNING id",
        NAME,
        "https://reliability.test",
    )
    fact_id = await conn.fetchval(
        """
        INSERT INTO fact_items (source_id, category, title, claim_summary, fact_explanation,
                                verdict, source_url, published_at)
        VALUES ($1, 'GENERAL_NEWS', 'judul', 'klaim', 'penjelasan', 'HOAX',
                'https://reliability.test/1', CURRENT_TIMESTAMP - INTERVAL '3 days')
        RETURNING id
        """,
        source_id,
    )
    try:
        yield conn, source_id, str(fact_id)
    finally:
        await conn.execute("DELETE FROM fact_items WHERE source_id = $1", source_id)
        await conn.execute("DELETE FROM fact_sources WHERE id = $1", source_id)
        await conn.close()


async def test_existing_sources_get_the_neutral_default(source):
    conn, source_id, _ = source

    score = await conn.fetchval("SELECT reliability_score FROM fact_sources WHERE id = $1", source_id)

    # 0.80, not 1.0: unscored sits just below explicitly vouched for, and no
    # existing row changes rank relative to another on the day this lands.
    assert float(score) == 0.80


async def test_the_score_is_constrained_to_zero_one(source):
    conn, source_id, _ = source

    for invalid in (-0.01, 1.01):
        with pytest.raises(asyncpg.CheckViolationError):
            await conn.execute(
                "UPDATE fact_sources SET reliability_score = $2 WHERE id = $1", source_id, invalid
            )


async def test_update_reports_the_previous_score_and_what_is_now_stale(source, reliability_settings):
    conn, source_id, fact_id = source
    await conn.execute("UPDATE fact_items SET synced_at = CURRENT_TIMESTAMP WHERE id = $1::uuid", fact_id)

    result = await knowledge.apply_fact_source_action(
        source_id, reliability_score=0.35, settings=reliability_settings
    )

    assert result["reliability_score"] == 0.35
    assert result["previous_reliability"] == 0.80
    # The score is denormalised into Qdrant payloads at sync time, so this
    # count is the operator's warning that retrieval has not changed yet.
    assert result["stale_in_qdrant"] == 1


async def test_update_rejects_an_out_of_range_score_before_touching_the_database(reliability_settings):
    with pytest.raises(ValueError, match="between 0 and 1"):
        await knowledge.apply_fact_source_action(1, reliability_score=2.0, settings=reliability_settings)


async def test_update_requires_at_least_one_field(reliability_settings):
    with pytest.raises(ValueError, match="at least one"):
        await knowledge.apply_fact_source_action(1, settings=reliability_settings)


async def test_unknown_source_is_none_not_an_error(reliability_settings):
    assert (
        await knowledge.apply_fact_source_action(
            -1, reliability_score=0.5, settings=reliability_settings
        )
        is None
    )


async def test_sync_payload_carries_the_score_and_publication_date(source, reliability_settings):
    """This is the only route the ranker's inputs travel: ml-service has no
    database to join `fact_sources` against."""
    conn, source_id, fact_id = source
    await knowledge.apply_fact_source_action(
        source_id, reliability_score=0.42, settings=reliability_settings
    )

    facts = await knowledge.fetch_facts_for_sync(conn, only_ids=[fact_id])

    assert len(facts) == 1
    assert facts[0]["source_reliability"] == 0.42
    assert facts[0]["published_at"] is not None
    assert facts[0]["source_name"] == NAME


async def test_listing_sources_reports_fact_and_sync_counts(source, reliability_settings):
    conn, source_id, fact_id = source
    await conn.execute("UPDATE fact_items SET synced_at = CURRENT_TIMESTAMP WHERE id = $1::uuid", fact_id)

    listed = await knowledge.list_fact_sources(settings=reliability_settings)

    row = next(item for item in listed if item["id"] == source_id)
    assert row["fact_count"] == 1
    assert row["synced_count"] == 1
    assert row["reliability_score"] == 0.80


async def test_fact_item_ids_for_source_is_the_resync_set(source, reliability_settings):
    _, source_id, fact_id = source

    assert await knowledge.fact_item_ids_for_source(source_id, settings=reliability_settings) == [fact_id]


async def test_created_sources_take_the_score_they_were_given(reliability_settings):
    created = await knowledge.create_fact_source(
        "Pytest Created Source", "https://created.test", True, 0.55, settings=reliability_settings
    )
    conn = await asyncpg.connect(reliability_settings.database_url)
    try:
        assert created["reliability_score"] == 0.55
        # Omitted means the column default, not zero.
        default = await knowledge.create_fact_source(
            "Pytest Default Source", "https://default.test", True, None, settings=reliability_settings
        )
        assert default["reliability_score"] == 0.80
    finally:
        await conn.execute(
            "DELETE FROM fact_sources WHERE name = ANY($1::text[])",
            ["Pytest Created Source", "Pytest Default Source"],
        )
        await conn.close()


async def test_ingestion_seeds_the_adapters_own_score(reliability_settings):
    """TurnBackHoax is IFCN-verified and the adapter says so once, at
    provisioning — after that the score belongs to the operator."""
    from app.ingestion.turnbackhoax import TurnBackHoaxAdapter
    from app.services.fact_ingestion import _ensure_source

    conn = await asyncpg.connect(reliability_settings.database_url)
    try:
        existing = await conn.fetchval("SELECT id FROM fact_sources WHERE slug = 'turnbackhoax'")
        if existing:
            pytest.skip("turnbackhoax source already provisioned in this database")

        source_id = await _ensure_source(conn, TurnBackHoaxAdapter(reliability_settings))
        score = await conn.fetchval("SELECT reliability_score FROM fact_sources WHERE id = $1", source_id)
        assert float(score) == TurnBackHoaxAdapter.reliability
    finally:
        await conn.close()
