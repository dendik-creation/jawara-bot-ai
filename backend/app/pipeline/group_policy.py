"""When may the bot speak in a WhatsApp group?

In a one-to-one chat the answer is always: the person messaged the bot, so the
bot answers. A group is different. Replying to every message in a family group
is spam, it drowns the conversation the bot is supposed to protect, and WhatsApp
bans numbers that behave that way.

So in a group the bot stays silent unless it was actually addressed —
**mentioned** (`@62…`) or **replied to**. That is the interaction
01_Overview/04_How_it_Works.md §101 describes: forward, reply, or mention.

This module is pure: payload in, decision out. WAHA's payload shape differs
between engines and versions, so every field is read defensively across the
spellings seen in the wild rather than assuming one.
"""

import re
from dataclasses import dataclass
from typing import Any

GROUP_SUFFIX = "@g.us"

# `62812…@c.us`, `2491174…@lid` — the JID's local part is what a mention carries.
_JID_LOCAL = re.compile(r"^(\d+)")


@dataclass(frozen=True)
class GroupDecision:
    """Whether to answer, and what the bot is answering to."""

    is_group: bool
    should_reply: bool
    reason: str
    sender_id: str | None = None
    quoted_message_id: str | None = None


def is_group_chat(chat_id: str | None) -> bool:
    return bool(chat_id) and chat_id.endswith(GROUP_SUFFIX)


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, (str, dict)) and value:
        return [value]
    return []


def _jid_text(value: Any) -> str:
    """A JID out of either a bare string or WAHA's `{_serialized: …}` object."""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("_serialized", "id", "user"):
            nested = value.get(key)
            if isinstance(nested, str):
                return nested
            if isinstance(nested, dict):
                serialized = nested.get("_serialized")
                if isinstance(serialized, str):
                    return serialized
    return ""


def _local_part(jid: str) -> str:
    match = _JID_LOCAL.match(jid.strip())
    return match.group(1) if match else ""


def _data_of(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("_data")
    return data if isinstance(data, dict) else {}


def sender_of(payload: dict[str, Any], chat_id: str | None) -> str | None:
    """Who actually typed the message.

    In a group `from` is the group itself; the human is in `participant`
    (WAHA's normalised field) or `author` (raw WEBJS). In a direct chat the
    sender and the chat are the same thing.
    """
    data = _data_of(payload)
    for key in ("participant", "author"):
        jid = _jid_text(payload.get(key)) or _jid_text(data.get(key))
        if jid:
            return jid
    return None if is_group_chat(chat_id) else chat_id


def mentioned_jids(payload: dict[str, Any]) -> list[str]:
    data = _data_of(payload)
    raw: list[Any] = []
    for key in ("mentionedIds", "mentionedJidList", "groupMentions"):
        raw.extend(_as_list(payload.get(key)))
        raw.extend(_as_list(data.get(key)))
    return [jid for jid in (_jid_text(item) for item in raw) if jid]


def quoted_message_id(payload: dict[str, Any]) -> str | None:
    """Id of the message this one replies to, if any."""
    data = _data_of(payload)
    reply_to = payload.get("replyTo")
    if isinstance(reply_to, dict):
        candidate = _jid_text(reply_to.get("id")) or reply_to.get("id")
        if isinstance(candidate, str) and candidate:
            return candidate
    if isinstance(reply_to, str) and reply_to:
        return reply_to
    for key in ("quotedStanzaID", "quotedMsgId"):
        candidate = data.get(key)
        if isinstance(candidate, str) and candidate:
            return candidate
    return None


def _quoted_author(payload: dict[str, Any]) -> str | None:
    data = _data_of(payload)
    reply_to = payload.get("replyTo")
    if isinstance(reply_to, dict):
        jid = _jid_text(reply_to.get("participant")) or _jid_text(reply_to.get("from"))
        if jid:
            return jid
        # Some versions only say whether the quoted message was ours.
        if reply_to.get("fromMe") is True:
            return "__self__"
    for key in ("quotedParticipant", "quotedRemoteJid"):
        jid = _jid_text(data.get(key))
        if jid:
            return jid
    quoted = payload.get("quotedMsg") or data.get("quotedMsg")
    if isinstance(quoted, dict) and quoted.get("fromMe") is True:
        return "__self__"
    return None


def strip_bot_mentions(body: str, bot_ids: frozenset[str]) -> str:
    """Remove the `@62…` that summoned the bot from the text to be analysed.

    The mention is addressing, not content. Left in, it reaches the normalizer,
    the keyword lexicon and the LLM prompt as if the user had written a phone
    number — which is exactly the kind of token the fraud rules look at.
    """
    cleaned = body
    for local in {local for local in (_local_part(jid) for jid in bot_ids) if local}:
        cleaned = cleaned.replace(f"@{local}", " ")
    return " ".join(cleaned.split())


def decide(
    payload: dict[str, Any],
    chat_id: str | None,
    body: str,
    bot_ids: frozenset[str],
    require_trigger: bool = True,
) -> GroupDecision:
    """Answer or stay quiet, with the reason recorded either way.

    `bot_ids` are the JIDs this session answers to (`…@c.us` and the `@lid`
    twin). When it is empty the bot cannot recognise its own name, and in a
    group it then stays **silent** rather than replying to everything — the
    failure mode of a broken lookup must be quiet, not spam.
    """
    quoted_id = quoted_message_id(payload)

    if not is_group_chat(chat_id):
        return GroupDecision(
            is_group=False,
            should_reply=True,
            reason="direct_chat",
            sender_id=sender_of(payload, chat_id),
            quoted_message_id=quoted_id,
        )

    sender = sender_of(payload, chat_id)

    if not require_trigger:
        return GroupDecision(True, True, "trigger_disabled", sender, quoted_id)

    bot_locals = {local for local in (_local_part(jid) for jid in bot_ids) if local}

    for jid in mentioned_jids(payload):
        if jid in bot_ids or (_local_part(jid) and _local_part(jid) in bot_locals):
            return GroupDecision(True, True, "mention", sender, quoted_id)

    # Text fallback: mention metadata is the field most likely to be missing or
    # renamed between WAHA versions, while the visible `@62…` in the body is not.
    for local in bot_locals:
        if f"@{local}" in body:
            return GroupDecision(True, True, "mention_text", sender, quoted_id)

    quoted_author = _quoted_author(payload)
    if quoted_author == "__self__" or (quoted_author and quoted_author in bot_ids):
        return GroupDecision(True, True, "reply_to_bot", sender, quoted_id)
    if quoted_author and _local_part(quoted_author) in bot_locals:
        return GroupDecision(True, True, "reply_to_bot", sender, quoted_id)

    return GroupDecision(True, False, "not_addressed", sender, quoted_id)
