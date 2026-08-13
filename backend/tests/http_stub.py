"""Minimal `httpx.AsyncClient` stand-in for client tests.

Every outbound client builds its own `AsyncClient` inside the call — that is what
keeps connection setup out of the caller's hands — so tests replace the class in
the module under test rather than injecting a transport.

Deliberately not a mock library: the clients are judged on how they react to
statuses, timeouts and malformed bodies, and a handler function expresses those
cases more directly than layers of `assert_called_with`.
"""

from typing import Any, Callable

import httpx


class FakeResponse:
    def __init__(
        self,
        status_code: int = 200,
        json_data: Any = None,
        text: str = "",
        headers: dict[str, str] | None = None,
        content: bytes = b"",
    ) -> None:
        self.status_code = status_code
        self._json = json_data
        self.text = text or ""
        # Some clients read response headers (Retry-After on a 429); an empty
        # mapping keeps the stub usable for the ones that don't.
        self.headers = headers or {}
        # Raw bytes for clients that download binary content (media fetches)
        # rather than parse JSON.
        self.content = content

    def json(self) -> Any:
        if self._json is None:
            raise ValueError("no json body")
        return self._json


Handler = Callable[..., FakeResponse]


class FakeAsyncClient:
    """Records every request and delegates the answer to a handler."""

    calls: list[dict[str, Any]] = []

    def __init__(self, handler: Handler, **_: Any) -> None:
        self._handler = handler

    async def __aenter__(self) -> "FakeAsyncClient":
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def post(self, url: str, **kwargs: Any) -> FakeResponse:
        return self._record("POST", url, kwargs)

    async def get(self, url: str, **kwargs: Any) -> FakeResponse:
        return self._record("GET", url, kwargs)

    def _record(self, method: str, url: str, kwargs: dict[str, Any]) -> FakeResponse:
        FakeAsyncClient.calls.append({"method": method, "url": url, **kwargs})
        return self._handler(method=method, url=url, **kwargs)


def patch_httpx(monkeypatch, module: str, handler: Handler) -> list[dict[str, Any]]:
    """Point `module.httpx.AsyncClient` at `handler`. Returns the call log."""
    FakeAsyncClient.calls = []

    def factory(*_: Any, **kwargs: Any) -> FakeAsyncClient:
        return FakeAsyncClient(handler, **kwargs)

    monkeypatch.setattr(f"{module}.httpx.AsyncClient", factory)
    return FakeAsyncClient.calls


def raise_timeout(**_: Any) -> FakeResponse:
    raise httpx.TimeoutException("timed out")


def raise_connect_error(**_: Any) -> FakeResponse:
    raise httpx.ConnectError("connection refused")
