"""Image-attachment detection shared by the current message and a replied-to one.

Split out of `orchestrator.py` so `input_resolver.py` can inspect a *replied*
message's WAHA payload with the exact same rules the current message already
uses — one definition of "this counts as an image", not two that could drift.
"""

import base64
import binascii
from dataclasses import dataclass
from typing import Any

_IMAGE_MIME_PREFIX = "image/"


@dataclass(frozen=True)
class ImageAttachment:
    """One image WAHA attached to a message, however that engine reports it."""

    mimetype: str
    filename: str
    url: str | None = None
    data: bytes | None = None


def attachment_names(payload: dict[str, Any]) -> list[str]:
    """Filenames WAHA reports for an attachment, across engine payload shapes."""
    names: list[str] = []
    for key in ("filename", "fileName"):
        value = payload.get(key)
        if isinstance(value, str):
            names.append(value)
    media = payload.get("media")
    if isinstance(media, dict):
        for key in ("filename", "fileName"):
            value = media.get(key)
            if isinstance(value, str):
                names.append(value)
    return names


def image_attachment_of(payload: dict[str, Any]) -> ImageAttachment | None:
    """The image attachment on this message, if any — across WAHA engine shapes.

    WAHA reports media two ways depending on its own `downloadMedia` setting:
    a `media.url` to fetch, or the bytes already inline as `media.data`
    (base64). Neither is assumed; either is accepted. `type == "image"` or an
    `image/*` mimetype both count as "this is a picture" — WEBJS and NOWEB
    spell the field slightly differently. Works on any WAHA message-shaped
    dict — the live webhook payload, or one fetched after the fact via
    `WahaClient.get_message()` for a replied-to message.

    Returns `None` for anything that isn't a fetchable image, including a
    payload that merely *claims* to be one but carries neither a URL nor
    inline bytes — there is nothing this pipeline could OCR from that.
    """
    media = payload.get("media")
    media = media if isinstance(media, dict) else {}
    mimetype = str(media.get("mimetype") or payload.get("mimetype") or "")
    is_image = mimetype.lower().startswith(_IMAGE_MIME_PREFIX) or payload.get("type") == "image"
    if not is_image:
        return None

    filename = str(
        media.get("filename")
        or media.get("fileName")
        or payload.get("filename")
        or payload.get("fileName")
        or "image"
    )
    url = media.get("url") if isinstance(media.get("url"), str) and media.get("url") else None
    data: bytes | None = None
    raw_data = media.get("data")
    if isinstance(raw_data, str) and raw_data:
        try:
            data = base64.b64decode(raw_data, validate=False)
        except (binascii.Error, ValueError):
            data = None

    if not url and not data:
        return None
    return ImageAttachment(mimetype=mimetype or "image/jpeg", filename=filename, url=url, data=data)
