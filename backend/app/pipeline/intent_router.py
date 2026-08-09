"""Intent classification and verification-engine dispatch ([[Build Intent Router]]).

This is the deterministic half of detection — Detection Rules, in the vocabulary
of 02_Architecture/01_System_Architecture.md §5. It is keyword/indicator scoring,
not a model: it is explainable, editable without retraining, and cheap enough to
run on every message. The probabilistic half (ML classification with confidence
and `model_version`) lives in `ml-service` behind `POST /v1/classify`; when that
call is unavailable the pipeline degrades to this path alone and the result is
marked `ml_unavailable`.

Sprint 1 routes `HEALTH_HOAX`, `GENERAL_NEWS`, `PHISHING_LINK` and — per the
scope update in the task note — `FILE_APK` (detect the attachment and warn; no
static analysis). `FINANCIAL_FRAUD` is a known category with no engine yet: it
classifies, then routes to `unsupported` rather than silently pretending to be
one of the others. Adding an engine later is a line in `ROUTES`.
"""

import re
from dataclasses import dataclass, field
from typing import Sequence

from app.pipeline.categories import Category
from app.pipeline.url_extractor import ExtractedURL

# Verification engines the router can dispatch to. String constants rather than
# imports: the router must not depend on the engines, or every engine would drag
# its client library into the classification path.
ENGINE_TEXT_VERIFICATION = "text_verification"
ENGINE_URL_SAFETY = "url_safety"
ENGINE_APK_WARNING = "apk_warning"
ENGINE_UNSUPPORTED = "unsupported"
ENGINE_NONE = "none"

ROUTES: dict[Category, str] = {
    Category.HEALTH_HOAX: ENGINE_TEXT_VERIFICATION,
    Category.GENERAL_NEWS: ENGINE_TEXT_VERIFICATION,
    Category.PHISHING_LINK: ENGINE_URL_SAFETY,
    Category.FILE_APK: ENGINE_APK_WARNING,
    # Post-MVP: needs CekRekening.id / fraud_blacklists, neither of which exists.
    Category.FINANCIAL_FRAUD: ENGINE_UNSUPPORTED,
}

# Keyword weights. Multi-word phrases score higher than single words because a
# lone word like "gratis" appears in perfectly ordinary messages.
_LEXICON: dict[Category, dict[str, float]] = {
    Category.HEALTH_HOAX: {
        "sembuh": 1.4,
        "menyembuhkan": 1.8,
        "obat": 1.2,
        "khasiat": 1.5,
        "ramuan": 1.6,
        "herbal": 1.3,
        "vaksin": 1.3,
        "kanker": 1.4,
        "katarak": 1.6,
        "diabetes": 1.4,
        "stroke": 1.3,
        "kolesterol": 1.3,
        "darah tinggi": 1.5,
        "tanpa operasi": 2.0,
        "dokter": 0.8,
        "kemenkes": 1.2,
        "rumah sakit": 1.0,
        "penyakit": 1.2,
        "tetes mata": 1.6,
        "rebusan daun": 2.0,
        "covid": 1.2,
        "imunisasi": 1.2,
        "terapi": 1.1,
    },
    Category.FINANCIAL_FRAUD: {
        "rekening": 1.8,
        "transfer": 1.6,
        "saldo": 1.5,
        "biaya administrasi": 2.0,
        "menang hadiah": 2.2,
        "undian": 1.8,
        "hadiah": 1.2,
        "pinjaman online": 1.8,
        "investasi": 1.4,
        "keuntungan": 1.1,
        "dana": 0.8,
        "ovo": 1.2,
        "gopay": 1.2,
        "atm": 1.2,
        "pin": 1.0,
        "otp": 1.8,
        "kode verifikasi": 2.0,
    },
    Category.PHISHING_LINK: {
        "klik link": 2.0,
        "klik tautan": 2.0,
        "daftar sekarang": 1.4,
        "klaim": 1.4,
        "bansos": 1.8,
        "bantuan sosial": 1.8,
        "subsidi": 1.4,
        "login": 1.4,
        "verifikasi akun": 2.0,
        "akun anda": 1.4,
        "diblokir": 1.4,
        "promo": 1.0,
        "gratis": 0.9,
        "hadiah": 0.8,
        "resi": 1.2,
        "paket": 0.8,
    },
    Category.GENERAL_NEWS: {
        "berita": 1.6,
        "informasi": 1.0,
        "kabar": 1.4,
        "beredar": 1.5,
        "viral": 1.4,
        "pengumuman": 1.4,
        "pemerintah": 1.0,
        "resmi": 1.0,
        "benarkah": 1.8,
        "apakah benar": 2.0,
        "hoaks": 1.6,
        "hoax": 1.6,
        "cek fakta": 2.0,
        "sumber": 0.8,
    },
    Category.FILE_APK: {
        "apk": 2.0,
        "aplikasi": 0.8,
        "install": 1.2,
        "instal": 1.2,
        "unduh": 1.0,
        "undangan": 1.0,
        "surat tilang": 1.6,
    },
}

# Indicator weights added on top of the lexicon. These come from message
# structure, not vocabulary, and are what let a bare forwarded link classify at
# all — such a message often has no keywords whatsoever.
WEIGHT_URL_PRESENT = 2.2
WEIGHT_SHORTLINK = 1.8
WEIGHT_IP_HOST = 1.6
WEIGHT_DEFANGED = 1.0
WEIGHT_APK_ATTACHMENT = 4.0
WEIGHT_APK_MENTION = 1.5
WEIGHT_QUESTION = 0.6

_APK_FILENAME = re.compile(r"[\w\-. ]+\.apk\b", re.IGNORECASE)
_QUESTION = re.compile(r"\?|\bbenarkah\b|\bapakah\b|\bbetulkah\b")


@dataclass(frozen=True)
class IntentResult:
    """Classification outcome plus the engine it should be dispatched to."""

    category: Category | None
    confidence: float
    engine: str
    scores: dict[str, float] = field(default_factory=dict)
    signals: tuple[str, ...] = ()
    threshold: float = 0.0

    @property
    def is_confident(self) -> bool:
        return self.category is not None

    def as_log_fields(self) -> dict[str, object]:
        return {
            "intent": self.category.value if self.category else "UNKNOWN",
            "intent_confidence": round(self.confidence, 3),
            "intent_engine": self.engine,
            "intent_signals": list(self.signals),
        }


def _lexicon_scores(text: str) -> tuple[dict[Category, float], list[str]]:
    scores: dict[Category, float] = {category: 0.0 for category in Category}
    signals: list[str] = []
    for category, lexicon in _LEXICON.items():
        for phrase, weight in lexicon.items():
            if phrase in text:
                scores[category] += weight
                signals.append(f"kw:{category.value}:{phrase}")
    return scores, signals


def classify(
    text: str,
    urls: Sequence[ExtractedURL] = (),
    attachment_names: Sequence[str] = (),
    confidence_threshold: float | None = None,
    min_score: float | None = None,
) -> IntentResult:
    """Classify normalised `text` plus its extracted indicators.

    `confidence_threshold` and `min_score` default to configuration, never to
    literals baked in at the call site — the acceptance criterion is an operator
    being able to retune sensitivity without a code change.

    Confidence is the winning category's *share* of total score, so a message
    that scores highly for two categories at once is reported as ambiguous
    rather than as a confident win for whichever edged ahead.
    """
    from app.core.config import get_settings

    settings = get_settings()
    threshold = settings.intent_confidence_threshold if confidence_threshold is None else confidence_threshold
    floor = settings.intent_min_score if min_score is None else min_score

    scores, signals = _lexicon_scores(text or "")

    if urls:
        scores[Category.PHISHING_LINK] += WEIGHT_URL_PRESENT
        signals.append("url:present")
        if any(url.is_shortlink for url in urls):
            scores[Category.PHISHING_LINK] += WEIGHT_SHORTLINK
            signals.append("url:shortlink")
        if any(url.is_ip_host for url in urls):
            scores[Category.PHISHING_LINK] += WEIGHT_IP_HOST
            signals.append("url:ip_host")
        if any(url.was_defanged for url in urls):
            scores[Category.PHISHING_LINK] += WEIGHT_DEFANGED
            signals.append("url:defanged")

    if any(name.lower().endswith(".apk") for name in attachment_names):
        scores[Category.FILE_APK] += WEIGHT_APK_ATTACHMENT
        signals.append("file:apk_attachment")
    elif _APK_FILENAME.search(text or ""):
        scores[Category.FILE_APK] += WEIGHT_APK_MENTION
        signals.append("file:apk_mention")

    if _QUESTION.search(text or ""):
        scores[Category.GENERAL_NEWS] += WEIGHT_QUESTION
        signals.append("form:question")

    total = sum(scores.values())
    readable = {category.value: round(score, 3) for category, score in scores.items() if score > 0}

    if total <= 0:
        return IntentResult(
            category=None,
            confidence=0.0,
            engine=ENGINE_NONE,
            scores=readable,
            signals=tuple(signals),
            threshold=threshold,
        )

    winner = max(scores, key=lambda category: (scores[category], category.value))
    top = scores[winner]
    confidence = top / total

    if top < floor or confidence < threshold:
        return IntentResult(
            category=None,
            # Too little evidence and too much ambiguity are different failures.
            # A dominant-but-tiny score is not 100% confident about anything, so
            # it reports 0.0; a genuinely contested message reports its share.
            confidence=0.0 if top < floor else confidence,
            engine=ENGINE_NONE,
            scores=readable,
            signals=tuple(signals),
            threshold=threshold,
        )

    return IntentResult(
        category=winner,
        confidence=confidence,
        engine=ROUTES[winner],
        scores=readable,
        signals=tuple(signals),
        threshold=threshold,
    )


def route_for(category: Category | None) -> str:
    """Engine responsible for `category`; `none` for an unclassified message."""
    if category is None:
        return ENGINE_NONE
    return ROUTES.get(category, ENGINE_UNSUPPORTED)
