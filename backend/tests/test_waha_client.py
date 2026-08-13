"""Outbound WhatsApp dispatch: payload shape, retry policy, failure reporting."""

from app.clients.waha_client import WahaClient
from app.core.config import Settings
from tests.http_stub import FakeResponse, patch_httpx, raise_timeout

CHAT_ID = "628111@c.us"
REPLY = "🔴 *HOAKS / BAHAYA TINGGI*\n\nBapak/Ibu..."


def waha_settings(**overrides) -> Settings:
    base = {
        "waha_api_url": "http://waha:3000",
        "waha_api_key": "waha-key",
        "waha_send_max_attempts": 2,
        "waha_send_retry_backoff_seconds": 0.0,
    }
    base.update(overrides)
    return Settings(**base)


async def test_sends_to_the_documented_endpoint_and_chat(monkeypatch):
    calls = patch_httpx(
        monkeypatch, "app.clients.waha_client", lambda **_: FakeResponse(201, {"id": "true_x_1"})
    )
    result = await WahaClient(waha_settings()).send_text(CHAT_ID, REPLY, session="default")

    assert calls[0]["url"] == "http://waha:3000/api/sendText"
    assert calls[0]["json"] == {"session": "default", "chatId": CHAT_ID, "text": REPLY}
    assert calls[0]["headers"]["X-Api-Key"] == "waha-key"
    assert result.delivered is True
    assert result.message_id == "true_x_1"


async def test_transient_failure_is_retried_then_succeeds(monkeypatch):
    attempts: list[int] = []

    def handler(**_):
        attempts.append(1)
        if len(attempts) == 1:
            raise_timeout()
        return FakeResponse(200, {"id": {"_serialized": "true_x_2"}})

    patch_httpx(monkeypatch, "app.clients.waha_client", handler)
    result = await WahaClient(waha_settings()).send_text(CHAT_ID, REPLY)

    assert result.delivered is True
    assert result.attempts == 2
    assert result.message_id == "true_x_2"


async def test_persistent_failure_is_reported_not_raised(monkeypatch):
    patch_httpx(monkeypatch, "app.clients.waha_client", raise_timeout)
    result = await WahaClient(waha_settings()).send_text(CHAT_ID, REPLY)

    assert result.delivered is False
    assert result.attempts == 2
    assert result.error == "timeout"


async def test_client_error_is_not_retried(monkeypatch):
    # A bad chatId or a stopped session fails identically on attempt two.
    calls = patch_httpx(monkeypatch, "app.clients.waha_client", lambda **_: FakeResponse(422))
    result = await WahaClient(waha_settings()).send_text(CHAT_ID, REPLY)

    assert len(calls) == 1
    assert result.delivered is False
    assert result.error == "http_422"


async def test_get_message_text_hits_the_documented_endpoint(monkeypatch):
    calls = patch_httpx(
        monkeypatch, "app.clients.waha_client", lambda **_: FakeResponse(200, {"body": "cek info ini ya"})
    )
    text = await WahaClient(waha_settings()).get_message_text("default", CHAT_ID, "false_x_1")

    assert calls[0]["method"] == "GET"
    assert calls[0]["url"] == f"http://waha:3000/api/default/chats/{CHAT_ID}/messages/false_x_1"
    assert text == "cek info ini ya"


async def test_get_message_text_returns_none_when_not_found(monkeypatch):
    patch_httpx(monkeypatch, "app.clients.waha_client", lambda **_: FakeResponse(404))
    text = await WahaClient(waha_settings()).get_message_text("default", CHAT_ID, "gone")

    assert text is None


async def test_get_message_text_returns_none_on_transport_failure(monkeypatch):
    patch_httpx(monkeypatch, "app.clients.waha_client", raise_timeout)
    text = await WahaClient(waha_settings()).get_message_text("default", CHAT_ID, "x")

    assert text is None


async def test_get_message_text_returns_none_for_blank_body(monkeypatch):
    patch_httpx(monkeypatch, "app.clients.waha_client", lambda **_: FakeResponse(200, {"body": "   "}))
    text = await WahaClient(waha_settings()).get_message_text("default", CHAT_ID, "x")

    assert text is None


async def test_get_message_hits_the_documented_endpoint(monkeypatch):
    calls = patch_httpx(
        monkeypatch,
        "app.clients.waha_client",
        lambda **_: FakeResponse(200, {"body": "cek info ini ya", "hasMedia": False}),
    )
    data = await WahaClient(waha_settings()).get_message("default", CHAT_ID, "false_x_1")

    assert calls[0]["method"] == "GET"
    assert calls[0]["url"] == f"http://waha:3000/api/default/chats/{CHAT_ID}/messages/false_x_1"
    assert data == {"body": "cek info ini ya", "hasMedia": False}


async def test_get_message_with_download_media_appends_the_query_param(monkeypatch):
    calls = patch_httpx(
        monkeypatch,
        "app.clients.waha_client",
        lambda **_: FakeResponse(200, {"hasMedia": True, "media": {"url": "http://waha:3000/api/files/x.jpg"}}),
    )
    data = await WahaClient(waha_settings()).get_message(
        "default", CHAT_ID, "false_x_1", download_media=True
    )

    assert calls[0]["url"] == f"http://waha:3000/api/default/chats/{CHAT_ID}/messages/false_x_1?downloadMedia=true"
    assert data["media"]["url"] == "http://waha:3000/api/files/x.jpg"


async def test_get_message_returns_none_when_not_found(monkeypatch):
    patch_httpx(monkeypatch, "app.clients.waha_client", lambda **_: FakeResponse(404))
    assert await WahaClient(waha_settings()).get_message("default", CHAT_ID, "gone") is None


async def test_get_message_returns_none_on_transport_failure(monkeypatch):
    patch_httpx(monkeypatch, "app.clients.waha_client", raise_timeout)
    assert await WahaClient(waha_settings()).get_message("default", CHAT_ID, "x") is None


async def test_server_error_is_retried(monkeypatch):
    calls = patch_httpx(monkeypatch, "app.clients.waha_client", lambda **_: FakeResponse(500))
    await WahaClient(waha_settings()).send_text(CHAT_ID, REPLY)

    assert len(calls) == 2


async def test_session_list_is_normalised_for_the_control_panel(monkeypatch):
    patch_httpx(
        monkeypatch,
        "app.clients.waha_client",
        lambda **_: FakeResponse(
            200, [{"name": "default", "status": "WORKING", "engine": {"engine": "WEBJS"}}]
        ),
    )
    sessions = await WahaClient(waha_settings()).list_sessions()

    assert sessions == [{"name": "default", "status": "WORKING", "engine": "WEBJS"}]


async def test_session_list_failure_is_an_empty_list_not_an_exception(monkeypatch):
    patch_httpx(monkeypatch, "app.clients.waha_client", raise_timeout)
    assert await WahaClient(waha_settings()).list_sessions() == []


async def test_download_media_returns_the_raw_bytes(monkeypatch):
    calls = patch_httpx(
        monkeypatch, "app.clients.waha_client", lambda **_: FakeResponse(200, content=b"\xff\xd8\xff...jpeg")
    )
    result = await WahaClient(waha_settings()).download_media("http://waha:3000/api/files/abc.jpg")

    assert calls[0]["url"] == "http://waha:3000/api/files/abc.jpg"
    assert calls[0]["headers"]["X-Api-Key"] == "waha-key"
    assert result == b"\xff\xd8\xff...jpeg"


async def test_download_media_failure_is_none_not_an_exception(monkeypatch):
    patch_httpx(monkeypatch, "app.clients.waha_client", raise_timeout)
    assert await WahaClient(waha_settings()).download_media("http://waha:3000/api/files/gone.jpg") is None


async def test_download_media_4xx_is_none(monkeypatch):
    patch_httpx(monkeypatch, "app.clients.waha_client", lambda **_: FakeResponse(404))
    assert await WahaClient(waha_settings()).download_media("http://waha:3000/api/files/missing.jpg") is None


async def test_download_media_rewrites_a_host_waha_reported_that_is_unreachable_from_here(monkeypatch):
    """WAHA embeds its own webhook payload URLs using its own view of its
    host — often `localhost`, which resolves to the worker container itself,
    not WAHA. The path WAHA reported is real; the host it put in front of it
    is not, so it is swapped for `waha_api_url`, the one address every other
    call in this client already proves reachable."""
    calls = patch_httpx(monkeypatch, "app.clients.waha_client", lambda **_: FakeResponse(200, content=b"jpeg-bytes"))
    result = await WahaClient(waha_settings()).download_media("http://localhost:3000/api/files/abc.jpg?token=x")

    assert calls[0]["url"] == "http://waha:3000/api/files/abc.jpg?token=x"
    assert result == b"jpeg-bytes"


async def test_download_media_accepts_a_bare_path(monkeypatch):
    calls = patch_httpx(monkeypatch, "app.clients.waha_client", lambda **_: FakeResponse(200, content=b"bytes"))
    await WahaClient(waha_settings()).download_media("/api/files/abc.jpg")

    assert calls[0]["url"] == "http://waha:3000/api/files/abc.jpg"
