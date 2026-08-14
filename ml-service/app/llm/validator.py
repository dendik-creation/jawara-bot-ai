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

# URL-safety vocabulary — deliberately distinct wording from the fact/hoax
# markers above (`!link` false-positive fix, task Part 2). A phishing scan
# and a factual claim answer different questions: "is this destination
# dangerous" is not "is this claim true", so a legitimate-but-unverified URL
# must never render as "HOAX", and an unresolved fact claim must never render
# as "BERBAHAYA". `URL_STATUS_UNKNOWN` is its own marker, not a reuse of
# `URL_STATUS_MEDIUM` — "we have no evidence either way" and "we found
# something to be cautious about" are different claims to make to a user.
URL_STATUS_LOW = "🟢 *AMAN*"
URL_STATUS_MEDIUM = "🟡 *PERLU WASPADA*"
URL_STATUS_HIGH = "🔴 *BERBAHAYA*"
URL_STATUS_UNKNOWN = "⚪ *BELUM TERVERIFIKASI*"

URL_STATUS_MARKERS = (URL_STATUS_LOW, URL_STATUS_MEDIUM, URL_STATUS_HIGH, URL_STATUS_UNKNOWN)

# Every marker the parser accepts as *a* status line, across both
# vocabularies — which one is *correct* for a given (risk, category) pair is
# `status_for_risk`'s job, checked separately by `status_mismatch` below.
ALL_STATUS_MARKERS = STATUS_MARKERS + URL_STATUS_MARKERS

# Categories that answer "is this destination dangerous" rather than "is this
# claim true" — the only ones that get the URL vocabulary above.
URL_SAFETY_CATEGORIES = frozenset({"PHISHING_LINK"})

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


def validate_response(text: str, *, expected_status: str | None = None) -> ValidatedResponse:
    """Parse and check one generated reply. Never raises.

    `expected_status` is the deterministic verdict — `status_for_risk(risk,
    category=...)` — computed by the caller from the URL-safety engine or the
    knowledge-base risk assessment. When given, the LLM's own status line
    must match it exactly: a mismatch is a `status_mismatch` *violation*, not
    a warning, which is what makes it non-negotiable. `generate()`
    (`app/api/v1/endpoints/inference.py`) already treats any violation as
    "discard this reply, use the deterministic composer instead" — reusing
    that path is the entire enforcement mechanism (task Part 1.2): there is
    no separate "reject" branch to forget to wire up.
    """
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
        if candidate in ALL_STATUS_MARKERS:
            status = candidate
            body_start = index + 1
        else:
            violations.append("missing_status_indicator")
            body_start = index
        break

    if expected_status is not None and status and status != expected_status:
        # The model chose a real, well-formed status marker — just not the
        # one the deterministic risk assessment computed. This is exactly the
        # failure this fix targets: risk_level=UNKNOWN, LLM says HIGH (or the
        # reverse). Structurally valid is not good enough to dispatch.
        violations.append("status_mismatch")

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


def status_for_risk(risk_level: str, *, category: str | None = None) -> str:
    """The one authoritative mapping from computed `risk_level` to status marker.

    This is the deterministic source of truth the task requires: the LLM may
    explain a result, never choose it. Two vocabularies, picked by
    `category` — URL safety (`PHISHING_LINK`) and everything else
    (fact/hoax verification, `!cek`). They must stay semantically distinct
    (task Part 2): UNKNOWN is never HIGH, and for a URL, UNKNOWN is never
    rendered as HOAX-vocabulary at all.

    Fact/hoax UNKNOWN still folds into the amber "belum terverifikasi"
    marker (unchanged, pre-existing behaviour) — "we could not verify this"
    must never be shown to a user as "this is safe". URL safety gets its own
    dedicated ⚪ UNKNOWN marker instead of reusing MEDIUM's, because "no
    evidence either way" and "found something to be cautious about" are
    different claims about a link.
    """
    normalised = (risk_level or "").upper()

    if (category or "").upper() in URL_SAFETY_CATEGORIES:
        if normalised == "HIGH":
            return URL_STATUS_HIGH
        if normalised == "LOW":
            return URL_STATUS_LOW
        if normalised == "MEDIUM":
            return URL_STATUS_MEDIUM
        return URL_STATUS_UNKNOWN

    if normalised == "HIGH":
        return STATUS_HIGH
    if normalised == "LOW":
        return STATUS_SAFE
    return STATUS_MEDIUM
