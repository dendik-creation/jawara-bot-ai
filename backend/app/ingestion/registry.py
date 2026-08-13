"""Slug → adapter lookup.

The one place a new source is wired in. Factories rather than instances:
an adapter holds a `PoliteHttpClient` whose rate-limit state is per run, so
each ingestion run constructs its own.

CekFakta, Kompas, ANTARA, Tirto and AFP are deliberately absent — Phase 1
ships TurnBackHoax only. They arrive as one module plus one line here.
"""

from typing import Callable

from app.core.config import Settings
from app.ingestion.base import FactCheckSourceAdapter
from app.ingestion.turnbackhoax import TurnBackHoaxAdapter

AdapterFactory = Callable[[Settings], FactCheckSourceAdapter]

_ADAPTERS: dict[str, AdapterFactory] = {
    TurnBackHoaxAdapter.slug: lambda settings: TurnBackHoaxAdapter(settings),
}


def get_adapter(slug: str, settings: Settings) -> FactCheckSourceAdapter:
    """Raises `KeyError` for an unknown slug — a typo in configuration must
    fail loudly rather than silently ingest nothing."""
    try:
        factory = _ADAPTERS[slug]
    except KeyError:
        raise KeyError(f"unknown fact-check source '{slug}' (known: {', '.join(sorted(_ADAPTERS))})") from None
    return factory(settings)


def available_sources() -> list[str]:
    return sorted(_ADAPTERS)
