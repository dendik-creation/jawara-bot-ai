"""Text normalisation for WhatsApp-style Indonesian input.

Stage 4 of the pipeline ([[Implement Text Normalizer]]). Output feeds the intent
router and, later, the embedding request — both need the *same* string for the
same message, so every transform here is pure and ordering-stable: no locale
lookups, no random iteration, no time.

Deliberately not done here:

- OCR text (`ml-service` owns image input; this module never sees pixels)
- stemming / stopword removal — the RAG query works better with the sentence
  intact, and Indonesian stemming would need Sastrawi at the gateway
- destroying URLs: they are masked before casefolding and restored afterwards,
  because the URL extractor and the LLM both need the original characters
"""

import re
import unicodedata
from dataclasses import dataclass, field

# Zero-width marks, bidi controls, soft hyphen, BOM. Invisible in WhatsApp, but
# they split words for anything that tokenises — a scammer writing "b​ansos"
# defeats a naive keyword rule.
_INVISIBLE = re.compile("[­​-‏‪-‮⁠-⁤﻿]")

# Emoji and pictographic blocks. Stripped from the analysed text but counted, so
# a downstream rule can still see "this message was emoji-heavy".
_EMOJI = re.compile(
    "["
    "\U0001f1e6-\U0001f1ff"  # flags
    "\U0001f300-\U0001f5ff"  # symbols & pictographs
    "\U0001f600-\U0001f64f"  # emoticons
    "\U0001f680-\U0001f6ff"  # transport & map
    "\U0001f700-\U0001faff"  # supplemental symbols
    "☀-➿"  # misc symbols & dingbats
    "︎️"  # variation selectors
    "]"
)

_URL = re.compile(r"(?:https?://|www\.)[^\s<>\"']+", re.IGNORECASE)
_URL_PLACEHOLDER = "\x00url{}\x00"

# WhatsApp markdown emphasis: *bold*, _italic_, ~strike~, ```mono```.
_MARKDOWN = re.compile(r"[*_~`]+")

# Three or more identical letters collapse to one ("bagusss" -> "bagus").
# Two is left alone: doubled vowels/consonants are ordinary Indonesian
# ("maaf", "massa", "saat").
_REPEATED_CHAR = re.compile(r"(\w)\1{2,}", re.UNICODE)
_REPEATED_PUNCT = re.compile(r"([!?.,])\1+")
_WHITESPACE = re.compile(r"\s+")

# Slang/abbreviation map. Word-boundary replacements only, applied after
# casefolding. Kept small and high-frequency on purpose: an aggressive
# dictionary starts mangling real words, and every entry here has to be worth
# the risk of a false rewrite.
SLANG: dict[str, str] = {
    "yg": "yang",
    "dgn": "dengan",
    "dg": "dengan",
    "utk": "untuk",
    "tdk": "tidak",
    "gak": "tidak",
    "ga": "tidak",
    "gk": "tidak",
    "nggak": "tidak",
    "enggak": "tidak",
    "engga": "tidak",
    "sdh": "sudah",
    "udh": "sudah",
    "udah": "sudah",
    "blm": "belum",
    "blum": "belum",
    "bkn": "bukan",
    "krn": "karena",
    "karna": "karena",
    "klo": "kalau",
    "kalo": "kalau",
    "gmn": "bagaimana",
    "gimana": "bagaimana",
    "gmna": "bagaimana",
    "bgt": "sangat",
    "banget": "sangat",
    "sy": "saya",
    "aq": "saya",
    "aku": "saya",
    "bpk": "bapak",
    "org": "orang",
    "orng": "orang",
    "hp": "handphone",
    "rek": "rekening",
    "trf": "transfer",
    "tf": "transfer",
    "jt": "juta",
    "rb": "ribu",
    "bnr": "benar",
    "bener": "benar",
    "info": "informasi",
    "sblm": "sebelum",
    "spt": "seperti",
    "dlm": "dalam",
    "jgn": "jangan",
    "bs": "bisa",
    "bsa": "bisa",
}

# Left out on purpose, despite being common: "dr" (dari vs dokter), "no"
# (nomor vs the English word), "sm" (sama vs a name). An expansion that guesses
# wrong changes the meaning of a message the pipeline is about to classify.
AMBIGUOUS_ABBREVIATIONS = frozenset({"dr", "no", "sm", "jg", "dl"})

_SLANG_PATTERN = re.compile(
    r"\b(" + "|".join(sorted(SLANG, key=len, reverse=True)) + r")\b",
)


@dataclass(frozen=True)
class NormalizedText:
    """Result of normalising one message body.

    `text` is what classification and embedding consume; `raw` is what the audit
    log and the LLM prompt quote back to the user, because a reply that quotes a
    mangled version of their own message reads as broken.
    """

    raw: str
    text: str
    urls_masked: int = 0
    emoji_count: int = 0
    was_truncated: bool = False
    slang_replaced: tuple[str, ...] = field(default_factory=tuple)

    @property
    def is_empty(self) -> bool:
        return not self.text


# Guard against a pathological forward (WhatsApp allows ~65k chars). Anything
# past this adds embedding cost without adding signal.
MAX_LENGTH = 4000


def normalize_text(raw: str | None, max_length: int = MAX_LENGTH) -> NormalizedText:
    """Normalise one WhatsApp message body. Deterministic for identical input."""
    if not raw:
        return NormalizedText(raw=raw or "", text="")

    truncated = len(raw) > max_length
    working = raw[:max_length] if truncated else raw

    working = unicodedata.normalize("NFKC", working)
    working = _INVISIBLE.sub("", working)

    # Mask URLs before any casefolding/character surgery: paths and query strings
    # are case-sensitive and full of characters this function squashes.
    urls: list[str] = []

    def _mask(match: re.Match[str]) -> str:
        urls.append(match.group(0))
        return _URL_PLACEHOLDER.format(len(urls) - 1)

    working = _URL.sub(_mask, working)

    emoji_count = len(_EMOJI.findall(working))
    working = _EMOJI.sub(" ", working)
    working = _MARKDOWN.sub(" ", working)

    working = working.casefold()
    working = _REPEATED_CHAR.sub(r"\1", working)
    working = _REPEATED_PUNCT.sub(r"\1", working)

    replaced: list[str] = []

    def _expand(match: re.Match[str]) -> str:
        token = match.group(1)
        expansion = SLANG[token]
        if expansion != token:
            replaced.append(token)
        return expansion

    working = _SLANG_PATTERN.sub(_expand, working)

    for index, url in enumerate(urls):
        working = working.replace(_URL_PLACEHOLDER.format(index), url)

    working = _WHITESPACE.sub(" ", working).strip()

    return NormalizedText(
        raw=raw,
        text=working,
        urls_masked=len(urls),
        emoji_count=emoji_count,
        was_truncated=truncated,
        slang_replaced=tuple(replaced),
    )
