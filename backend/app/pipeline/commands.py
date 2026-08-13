"""Strict `!command` parsing for a `@JAWARA` mention (JAWARA Strict WhatsApp Command System).

Mention = activation. Command = intent. A group message that reaches this
module has already been decided as "addressed to the bot" by `group_policy`;
what happens next must not depend on an LLM guessing what the user wanted.
Only the four names in `KNOWN_COMMANDS` may ever select a pipeline stage —
anything else, including a bare mention or free-form natural language, is
routed to a static guidance reply by the caller and never reaches OCR, RAG,
URL scanning or the ML classifier.

This module only parses; it does not know about Celery, OCR, or WAHA. That
keeps the allowlist testable without stubbing the rest of the pipeline, and
keeps the orchestrator the single place that decides what a recognised
command actually does.
"""

import re
from dataclasses import dataclass

COMMAND_PREFIX = "!"

CEK = "cek"
LINK = "link"
BANTU = "bantu"
STATUS = "status"

# The allowlist. Nothing outside this set is ever dispatched — no
# `getattr(service, name)`, no dynamic lookup by user-provided string.
KNOWN_COMMANDS: frozenset[str] = frozenset({CEK, LINK, BANTU, STATUS})

_COMMAND_LINE = re.compile(r"^!(\S+)\s*(.*)$", re.DOTALL)


@dataclass(frozen=True)
class ParsedCommand:
    """Result of parsing the text that follows a bot mention.

    `command` is `None` only when the text carries no `!` prefix at all — a
    bare mention or plain conversation. `recognized` is `False` for both that
    case and an unknown `!name`; callers branch on `command is None` first to
    tell the two apart for the right guidance copy.
    """

    recognized: bool
    command: str | None
    args: str


def parse_command(text: str) -> ParsedCommand:
    """Parse `text` — the message body with the bot mention already stripped.

    Deterministic, regex-only, no natural-language interpretation: a command
    is recognised if and only if the first non-whitespace token is `!` plus
    one of `KNOWN_COMMANDS`, case-insensitively. `!cek` buried mid-sentence
    ("tolong !cek dong") is not a command — it must lead the message.
    """
    stripped = text.strip()
    if not stripped.startswith(COMMAND_PREFIX):
        return ParsedCommand(recognized=False, command=None, args="")

    match = _COMMAND_LINE.match(stripped)
    if not match:
        return ParsedCommand(recognized=False, command=None, args="")

    name = match.group(1).strip().lower()
    args = match.group(2).strip()
    if name not in KNOWN_COMMANDS:
        return ParsedCommand(recognized=False, command=name, args=args)
    return ParsedCommand(recognized=True, command=name, args=args)
