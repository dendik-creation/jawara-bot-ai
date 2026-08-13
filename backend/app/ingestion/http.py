"""Polite HTTP for crawlers.

Every adapter fetch goes through here, which is what makes "respect the
source" a property of the package rather than of each adapter's good
intentions: one request at a time, a minimum gap between requests, a small
bounded number of retries, an identifying User-Agent, and `Retry-After`
honoured when the server sends it.

Status handling mirrors the vocabulary the pipeline already needs:
429/5xx/timeout are retryable `SourceFetchError`s, 403/404 are not. Nothing
is swallowed — a failure always becomes an exception the caller records.
"""

import asyncio
import logging
import random
import time

import httpx

from app.core.config import Settings, get_settings
from app.ingestion.base import SourceFetchError

logger = logging.getLogger("app.ingestion.http")

RETRYABLE_STATUSES = frozenset({408, 425, 429, 500, 502, 503, 504})
# Never wait longer than this on a Retry-After, however generous the header:
# a scheduled task that parks a worker for an hour is a worse outage than a
# skipped run.
MAX_RETRY_AFTER_SECONDS = 60.0


class PoliteHttpClient:
    """Serial, rate-limited HTTP GET. One instance per ingestion run."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._last_request_at: float | None = None

    @property
    def _delay(self) -> float:
        return self._settings.fact_ingestion_request_delay_seconds

    async def get_text(self, url: str) -> str:
        settings = self._settings
        attempts = max(1, settings.fact_ingestion_max_attempts)
        last_error: SourceFetchError | None = None

        for attempt in range(attempts):
            await self._wait_turn()
            try:
                async with httpx.AsyncClient(
                    timeout=settings.fact_ingestion_request_timeout_seconds,
                    follow_redirects=True,
                ) as client:
                    response = await client.get(
                        url,
                        headers={
                            "User-Agent": settings.fact_ingestion_user_agent,
                            "Accept": "application/rss+xml, application/xml, text/html;q=0.9, */*;q=0.5",
                        },
                    )
            except httpx.TimeoutException as exc:
                last_error = SourceFetchError(f"timeout fetching {url}: {exc}", retryable=True)
            except httpx.HTTPError as exc:
                last_error = SourceFetchError(f"transport error fetching {url}: {exc}", retryable=True)
            else:
                if response.status_code < 400:
                    return response.text
                last_error = SourceFetchError(
                    f"HTTP {response.status_code} fetching {url}",
                    status_code=response.status_code,
                    retryable=response.status_code in RETRYABLE_STATUSES,
                )
                if not last_error.retryable:
                    break
                await self._honour_retry_after(response)

            if attempt + 1 < attempts and last_error.retryable:
                backoff = settings.fact_ingestion_retry_backoff_seconds * (2**attempt)
                logger.warning(
                    "source fetch failed, retrying",
                    extra={
                        "url": url,
                        "attempt": attempt + 1,
                        "status_code": last_error.status_code,
                        "backoff_seconds": round(backoff, 2),
                    },
                )
                # Jitter for the same reason the Celery retry policy has it: a
                # 429 hit by several sources at once should not produce a
                # synchronised second wave.
                await asyncio.sleep(backoff + random.uniform(0, backoff / 2))

        assert last_error is not None
        logger.warning(
            "source fetch failed",
            extra={"url": url, "status_code": last_error.status_code, "retryable": last_error.retryable},
        )
        raise last_error

    async def _wait_turn(self) -> None:
        """Keep at least `fact_ingestion_request_delay_seconds` between requests."""
        if self._last_request_at is not None:
            elapsed = time.monotonic() - self._last_request_at
            if elapsed < self._delay:
                await asyncio.sleep(self._delay - elapsed)
        self._last_request_at = time.monotonic()

    async def _honour_retry_after(self, response: httpx.Response) -> None:
        header = (getattr(response, "headers", None) or {}).get("Retry-After")
        if not header:
            return
        try:
            seconds = float(header)
        except ValueError:
            return
        wait = min(max(seconds, 0.0), MAX_RETRY_AFTER_SECONDS)
        logger.info("honouring Retry-After", extra={"seconds": wait})
        await asyncio.sleep(wait)
