"""Reply-to-media resolution — turning a `replyTo` pointer into the text
and/or image `!cek` should actually check (JAWARA reply-to-media fix).
"""

from app.pipeline.input_resolver import resolve_quoted_message

CHAT_ID = "628111@g.us"
MESSAGE_ID = "false_x_1"


class FakeWahaMessages:
    """Stands in for `WahaClient`, answering `get_message()` from a script of
    responses keyed by whether `downloadMedia` was requested."""

    def __init__(self, plain: dict | None = None, with_download: dict | None = None):
        self._plain = plain
        self._with_download = with_download
        self.calls: list[dict] = []

    async def get_message(self, session, chat_id, message_id, download_media=False):
        self.calls.append(
            {"session": session, "chat_id": chat_id, "message_id": message_id, "download_media": download_media}
        )
        return self._with_download if download_media else self._plain


async def test_quoted_message_unavailable_degrades():
    waha = FakeWahaMessages(plain=None)

    result = await resolve_quoted_message(waha, "default", CHAT_ID, MESSAGE_ID, {})

    assert result.text is None
    assert result.image is None
    assert result.degraded == ("quoted_message_unavailable",)
    assert len(waha.calls) == 1


async def test_inline_reply_to_resolves_without_calling_waha_at_all():
    """Production incident: `payload["replyTo"]` on this WAHA build already
    carries the full quoted message (`body`, `media.url`), not just an id
    pointer — and `GET .../messages/{id}` 500s unconditionally on this
    deployment regardless of id shape. Using the inline data directly is
    what makes `!cek` on a reply-to-image work at all here, not just faster."""
    waha = FakeWahaMessages(plain={"body": "should never be fetched"})
    inline = {
        "id": "3EB0DAF7516034EE5BE090",
        "participant": "99669027872892@lid",
        "body": "apakah ini nyata",
        "hasMedia": True,
        "media": {
            "url": "http://localhost:3000/api/files/x/y.jpeg",
            "filename": None,
            "mimetype": "image/jpeg",
        },
    }

    result = await resolve_quoted_message(waha, "default", CHAT_ID, MESSAGE_ID, {}, inline=inline)

    assert result.text == "apakah ini nyata"
    assert result.image is not None
    assert result.image.url == "http://localhost:3000/api/files/x/y.jpeg"
    assert result.degraded == ()
    assert waha.calls == []  # never touched WahaClient.get_message


async def test_inline_reply_to_with_nothing_usable_falls_back_to_fetching():
    """A bare pointer (`replyTo` with only `id`/`participant`, the older-WAHA
    shape the existing tests below already cover) must still fall back to
    the fetch path — inline is an optimisation/workaround, not a
    replacement for messages that genuinely need it."""
    waha = FakeWahaMessages(plain={"body": "fetched text", "hasMedia": False})
    inline = {"id": "msg_0", "participant": "6287712032005@c.us"}

    result = await resolve_quoted_message(waha, "default", CHAT_ID, MESSAGE_ID, {}, inline=inline)

    assert result.text == "fetched text"
    assert len(waha.calls) == 1


async def test_quoted_text_only_resolves_without_a_second_call():
    waha = FakeWahaMessages(plain={"body": "Air rebusan daun kitolod menyembuhkan katarak", "hasMedia": False})

    result = await resolve_quoted_message(waha, "default", CHAT_ID, MESSAGE_ID, {})

    assert result.text == "Air rebusan daun kitolod menyembuhkan katarak"
    assert result.image is None
    assert result.degraded == ()
    assert len(waha.calls) == 1  # no downloadMedia fallback needed


async def test_inline_media_url_resolves_on_the_first_call():
    waha = FakeWahaMessages(
        plain={
            "hasMedia": True,
            "media": {"mimetype": "image/jpeg", "url": "http://waha:3000/api/files/abc.jpg"},
        }
    )

    result = await resolve_quoted_message(waha, "default", CHAT_ID, MESSAGE_ID, {})

    assert result.image is not None
    assert result.image.url == "http://waha:3000/api/files/abc.jpg"
    assert result.degraded == ()
    assert len(waha.calls) == 1  # media.url was already usable — no fallback fetch


async def test_has_media_true_with_no_inline_reference_falls_back_to_download_media():
    waha = FakeWahaMessages(
        plain={"hasMedia": True, "media": None},
        with_download={
            "hasMedia": True,
            "media": {"mimetype": "image/jpeg", "data": "ZmFrZS1qcGVn"},
        },
    )

    result = await resolve_quoted_message(waha, "default", CHAT_ID, MESSAGE_ID, {})

    assert result.image is not None
    assert result.image.data == b"fake-jpeg"
    assert result.degraded == ()
    assert len(waha.calls) == 2
    assert waha.calls[1]["download_media"] is True


async def test_fallback_still_unresolvable_is_a_user_safe_degradation_not_a_crash():
    waha = FakeWahaMessages(
        plain={"hasMedia": True, "media": None},
        with_download={"hasMedia": True, "media": None},
    )

    result = await resolve_quoted_message(waha, "default", CHAT_ID, MESSAGE_ID, {})

    assert result.image is None
    assert result.degraded == ("reply_media_unavailable",)
    assert len(waha.calls) == 2  # bounded — exactly one retry, not a loop


async def test_caption_recovered_from_the_fallback_fetch_when_the_first_had_none():
    waha = FakeWahaMessages(
        plain={"hasMedia": True, "media": None},
        with_download={
            "hasMedia": True,
            "caption": "modal cuma 50rb, cuan jutaan",
            "media": {"mimetype": "image/jpeg", "url": "http://waha:3000/api/files/x.jpg"},
        },
    )

    result = await resolve_quoted_message(waha, "default", CHAT_ID, MESSAGE_ID, {})

    assert result.text == "modal cuma 50rb, cuan jutaan"
    assert result.image is not None
