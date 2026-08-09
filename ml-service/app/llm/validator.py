"""Output contract enforcement for generated WhatsApp replies.

The four-section structure in `01_LLM_System_Prompt.md` is a promise to the user,
not a formatting preference: the status indicator is how someone reads the
verdict at a glance, and the forwardable block is the feature that spreads the
correction to the family group. An LLM that drops a section produces a reply that
looks fine to the model and broken to a 70-year-old.

So the structure is checked in code before dispatch. Failures are *violations*
(the response is rejected and rebuilt deterministically). Style problems that do
not break the contract — an explanation longer than four sentences — are
*warnings*: logged, not grounds for throwing away an otherwise good answer.
"""

import re
from dataclasses import dataclass, field

STATUS_HIGH = "🔴 *HOAKS / BAHAYA TINGGI*"
STATUS_MEDIUM = "🟡 *PERLU WASPADA / BELUM TERVERIFIKASI*"
STATUS_SAFE = "🟢 *FAKTA RESMI / AMAN*"

STATUS_MARKERS = (STATUS_HIGH, STATUS_MEDIUM, STATUS_SAFE)

MAX_EXPLANATION_SENTENCES = 4

_URL = re.compile(r"https?://\S+")
_SENTENCE_END = re.compile(r"[.!?](?:\s|$)")
_REFERENCE_LABEL = re.compile(r"^\**\s*(sumber|referensi|source)\b", re.IGNORECASE)


@dataclass(frozen=True)
class ValidatedResponse:
    """Parsed four-section reply."""

    text: str
    status: str = ""
    explanation: str = ""
    reference: str = ""
    forward: str = ""
    violations: tuple[str, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def is_valid(self) -> bool:
        return not self.violations

    def as_sections(self) -> dict[str, str]:
        return {
            "status": self.status,
            "explanation": self.explanation,
            "reference": self.reference,
            "forward": self.forward,
        }


def validate_response(text: str) -> ValidatedResponse:
    """Parse and check one generated reply. Never raises."""
    violations: list[str] = []
    warnings: list[str] = []

    stripped = (text or "").strip()
    if not stripped:
        return ValidatedResponse(text="", violations=("empty_response",))

    lines = stripped.splitlines()

    # --- Part 1: status indicator ---------------------------------------
    status = ""
    body_start = 0
    for index, line in enumerate(lines):
        if not line.strip():
            continue
        candidate = line.strip()
        if candidate in STATUS_MARKERS:
            status = candidate
            body_start = index + 1
        else:
            violations.append("missing_status_indicator")
            body_start = index
        break

    # --- Part 4: forwardable block (final paragraph) ---------------------
    # The last blank-line-separated paragraph is the candidate. Taking the
    # paragraph rather than "the trailing run of `>` lines" is what lets a
    # half-quoted block report *why* it is wrong instead of looking absent.
    end = len(lines)
    while end > body_start and not lines[end - 1].strip():
        end -= 1

    forward_start = end
    while forward_start > body_start and lines[forward_start - 1].strip():
        forward_start -= 1

    forward_lines = [line for line in lines[forward_start:end] if line.strip()]
    quoted = [line for line in forward_lines if line.strip().startswith(">")]

    if not quoted:
        violations.append("missing_forwardable_message")
        forward_lines = []
    elif len(quoted) != len(forward_lines):
        violations.append("forwardable_message_not_quoted")

    # --- Part 3: exactly one official reference link ---------------------
    body_lines = lines[body_start:forward_start]
    reference_index = None
    for index in range(len(body_lines) - 1, -1, -1):
        if _URL.search(body_lines[index]):
            reference_index = index
            break

    if reference_index is None:
        violations.append("missing_reference_link")
        reference = ""
        explanation_lines = body_lines
    else:
        # A "Sumber Resmi:" style label above the link belongs to the reference
        # section; an ordinary sentence above it belongs to the explanation.
        block_start = reference_index
        if reference_index > 0 and _REFERENCE_LABEL.match(body_lines[reference_index - 1].strip()):
            block_start = reference_index - 1
        reference = "\n".join(
            line for line in body_lines[block_start : reference_index + 1] if line.strip()
        ).strip()
        explanation_lines = body_lines[:block_start]
        if len(_URL.findall("\n".join(body_lines))) > 1:
            violations.append("multiple_reference_links")

    # --- Part 2: empathetic explanation ----------------------------------
    explanation = "\n".join(explanation_lines).strip()
    if not explanation:
        violations.append("missing_explanation")
    elif len(_SENTENCE_END.findall(explanation)) > MAX_EXPLANATION_SENTENCES:
        warnings.append("explanation_over_four_sentences")

    return ValidatedResponse(
        text=stripped,
        status=status,
        explanation=explanation,
        reference=reference,
        forward="\n".join(forward_lines),
        violations=tuple(dict.fromkeys(violations)),
        warnings=tuple(warnings),
    )


def status_for_risk(risk_level: str) -> str:
    """Map `risk_level_enum` onto the documented status indicator.

    UNKNOWN maps to the amber "belum terverifikasi" marker, never to green:
    "we could not verify this" must never be shown to a user as "this is safe".
    """
    normalised = (risk_level or "").upper()
    if normalised == "HIGH":
        return STATUS_HIGH
    if normalised == "LOW":
        return STATUS_SAFE
    return STATUS_MEDIUM
