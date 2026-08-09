"""Group behaviour: the bot answers when addressed, and stays quiet otherwise.

The payload shapes below are the ones WAHA actually produces (WEBJS engine,
normalised and raw `_data` spellings). Getting this wrong in either direction is
expensive: too strict and the bot never answers in a group, too loose and it
spams a family group until the number is banned.
"""

import pytest

from app.pipeline import group_policy
from app.pipeline.group_policy import decide, is_group_chat, sender_of, strip_bot_mentions

GROUP = "120363000000000000@g.us"
DIRECT = "6281111111111@c.us"
BOT_IDS = frozenset({"6287712032005@c.us", "249117464891485@lid"})
MEMBER = "6289999999999@c.us"


def group_message(**payload) -> dict:
    return {"id": "msg_1", "from": GROUP, "participant": MEMBER, **payload}


# --------------------------------------------------------------------------
# Chat classification and sender extraction
# --------------------------------------------------------------------------


def test_group_ids_are_recognised():
    assert is_group_chat(GROUP) is True
    assert is_group_chat(DIRECT) is False
    assert is_group_chat("249117464891485@lid") is False
    assert is_group_chat(None) is False


def test_sender_in_a_group_is_the_participant_not_the_group():
    assert sender_of(group_message(), GROUP) == MEMBER


def test_sender_falls_back_to_the_raw_author_field():
    payload = {"from": GROUP, "_data": {"author": MEMBER}}
    assert sender_of(payload, GROUP) == MEMBER


def test_sender_reads_wahas_serialised_jid_objects():
    payload = {"from": GROUP, "participant": {"_serialized": MEMBER, "user": "6289999999999"}}
    assert sender_of(payload, GROUP) == MEMBER


def test_sender_in_a_direct_chat_is_the_chat_itself():
    assert sender_of({"from": DIRECT}, DIRECT) == DIRECT


def test_group_sender_is_none_when_waha_omits_it():
    """Better no sender than silently attributing the message to the group."""
    assert sender_of({"from": GROUP}, GROUP) is None


# --------------------------------------------------------------------------
# The decision
# --------------------------------------------------------------------------


def test_direct_chat_always_gets_an_answer():
    decision = decide({"from": DIRECT}, DIRECT, "halo", BOT_IDS)

    assert decision.is_group is False
    assert decision.should_reply is True
    assert decision.reason == "direct_chat"


def test_group_message_that_does_not_address_the_bot_is_ignored():
    decision = decide(group_message(body="pagi semua"), GROUP, "pagi semua", BOT_IDS)

    assert decision.is_group is True
    assert decision.should_reply is False
    assert decision.reason == "not_addressed"
    assert decision.sender_id == MEMBER


def test_mention_by_phone_jid_triggers_a_reply():
    payload = group_message(mentionedIds=["6287712032005@c.us"])
    assert decide(payload, GROUP, "@6287712032005 cek ini", BOT_IDS).reason == "mention"


def test_mention_by_lid_twin_triggers_a_reply():
    """One WhatsApp account, two JIDs — a mention may carry either."""
    payload = group_message(mentionedIds=["249117464891485@lid"])
    assert decide(payload, GROUP, "cek ini", BOT_IDS).should_reply is True


def test_mention_in_the_raw_data_field_triggers_a_reply():
    payload = group_message(_data={"mentionedJidList": ["6287712032005@c.us"]})
    assert decide(payload, GROUP, "cek ini", BOT_IDS).reason == "mention"


def test_mention_text_triggers_even_when_the_metadata_is_missing():
    """The visible `@62…` survives WAHA version drift; the metadata field may not."""
    decision = decide(group_message(), GROUP, "@6287712032005 tolong cek", BOT_IDS)

    assert decision.should_reply is True
    assert decision.reason == "mention_text"


def test_mentioning_someone_else_does_not_trigger():
    payload = group_message(mentionedIds=["6280000000000@c.us"])
    assert decide(payload, GROUP, "@6280000000000 lihat ini", BOT_IDS).should_reply is False


def test_reply_to_the_bot_triggers():
    payload = group_message(replyTo={"id": "msg_0", "participant": "6287712032005@c.us"})
    decision = decide(payload, GROUP, "benarkah ini?", BOT_IDS)

    assert decision.reason == "reply_to_bot"
    assert decision.quoted_message_id == "msg_0"


def test_reply_flagged_only_as_from_me_triggers():
    payload = group_message(replyTo={"id": "msg_0", "fromMe": True})
    assert decide(payload, GROUP, "benarkah ini?", BOT_IDS).reason == "reply_to_bot"


def test_reply_to_another_member_does_not_trigger():
    payload = group_message(replyTo={"id": "msg_0", "participant": MEMBER})
    assert decide(payload, GROUP, "setuju", BOT_IDS).should_reply is False


def test_unknown_bot_identity_keeps_the_bot_quiet_in_groups():
    """A failed identity lookup must fail silent, never fail spammy."""
    payload = group_message(mentionedIds=["6287712032005@c.us"])
    assert decide(payload, GROUP, "@6287712032005 cek", frozenset()).should_reply is False


def test_trigger_can_be_disabled_for_a_test_group():
    decision = decide(group_message(), GROUP, "pagi semua", BOT_IDS, require_trigger=False)

    assert decision.should_reply is True
    assert decision.reason == "trigger_disabled"


# --------------------------------------------------------------------------
# Mention stripping
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "body,expected",
    [
        ("@6287712032005 tolong cek kabar ini", "tolong cek kabar ini"),
        ("tolong cek @6287712032005", "tolong cek"),
        ("@249117464891485 cek", "cek"),
        ("@6287712032005", ""),
        ("tidak ada mention", "tidak ada mention"),
    ],
)
def test_bot_mention_is_removed_before_analysis(body, expected):
    """The mention is addressing, not content — and a bare number trips fraud rules."""
    assert strip_bot_mentions(body, BOT_IDS) == expected


def test_other_peoples_mentions_survive_stripping():
    assert strip_bot_mentions("@6280000000000 cek", BOT_IDS) == "@6280000000000 cek"


def test_group_suffix_is_the_documented_one():
    assert group_policy.GROUP_SUFFIX == "@g.us"
