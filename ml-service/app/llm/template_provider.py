"""Deterministic offline composer for the four-section reply.

Two jobs:

1. **Default provider** when no vendor key is configured, so the whole pipeline —
   webhook to WhatsApp reply — runs end to end offline, in CI, and in a demo
   without an internet connection.
2. **Repair path** when a real LLM returns something that fails the output
   contract. `01_LLM_System_Prompt.md` promises the user four sections; a broken
   generation must be replaced, not forwarded.

It is templating, not generation: wording comes from the retrieved fact
explanation and from per-category safety advice written to match the tone of the
documented few-shot examples ("Bapak/Ibu", no blame, one concrete action). It
will never phrase something the knowledge base did not contain, which is exactly
why it is safe as a fallback.
"""

import re

from app.llm.base import LlmProvider
from app.llm.prompt import GenerationRequest
from app.llm.validator import status_for_risk

# One official reference per category, used when the knowledge base match does
# not carry its own source URL.
DEFAULT_REFERENCES: dict[str, str] = {
    "HEALTH_HOAX": "https://kemkes.go.id/",
    "GENERAL_NEWS": "https://turnbackhoax.id/",
    "PHISHING_LINK": "https://patrolisiber.id/",
    "FINANCIAL_FRAUD": "https://cekrekening.id/",
    "FILE_APK": "https://patrolisiber.id/",
    "UNKNOWN": "https://turnbackhoax.id/",
}

# Advice sentence appended per category. Kept to one sentence: the contract caps
# the explanation at four short sentences and the fact explanation already uses
# most of that budget.
CATEGORY_ADVICE: dict[str, str] = {
    "HEALTH_HOAX": (
        "Untuk keluhan kesehatan, mohon selalu periksakan ke dokter atau Puskesmas terdekat ya."
    ),
    "GENERAL_NEWS": (
        "Sebelum meneruskan kabar ini, ada baiknya Bapak/Ibu memeriksanya di sumber resmi terlebih dahulu."
    ),
    "PHISHING_LINK": (
        "Mohon jangan memasukkan data pribadi, KTP, atau kode OTP di tautan yang tidak dikenal."
    ),
    "FINANCIAL_FRAUD": (
        "Mohon jangan mentransfer uang apa pun sebelum memastikan langsung ke pihak resminya."
    ),
    "FILE_APK": (
        "Mohon jangan mengunduh atau memasang file `.apk` yang dikirim lewat WhatsApp, "
        "meskipun dari nomor yang dikenal."
    ),
}

RISK_OPENING: dict[str, str] = {
    "HIGH": "Bapak/Ibu, mohon berhati-hati — informasi ini terindikasi berbahaya.",
    "MEDIUM": "Bapak/Ibu, informasi ini belum dapat kami pastikan kebenarannya.",
    "LOW": "Bapak/Ibu, sejauh pemeriksaan kami informasi ini aman.",
    "UNKNOWN": "Bapak/Ibu, kami belum dapat memastikan kebenaran informasi ini.",
}

FORWARD_TITLE_SAFE = "> *Informasi untuk Keluarga:*"
FORWARD_TITLE_WARNING = "> *Pesan Penting untuk Keluarga:*"

_SENTENCE = re.compile(r"(?<=[.!?])\s+")
_MAX_CONTEXT_SENTENCES = 2


def _first_sentences(text: str, count: int) -> str:
    sentences = [part.strip() for part in _SENTENCE.split((text or "").strip()) if part.strip()]
    return " ".join(sentences[:count])


class TemplateProvider(LlmProvider):
    name = "template-composer"
    version = "v1"

    @property
    def is_offline(self) -> bool:
        return True

    async def generate(self, request: GenerationRequest) -> str:
        return self.compose(request)

    def compose(self, request: GenerationRequest) -> str:
        category = (request.category or "UNKNOWN").upper()
        status = status_for_risk(request.risk_level, category=category)

        explanation_parts = [RISK_OPENING.get(request.risk_level.upper(), RISK_OPENING["UNKNOWN"])]

        top = request.context[0] if request.context else None
        if top:
            summary = _first_sentences(str(top.get("fact_explanation", "")), _MAX_CONTEXT_SENTENCES)
            if summary:
                explanation_parts.append(summary)
        elif request.url_verdicts:
            explanation_parts.append(self._url_sentence(request.url_verdicts))
        else:
            explanation_parts.append(
                "Kami belum menemukan rujukan resmi yang membahas informasi ini, "
                "jadi mohon jangan diteruskan dulu."
            )

        explanation_parts.append(CATEGORY_ADVICE.get(category, CATEGORY_ADVICE["GENERAL_NEWS"]))

        reference = ""
        if top and top.get("source_url"):
            reference = str(top["source_url"])
        else:
            reference = DEFAULT_REFERENCES.get(category, DEFAULT_REFERENCES["UNKNOWN"])

        title = FORWARD_TITLE_WARNING if status != status_for_risk("LOW", category=category) else FORWARD_TITLE_SAFE
        forward_body = self._forward_body(request, category, status)

        return (
            f"{status}\n\n"
            f"{' '.join(explanation_parts)}\n\n"
            f"Sumber Resmi:\n{reference}\n\n"
            f"{title}\n{forward_body}"
        )

    def _url_sentence(self, url_verdicts: list[dict[str, object]]) -> str:
        flagged = [verdict for verdict in url_verdicts if str(verdict.get("risk")) == "HIGH"]
        if flagged:
            return (
                "Tautan di dalam pesan tersebut terdeteksi berbahaya oleh layanan keamanan "
                "dan berisiko mencuri data pribadi Bapak/Ibu."
            )
        unknown = [verdict for verdict in url_verdicts if str(verdict.get("risk")) in {"UNKNOWN", "MEDIUM"}]
        if unknown:
            return (
                "Tautan di dalam pesan tersebut belum dapat dipastikan keamanannya, "
                "sehingga sebaiknya tidak dibuka dulu."
            )
        return "Tautan di dalam pesan tersebut tidak terdeteksi berbahaya, namun tetap mohon berhati-hati."

    def _forward_body(self, request: GenerationRequest, category: str, status: str) -> str:
        top = request.context[0] if request.context else None
        if top:
            claim = _first_sentences(str(top.get("claim_text", "")), 1)
            verdict = str(top.get("verdict", "UNVERIFIED"))
            if verdict == "FACT":
                line = f"Kabar berikut sudah dipastikan benar oleh sumber resmi: {claim}"
            elif verdict == "HOAX":
                line = f"Mohon berhati-hati, kabar berikut dinyatakan hoaks oleh sumber resmi: {claim}"
            else:
                line = f"Mohon berhati-hati, kabar berikut belum terbukti kebenarannya: {claim}"
        elif status == status_for_risk("HIGH", category=category):
            line = "Mohon berhati-hati, pesan yang beredar berikut terindikasi penipuan."
        else:
            line = "Mohon berhati-hati, pesan yang beredar berikut belum dapat dipastikan kebenarannya."

        advice = CATEGORY_ADVICE.get(category, CATEGORY_ADVICE["GENERAL_NEWS"])
        return f"> {line}\n> {advice} 🙏"
