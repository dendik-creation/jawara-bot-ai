"""The generic ingestion pipeline, against a live PostgreSQL.

Deliberately not a mocked database. Idempotency here *is* a database
property — the partial unique index on (source_id, external_id), the
insert-or-update decision, the fingerprint comparison — and a fake
connection would only prove that the Python branches were taken. Skipped
when Postgres is unreachable, same as `test_migrations.py`.

The source is stubbed, though: what these tests exercise is the pipeline,
and a suite that hit turnbackhoax.id would be neither deterministic nor
polite. Adapter behaviour has its own suite in
`test_fact_ingestion_adapter.py`.
"""

import uuid
from datetime import datetime, timezone

import asyncpg
import pytest

from app.core.config import Settings, get_settings
from app.ingestion.base import FactCheckSourceAdapter, NormalizedFactRecord, SourceCandidate, SourceFetchError
from app.services import fact_ingestion

pytestmark = pytest.mark.integration

SLUG = "pytest-source"
SOURCE_NAME = "Pytest Fact Source"
PUBLISHED = datetime(2026, 8, 12, 3, 0, tzinfo=timezone.utc)


class StubAdapter(FactCheckSourceAdapter):
    """A source under the test's control.

    `records` is keyed by external id, so a test can change one article's
    content between runs (the update path) or make one raise (the
    partial-failure path) without touching the pipeline.
    """

    slug = SLUG
    source_name = SOURCE_NAME
    base_url = "https://example.test"

    def __init__(self, candidates, records, *, listing_error: Exception | None = None) -> None:
        self.candidates = candidates
        self.records = records
        self.listing_error = listing_error
        self.fetched: list[str] = []
        self.closed = False

    async def list_candidates(self, limit: int):
        if self.listing_error:
            raise self.listing_error
        return self.candidates[:limit]

    async def fetch_record(self, candidate: SourceCandidate):
        self.fetched.append(candidate.external_id)
        outcome = self.records[candidate.external_id]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    async def aclose(self) -> None:
        self.closed = True


def _candidate(external_id: str) -> SourceCandidate:
    return SourceCandidate(
        external_id=external_id,
        url=f"https://example.test/articles/{external_id}",
        title=f"[SALAH] Klaim {external_id}",
    )


def _record(external_id: str, *, explanation: str = "Penjelasan resmi membantah klaim ini.") -> NormalizedFactRecord:
    return NormalizedFactRecord(
        source_slug=SLUG,
        source_name=SOURCE_NAME,
        external_id=external_id,
        source_url=f"https://example.test/articles/{external_id}",
        title=f"[SALAH] Klaim {external_id}",
        claim_text=f"Klaim nomor {external_id} yang beredar di WhatsApp.",
        fact_explanation=explanation,
        verdict="HOAX",
        category="GENERAL_NEWS",
        published_at=PUBLISHED,
        raw_metadata={"external_id": external_id, "site_category": "Politik"},
    )


@pytest.fixture
def ingest_settings(postgres_dsn):
    return Settings(
        database_url=postgres_dsn,
        fact_ingestion_sources=SLUG,
        fact_ingestion_auto_sync=False,
    )


@pytest.fixture
async def db(ingest_settings):
    """A connection, plus removal of everything this module wrote."""
    conn = await asyncpg.connect(ingest_settings.database_url)
    try:
        yield conn
    finally:
        source_id = await conn.fetchval("SELECT id FROM fact_sources WHERE slug = $1", SLUG)
        if source_id:
            await conn.execute("DELETE FROM fact_items WHERE source_id = $1", source_id)
        await conn.execute("DELETE FROM fact_ingestion_cursors WHERE source_slug = $1", SLUG)
        await conn.execute("DELETE FROM fact_ingestion_runs WHERE source_slug = $1", SLUG)
        if source_id:
            await conn.execute("DELETE FROM fact_sources WHERE id = $1", source_id)
        await conn.close()


@pytest.fixture
def use_adapter(monkeypatch):
    """Point the pipeline at a stub source. Returns a setter."""

    def _use(adapter: StubAdapter) -> StubAdapter:
        monkeypatch.setattr(fact_ingestion, "get_adapter", lambda slug, _settings: adapter)
        return adapter

    return _use


def _stub(ids=("101", "102"), **kwargs) -> StubAdapter:
    return StubAdapter([_candidate(i) for i in ids], {i: _record(i) for i in ids}, **kwargs)


async def _fact_rows(conn) -> list[asyncpg.Record]:
    return await conn.fetch(
        """
        SELECT fi.* FROM fact_items fi
        JOIN fact_sources fs ON fs.id = fi.source_id
        WHERE fs.slug = $1
        ORDER BY fi.external_id
        """,
        SLUG,
    )


# --------------------------------------------------------------------------
# Persistence and provenance
# --------------------------------------------------------------------------


async def test_first_run_creates_fact_items_with_full_provenance(ingest_settings, db, use_adapter):
    use_adapter(_stub())

    summary = await fact_ingestion.run_ingestion(SLUG, settings=ingest_settings)

    assert summary["status"] == "SUCCESS"
    assert (summary["fetched"], summary["created"], summary["duplicates"]) == (2, 2, 0)

    rows = await _fact_rows(db)
    assert [row["external_id"] for row in rows] == ["101", "102"]
    first = rows[0]
    assert first["source_url"] == "https://example.test/articles/101"
    assert first["published_at"] == PUBLISHED
    assert first["ingested_at"] is not None
    # Publication time is the source's, ingestion time is ours — never the
    # same field, never overwritten by the clock.
    assert first["published_at"] != first["ingested_at"]
    assert first["content_fingerprint"]
    assert first["verdict"] == "HOAX"


async def test_source_row_is_created_once_and_carries_the_adapter_slug(ingest_settings, db, use_adapter):
    use_adapter(_stub())
    await fact_ingestion.run_ingestion(SLUG, settings=ingest_settings)
    use_adapter(_stub())
    await fact_ingestion.run_ingestion(SLUG, settings=ingest_settings)

    sources = await db.fetch("SELECT id, name, base_url FROM fact_sources WHERE slug = $1", SLUG)
    assert len(sources) == 1
    assert sources[0]["name"] == SOURCE_NAME


async def test_existing_hand_created_source_is_adopted_not_duplicated(ingest_settings, db, use_adapter):
    """Operators already have a `fact_sources` row for the site; ingestion must
    attach to it rather than splitting the same publisher into two."""
    existing = await db.fetchval(
        "INSERT INTO fact_sources (name, base_url, is_trusted) VALUES ($1, $2, TRUE) RETURNING id",
        SOURCE_NAME,
        "https://example.test",
    )
    use_adapter(_stub(ids=("101",)))

    await fact_ingestion.run_ingestion(SLUG, settings=ingest_settings)

    assert await db.fetchval("SELECT count(*) FROM fact_sources WHERE name = $1", SOURCE_NAME) == 1
    assert await db.fetchval("SELECT slug FROM fact_sources WHERE id = $1", existing) == SLUG


# --------------------------------------------------------------------------
# Deduplication / idempotency
# --------------------------------------------------------------------------


async def test_repeated_runs_never_duplicate(ingest_settings, db, use_adapter):
    for _ in range(3):
        use_adapter(_stub())
        await fact_ingestion.run_ingestion(SLUG, settings=ingest_settings)

    rows = await _fact_rows(db)
    assert len(rows) == 2


async def test_second_run_skips_the_article_fetch_entirely(ingest_settings, db, use_adapter):
    """Incremental behaviour: known ids are filtered before the per-article
    request, so an unchanged source costs one feed request."""
    use_adapter(_stub())
    await fact_ingestion.run_ingestion(SLUG, settings=ingest_settings)

    second = use_adapter(_stub())
    summary = await fact_ingestion.run_ingestion(SLUG, settings=ingest_settings)

    assert second.fetched == []
    assert summary["duplicates"] == 2
    assert summary["created"] == 0


async def test_same_url_under_a_new_external_id_is_not_ingested_twice(ingest_settings, db, use_adapter):
    use_adapter(_stub(ids=("101",)))
    await fact_ingestion.run_ingestion(SLUG, settings=ingest_settings)

    renumbered = StubAdapter(
        [SourceCandidate(external_id="999", url="https://example.test/articles/101", title="x")],
        {"999": NormalizedFactRecord(**{**_record("101").__dict__, "external_id": "999"})},
    )
    use_adapter(renumbered)
    summary = await fact_ingestion.run_ingestion(SLUG, settings=ingest_settings)

    assert summary["duplicates"] == 1
    assert len(await _fact_rows(db)) == 1


async def test_identical_content_at_a_new_url_is_a_duplicate(ingest_settings, db, use_adapter):
    use_adapter(_stub(ids=("101",)))
    await fact_ingestion.run_ingestion(SLUG, settings=ingest_settings)

    reposted = NormalizedFactRecord(
        **{
            **_record("101").__dict__,
            "external_id": "202",
            "source_url": "https://example.test/articles/202-reposted",
        }
    )
    use_adapter(
        StubAdapter(
            [SourceCandidate(external_id="202", url=reposted.source_url, title=reposted.title)],
            {"202": reposted},
        )
    )
    summary = await fact_ingestion.run_ingestion(SLUG, settings=ingest_settings)

    assert summary["duplicates"] == 1
    assert len(await _fact_rows(db)) == 1


async def test_edited_article_updates_in_place_and_marks_it_for_resync(ingest_settings, db, use_adapter):
    use_adapter(_stub(ids=("101",)))
    await fact_ingestion.run_ingestion(SLUG, settings=ingest_settings)
    # Yesterday's ingest of a still-recent article: due for a re-check, which
    # is the only way a correction published after the fact is ever noticed.
    await db.execute(
        """
        UPDATE fact_items
        SET synced_at = CURRENT_TIMESTAMP, ingested_at = CURRENT_TIMESTAMP - INTERVAL '2 days'
        WHERE external_id = '101'
        """
    )
    before = (await _fact_rows(db))[0]

    edited = _record("101", explanation="Penjelasan yang sudah diperbarui oleh redaksi.")
    use_adapter(StubAdapter([_candidate("101")], {"101": edited}))
    summary = await fact_ingestion.run_ingestion(SLUG, settings=ingest_settings)

    assert (summary["updated"], summary["created"], summary["duplicates"]) == (1, 0, 0)
    rows = await _fact_rows(db)
    assert len(rows) == 1
    assert "diperbarui oleh redaksi" in rows[0]["fact_explanation"]
    assert rows[0]["content_fingerprint"] != before["content_fingerprint"]
    # Qdrant now holds the old text, so the row must not claim to be synced.
    assert rows[0]["synced_at"] is None


async def test_a_stale_but_unchanged_article_is_re_read_and_stays_one_row(ingest_settings, db, use_adapter):
    use_adapter(_stub(ids=("101",)))
    await fact_ingestion.run_ingestion(SLUG, settings=ingest_settings)
    await db.execute(
        "UPDATE fact_items SET ingested_at = CURRENT_TIMESTAMP - INTERVAL '2 days' WHERE external_id = '101'"
    )

    second = use_adapter(_stub(ids=("101",)))
    summary = await fact_ingestion.run_ingestion(SLUG, settings=ingest_settings)

    assert second.fetched == ["101"]  # re-read
    assert (summary["duplicates"], summary["updated"]) == (1, 0)  # unchanged
    assert len(await _fact_rows(db)) == 1


async def test_re_checking_can_be_switched_off(postgres_dsn, db, use_adapter):
    append_only = Settings(
        database_url=postgres_dsn,
        fact_ingestion_sources=SLUG,
        fact_ingestion_auto_sync=False,
        fact_ingestion_refresh_after_hours=0,
    )
    use_adapter(_stub(ids=("101",)))
    await fact_ingestion.run_ingestion(SLUG, settings=append_only)
    await db.execute(
        "UPDATE fact_items SET ingested_at = CURRENT_TIMESTAMP - INTERVAL '30 days' WHERE external_id = '101'"
    )

    second = use_adapter(_stub(ids=("101",)))
    await fact_ingestion.run_ingestion(SLUG, settings=append_only)

    assert second.fetched == []


async def test_an_old_article_is_left_alone_however_stale_the_check(postgres_dsn, db, use_adapter):
    """The re-check window is what keeps "notice corrections" from becoming
    "re-download the archive every hour"."""
    narrow = Settings(
        database_url=postgres_dsn,
        fact_ingestion_sources=SLUG,
        fact_ingestion_auto_sync=False,
        fact_ingestion_refresh_window_days=1,
    )
    use_adapter(_stub(ids=("101",)))
    await fact_ingestion.run_ingestion(SLUG, settings=narrow)
    await db.execute(
        """
        UPDATE fact_items
        SET ingested_at = CURRENT_TIMESTAMP - INTERVAL '10 days',
            published_at = CURRENT_TIMESTAMP - INTERVAL '30 days'
        WHERE external_id = '101'
        """
    )

    second = use_adapter(_stub(ids=("101",)))
    await fact_ingestion.run_ingestion(SLUG, settings=narrow)

    assert second.fetched == []


# --------------------------------------------------------------------------
# Failure handling
# --------------------------------------------------------------------------


async def test_unreachable_source_fails_the_run_without_losing_anything(ingest_settings, db, use_adapter):
    use_adapter(_stub(listing_error=SourceFetchError("HTTP 503", status_code=503, retryable=True)))

    summary = await fact_ingestion.run_ingestion(SLUG, settings=ingest_settings)

    assert summary["status"] == "FAILED"
    assert summary["retryable"] is True
    assert "503" in summary["error"]
    assert await _fact_rows(db) == []
    run = await db.fetchrow(
        "SELECT status::text AS status, error FROM fact_ingestion_runs WHERE id = $1", summary["run_id"]
    )
    assert run["status"] == "FAILED"


async def test_forbidden_source_is_not_marked_retryable(ingest_settings, db, use_adapter):
    use_adapter(_stub(listing_error=SourceFetchError("HTTP 403", status_code=403, retryable=False)))

    summary = await fact_ingestion.run_ingestion(SLUG, settings=ingest_settings)

    assert summary["status"] == "FAILED"
    assert summary["retryable"] is False


async def test_one_broken_article_does_not_cost_the_others(ingest_settings, db, use_adapter):
    adapter = _stub(ids=("101", "102", "103"))
    adapter.records["102"] = SourceFetchError("timeout", retryable=True)
    use_adapter(adapter)

    summary = await fact_ingestion.run_ingestion(SLUG, settings=ingest_settings)

    assert summary["status"] == "PARTIAL"
    assert (summary["created"], summary["failed"]) == (2, 1)
    assert [row["external_id"] for row in await _fact_rows(db)] == ["101", "103"]
    reasons = await db.fetchval(
        "SELECT details FROM fact_ingestion_runs WHERE id = $1", summary["run_id"]
    )
    assert "102" in str(reasons)


async def test_incomplete_record_is_rejected_and_counted(ingest_settings, db, use_adapter):
    adapter = _stub(ids=("101",))
    adapter.records["101"] = _record("101", explanation="   ")
    use_adapter(adapter)

    summary = await fact_ingestion.run_ingestion(SLUG, settings=ingest_settings)

    assert (summary["created"], summary["failed"]) == (0, 1)
    assert await _fact_rows(db) == []


async def test_a_failed_run_is_retried_by_the_next_one(ingest_settings, db, use_adapter):
    """Restart safety: nothing about a failed run blocks the following one."""
    use_adapter(_stub(listing_error=SourceFetchError("HTTP 500", status_code=500)))
    await fact_ingestion.run_ingestion(SLUG, settings=ingest_settings)

    use_adapter(_stub())
    summary = await fact_ingestion.run_ingestion(SLUG, settings=ingest_settings)

    assert summary["status"] == "SUCCESS"
    assert summary["created"] == 2


async def test_failed_run_does_not_advance_last_success(ingest_settings, db, use_adapter):
    use_adapter(_stub(ids=("101",)))
    await fact_ingestion.run_ingestion(SLUG, settings=ingest_settings)
    succeeded_at = await db.fetchval(
        "SELECT last_success_at FROM fact_ingestion_cursors WHERE source_slug = $1", SLUG
    )

    use_adapter(_stub(listing_error=SourceFetchError("HTTP 500", status_code=500)))
    await fact_ingestion.run_ingestion(SLUG, settings=ingest_settings)

    assert (
        await db.fetchval("SELECT last_success_at FROM fact_ingestion_cursors WHERE source_slug = $1", SLUG)
        == succeeded_at
    )


# --------------------------------------------------------------------------
# Knowledge-base sync — the existing path, not a second one
# --------------------------------------------------------------------------


async def test_new_items_are_pushed_through_the_existing_knowledge_sync(postgres_dsn, db, use_adapter, monkeypatch):
    synced_settings = Settings(
        database_url=postgres_dsn, fact_ingestion_sources=SLUG, fact_ingestion_auto_sync=True
    )
    calls: list[list[str]] = []

    async def fake_sync(ids, *, settings=None, **_):
        calls.append(list(ids))
        return {"total": len(ids), "upserted": len(ids), "failed": 0, "rejected": []}

    monkeypatch.setattr("app.services.knowledge.sync_fact_items", fake_sync)
    use_adapter(_stub())

    summary = await fact_ingestion.run_ingestion(SLUG, settings=synced_settings)

    assert summary["synced"] == 2
    ids = {str(row["id"]) for row in await _fact_rows(db)}
    assert set(calls[0]) == ids


async def test_a_sync_failure_keeps_the_facts_and_reports_partial(postgres_dsn, db, use_adapter, monkeypatch):
    synced_settings = Settings(
        database_url=postgres_dsn, fact_ingestion_sources=SLUG, fact_ingestion_auto_sync=True
    )

    async def exploding_sync(ids, *, settings=None, **_):
        raise ConnectionError("ml service down")

    monkeypatch.setattr("app.services.knowledge.sync_fact_items", exploding_sync)
    use_adapter(_stub())

    summary = await fact_ingestion.run_ingestion(SLUG, settings=synced_settings)

    assert summary["status"] == "PARTIAL"
    assert summary["sync_failed"] == 2
    # The facts themselves are safe in PostgreSQL; the next run or the
    # operator's "Sync All" pushes them.
    assert len(await _fact_rows(db)) == 2


async def test_duplicate_only_run_syncs_nothing(postgres_dsn, db, use_adapter, monkeypatch):
    synced_settings = Settings(
        database_url=postgres_dsn, fact_ingestion_sources=SLUG, fact_ingestion_auto_sync=True
    )
    calls: list[list[str]] = []

    async def fake_sync(ids, *, settings=None, **_):
        calls.append(list(ids))
        return {"total": len(ids), "upserted": len(ids), "failed": 0, "rejected": []}

    monkeypatch.setattr("app.services.knowledge.sync_fact_items", fake_sync)

    use_adapter(_stub())
    await fact_ingestion.run_ingestion(SLUG, settings=synced_settings)
    use_adapter(_stub())
    await fact_ingestion.run_ingestion(SLUG, settings=synced_settings)

    assert len(calls) == 1  # only the run that actually wrote something


# --------------------------------------------------------------------------
# Observability
# --------------------------------------------------------------------------


async def test_every_run_is_recorded_with_its_counters(ingest_settings, db, use_adapter):
    use_adapter(_stub())
    await fact_ingestion.run_ingestion(SLUG, settings=ingest_settings)
    use_adapter(_stub())
    await fact_ingestion.run_ingestion(SLUG, triggered_by="MANUAL", settings=ingest_settings)

    listed = await fact_ingestion.list_ingestion_runs(source_slug=SLUG, settings=ingest_settings)

    assert listed["total"] == 2
    newest, oldest = listed["items"]
    assert newest["triggered_by"] == "MANUAL"
    assert (newest["duplicates"], newest["created"]) == (2, 0)
    assert (oldest["triggered_by"], oldest["created"]) == ("SCHEDULE", 2)
    assert newest["finished_at"] is not None


async def test_status_answers_when_ingestion_last_ran_and_last_worked(ingest_settings, db, use_adapter):
    use_adapter(_stub())
    await fact_ingestion.run_ingestion(SLUG, settings=ingest_settings)

    status = await fact_ingestion.get_ingestion_status(ingest_settings)

    source = next(s for s in status["sources"] if s["slug"] == SLUG)
    assert source["ingested_facts"] == 2
    assert source["last_success_at"] is not None
    assert source["last_published_at"].startswith("2026-08-12")
    assert source["last_run"]["status"] == "SUCCESS"
    assert source["last_run"]["fetched"] == 2


async def test_run_summary_is_loggable_at_info(ingest_settings, db, use_adapter, caplog):
    """Regression: the summary carries a `created` count, and `logging` owns an
    attribute by that name — splatting it into `extra=` raised KeyError and
    failed the Celery task *after* a perfectly good ingestion."""
    import logging

    use_adapter(_stub())

    with caplog.at_level(logging.INFO, logger="app.services.fact_ingestion"):
        await fact_ingestion.run_ingestion(SLUG, settings=ingest_settings)

    finished = [r for r in caplog.records if r.message == "ingestion run finished"]
    assert finished and finished[0].ingestion["created"] == 2


async def test_cursor_remembers_the_newest_item(ingest_settings, db, use_adapter):
    use_adapter(_stub())
    await fact_ingestion.run_ingestion(SLUG, settings=ingest_settings)

    cursor = await db.fetchrow("SELECT * FROM fact_ingestion_cursors WHERE source_slug = $1", SLUG)
    assert cursor["last_external_id"] == "101"  # feed order is newest first
    assert cursor["last_published_at"] == PUBLISHED
    assert cursor["last_run_id"] is not None


async def test_adapter_is_closed_even_when_the_source_fails(ingest_settings, db, use_adapter):
    adapter = use_adapter(_stub(listing_error=SourceFetchError("boom")))

    await fact_ingestion.run_ingestion(SLUG, settings=ingest_settings)

    assert adapter.closed is True


async def test_unknown_source_fails_loudly(ingest_settings):
    with pytest.raises(KeyError):
        await fact_ingestion.run_ingestion(f"nope-{uuid.uuid4().hex[:6]}", settings=ingest_settings)


async def test_run_all_sources_reports_each_source(ingest_settings, db, use_adapter):
    use_adapter(_stub())

    summaries = await fact_ingestion.run_all_sources(settings=ingest_settings)

    assert [s["source"] for s in summaries] == [SLUG]
    assert summaries[0]["status"] == "SUCCESS"


def test_real_registry_exposes_turnbackhoax():
    from app.ingestion import available_sources, get_adapter

    assert "turnbackhoax" in available_sources()
    adapter = get_adapter("turnbackhoax", get_settings())
    assert adapter.base_url == "https://turnbackhoax.id"
