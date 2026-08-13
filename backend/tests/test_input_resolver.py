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
