"""Trusted-domain Knowledge Base sources against a live PostgreSQL.

`normalized_domain`'s uniqueness constraint and `lookup_trusted_sources`'s
exact-or-subdomain matching are database facts a mocked connection could
only pretend to have — same reasoning as `test_source_reliability_integration.py`.
Skipped when Postgres is unreachable.
"""

import asyncpg
import pytest

from app.core.config import Settings
from app.services import knowledge

pytestmark = pytest.mark.integration


@pytest.fixture
def trust_settings(postgres_dsn):
    return Settings(database_url=postgres_dsn)


@pytest.fixture
async def cleanup_sources(trust_settings):
    created_names: list[str] = []
    yield created_names
    if not created_names:
        return
    conn = await asyncpg.connect(trust_settings.database_url)
    try:
        await conn.execute("DELETE FROM fact_sources WHERE name = ANY($1::text[])", created_names)
    finally:
        await conn.close()


async def test_created_source_gets_its_normalized_domain(trust_settings, cleanup_sources):
    cleanup_sources.append("Pytest PLN")
    created = await knowledge.create_fact_source(
        "Pytest PLN", "https://www.pln.co.id", True, settings=trust_settings
    )
    assert created["normalized_domain"] == "pln.co.id"


async def test_creating_a_second_source_on_the_same_domain_is_rejected(trust_settings, cleanup_sources):
    cleanup_sources.append("Pytest PLN Original")
    await knowledge.create_fact_source(
        "Pytest PLN Original", "https://pln.co.id", True, settings=trust_settings
    )

    with pytest.raises(ValueError, match="sudah terdaftar"):
        await knowledge.create_fact_source(
            "Pytest PLN Duplicate", "https://www.pln.co.id/beranda", True, settings=trust_settings
        )


async def test_lookup_matches_the_domain_and_its_subdomains(trust_settings, cleanup_sources):
    cleanup_sources.append("Pytest PLN Lookup")
    await knowledge.create_fact_source(
        "Pytest PLN Lookup", "https://pln.co.id", True, settings=trust_settings
    )

    matched = await knowledge.lookup_trusted_sources(
        ["pln.co.id", "rekrutmen.pln.co.id", "pln-co-id.example.com"], settings=trust_settings
    )

    assert matched["pln.co.id"].name == "Pytest PLN Lookup"
    assert matched["rekrutmen.pln.co.id"].name == "Pytest PLN Lookup"
    assert "pln-co-id.example.com" not in matched


async def test_lookup_ignores_untrusted_sources(trust_settings, cleanup_sources):
    cleanup_sources.append("Pytest Untrusted")
    await knowledge.create_fact_source(
        "Pytest Untrusted", "https://untrusted-example.test", False, settings=trust_settings
    )

    matched = await knowledge.lookup_trusted_sources(["untrusted-example.test"], settings=trust_settings)

    assert "untrusted-example.test" not in matched


async def test_lookup_never_raises_when_the_database_is_unreachable():
    unreachable = Settings(database_url="postgresql://user:pass@127.0.0.1:1/does_not_matter")
    matched = await knowledge.lookup_trusted_sources(["pln.co.id"], settings=unreachable)
    assert matched == {}
