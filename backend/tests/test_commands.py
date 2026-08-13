"""Strict `!command` parsing (JAWARA Strict WhatsApp Command System).

Deterministic and LLM-free: a command is recognised if and only if the first
non-whitespace token is `!` plus one of the four allowlisted names. Everything
else — no `!` at all, or an unknown `!name` — must never be mistaken for one.
"""

import pytest

from app.pipeline import commands
from app.pipeline.commands import parse_command


def test_known_commands_are_exactly_the_four_public_ones():
    assert commands.KNOWN_COMMANDS == {"cek", "link", "bantu", "status"}


# --------------------------------------------------------------------------
# Valid commands
# --------------------------------------------------------------------------


def test_bare_cek_is_recognised_with_empty_args():
    result = parse_command("!cek")
    assert result.recognized is True
    assert result.command == "cek"
    assert result.args == ""


def test_cek_with_inline_text_carries_the_text_as_args():
    result = parse_command("!cek some claim")
    assert result.recognized is True
    assert result.command == "cek"
    assert result.args == "some claim"


def test_link_carries_the_url_as_args():
    result = parse_command("!link https://example.com")
    assert result.recognized is True
    assert result.command == "link"
    assert result.args == "https://example.com"


def test_bantu_is_recognised():
    assert parse_command("!bantu") == parse_command("!bantu")
    result = parse_command("!bantu")
    assert result.recognized is True
    assert result.command == "bantu"


def test_status_is_recognised():
    result = parse_command("!status")
    assert result.recognized is True
    assert result.command == "status"


# --------------------------------------------------------------------------
# Invalid commands — starts with `!`, but not an allowlisted name
# --------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["foo", "search", "ocr", "rag", "factcheck", "ai", "google", "qdrant"])
def test_unknown_command_names_are_rejected(name):
    result = parse_command(f"!{name}")
    assert result.recognized is False
    assert result.command == name  # normalised name is surfaced for logging


# --------------------------------------------------------------------------
# No command at all — must never be mistaken for one
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    ["Halo", "Halo JAWARA", "tolong cek ini", "", "   ", "Apa kabar?"],
)
def test_plain_text_is_not_a_command(text):
    result = parse_command(text)
    assert result.recognized is False
    assert result.command is None


def test_command_word_must_lead_the_message():
    """`!cek` appearing mid-sentence is not a command — natural language
    never gets reinterpreted as one."""
    result = parse_command("tolong !cek dong")
    assert result.recognized is False
    assert result.command is None


# --------------------------------------------------------------------------
# Case normalisation and whitespace tolerance
# --------------------------------------------------------------------------


@pytest.mark.parametrize("text", ["!CEK", "!Cek", "!cEk"])
def test_command_name_is_case_insensitive(text):
    result = parse_command(text)
    assert result.recognized is True
    assert result.command == "cek"


def test_link_case_insensitive():
    result = parse_command("!LINK https://example.com")
    assert result.recognized is True
    assert result.command == "link"
    assert result.args == "https://example.com"


def test_surrounding_whitespace_is_tolerated():
    result = parse_command("   !cek some text   ")
    assert result.recognized is True
    assert result.args == "some text"


def test_extra_internal_whitespace_before_args_is_trimmed():
    result = parse_command("!cek    some text")
    assert result.recognized is True
    assert result.args == "some text"
