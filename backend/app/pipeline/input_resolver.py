"""Resolves what a replied-to WhatsApp message actually contains.

A `!cek` on a reply is a request about *the replied message*, not about the
one-line question next to it (JAWARA Strict WhatsApp Command System §4.1,
§12: "Mention = activation. Command = intent."). WAHA's webhook only carries
a pointer to that message (`group_policy.quoted_message_id`) — this module
turns the pointer into the text and/or image the analysis pipeline can
actually read.

Kept separate from `orchestrator.py` on purpose: this is WhatsApp-payload
parsing (what did the replied message contain), not JAWARA analysis (what
does it mean). `image_attachment_of()` from `app.pipeline.media` is reused
here unchanged — a replied message fetched via `WahaClient.get_message()` is
the same WAHA message shape as a live webhook payload, so there is exactly
one place that decides "this counts as an image".
"""

import logging
from dataclasses import dataclass

from app.clients.waha_client import WahaClient
from app.pipeline.media import ImageAttachment, image_attachment_of

logger = logging.getLogger("app.pipeline.input_resolver")


@dataclass(frozen=True)
class ResolvedQuote:
    """What the replied-to message actually contained, once resolved.

    `text` and `image` are independent — a reply can carry either, both, or
    neither. `degraded` names what went wrong, if anything; a resolver never
    raises, it degrades (same contract as the rest of the pipeline).
    """

    text: str | None = None
    image: ImageAttachment | None = None
    degraded: tuple[str, ...] = ()


def _text_of(data: dict) -> str | None:
    text = data.get("body") or data.get("caption")
    return text.strip() if isinstance(text, str) and text.strip() else None


async def resolve_quoted_message(
    waha: WahaClient,
    session: str,
    chat_id: str,
    message_id: str,
    log_context: dict[str, object],
) -> ResolvedQuote:
    """Fetch the replied-to message and pull out its text and/or image.

    Preferred path: one `GET .../messages/{id}` call, same as a normal
    webhook delivery, read for both text and an inline media reference
    (`media.url` or `media.data`) — one round trip serves both, never two
    downloads for what is one message (§22 of the reply-to-media task note).

    Fallback path: WAHA sometimes reports `hasMedia: true` without inlining
    a usable reference (no `media.url`, no `media.data` — engine/version
    dependent). Exactly then, and only then, this retries the same endpoint
    with `?downloadMedia=true` so WAHA resolves the attachment server-side.
    One bounded retry, not a loop — a message that still has nothing
    fetchable after that is treated as unavailable, not retried forever.
    """
    logger.info(
        "jawara.input.resolve_started",
        extra={**log_context, "reply_message_id": message_id},
    )

    data = await waha.get_message(session, chat_id, message_id)
    if data is None:
        logger.warning(
            "jawara.input.resolve_failed",
            extra={**log_context, "reply_message_id": message_id, "reason": "quoted_message_unavailable"},
        )
        return ResolvedQuote(degraded=("quoted_message_unavailable",))

    text = _text_of(data)
    image = image_attachment_of(data)
    degraded: list[str] = []

    if image is not None:
        logger.info(
            "jawara.input.media_detected",
            extra={**log_context, "reply_message_id": message_id, "media_type": "image"},
        )
    elif data.get("hasMedia") is True:
        # WAHA says media exists but gave no `media.url`/`media.data` to use —
        # ask it to resolve the attachment server-side instead of guessing.
        logger.info(
            "jawara.input.media_download_started",
            extra={**log_context, "reply_message_id": message_id, "resolution_source": "downloadMedia_fallback"},
        )
        retried = await waha.get_message(session, chat_id, message_id, download_media=True)
        if retried is not None:
            image = image_attachment_of(retried)
            if text is None:
                text = _text_of(retried)

        if image is not None:
            logger.info(
                "jawara.input.media_downloaded",
                extra={**log_context, "reply_message_id": message_id, "media_type": "image"},
            )
        else:
            logger.warning(
                "jawara.input.resolve_failed",
                extra={**log_context, "reply_message_id": message_id, "reason": "reply_media_unavailable"},
            )
            degraded.append("reply_media_unavailable")

    logger.info(
        "jawara.input.resolve_completed",
        extra={
            **log_context,
            "reply_message_id": message_id,
            "has_text": bool(text),
            "has_media": image is not None,
        },
    )
    return ResolvedQuote(text=text, image=image, degraded=tuple(degraded))
