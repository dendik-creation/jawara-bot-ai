"""The deterministic composer, checked against the five documented few-shot cases.

`01_LLM_System_Prompt.md` ships five real-world examples. The acceptance
criterion is consistency in *tone and structure* with those examples — the exact
wording of a generated reply is the model's business, the shape is not.
"""

import pytest

from app.llm.prompt import GenerationRequest
from app.llm.template_provider import TemplateProvider
from app.llm.validator import STATUS_HIGH, STATUS_SAFE, validate_response

composer = TemplateProvider()

KITOLOD = {
    "title": "Klaim Daun Kitolod Menyembuhkan Katarak",
    "claim_text": "Air rebusan daun kitolod dapat menyembuhkan katarak tanpa operasi.",
    "fact_explanation": (
        "Kemenkes RI dan PERDAMI menegaskan penggunaan air ramuan daun liar pada mata "
        "berisiko infeksi hingga kebutaan permanen. Katarak hanya dapat ditangani lewat operasi."
    ),
    "verdict": "HOAX",
    "source_name": "Kemenkes RI & TurnBackHoax",
    "source_url": "https://turnbackhoax.id/2026/01/10/hoax-kitolod-katarak/",
    "score": 0.91,
}

VAKSINASI = {
    "title": "Vaksinasi Influenza Gratis di Puskesmas",
    "claim_text": "Puskesmas membuka vaksinasi flu gratis minggu depan.",
    "fact_explanation": "Kemenkes menyelenggarakan vaksinasi influenza gratis bagi lansia di Puskesmas.",
    "verdict": "FACT",
    "source_name": "Kemenkes RI",
    "source_url": "https://kemkes.go.id/",
    "score": 0.88,
}

# The five documented cases, in vault order.
FEW_SHOT: list[tuple[str, GenerationRequest]] = [
    (
        "health hoax",
        GenerationRequest(
            user_text="Tolong cek berita ini: Air rebusan daun kitolod bisa sembuhkan katarak.",
            category="HEALTH_HOAX",
            risk_level="HIGH",
            context=[KITOLOD],
        ),
    ),
    (
        "apk malware",
        GenerationRequest(
            user_text="Ada file dikirim di grup judulnya Undangan_Pernikahan.apk. Ini aman gak ya?",
            category="FILE_APK",
            risk_level="HIGH",
        ),
    ),
    (
        "financial fraud",
        GenerationRequest(
            user_text="Saya dapat SMS menang hadiah 50 juta, disuruh transfer biaya admin.",
            category="FINANCIAL_FRAUD",
            risk_level="HIGH",
        ),
    ),
    (
        "phishing link",
        GenerationRequest(
            user_text="Benar gak link ini http://bansos-pemerintah-2026.com buat klaim bantuan?",
            category="PHISHING_LINK",
            risk_level="HIGH",
            url_verdicts=[
                {"url": "http://bansos-pemerintah-2026.com", "risk": "HIGH", "reason": "flagged_by=safe_browsing"}
            ],
        ),
    ),
    (
        "official news",
        GenerationRequest(
            user_text="Apakah benar Puskesmas membuka vaksinasi flu gratis minggu depan?",
            category="GENERAL_NEWS",
            risk_level="LOW",
            context=[VAKSINASI],
        ),
    ),
]


@pytest.mark.parametrize("label,request_", FEW_SHOT, ids=[label for label, _ in FEW_SHOT])
def test_every_documented_case_produces_a_contract_compliant_reply(label, request_):
    result = validate_response(composer.compose(request_))
    assert result.is_valid, f"{label}: {result.violations}"


@pytest.mark.parametrize("label,request_", FEW_SHOT, ids=[label for label, _ in FEW_SHOT])
def test_forwardable_block_is_fully_quoted(label, request_):
    result = validate_response(composer.compose(request_))
    assert all(line.startswith(">") for line in result.forward.splitlines())


@pytest.mark.parametrize("label,request_", FEW_SHOT, ids=[label for label, _ in FEW_SHOT])
def test_replies_address_the_reader_politely(label, request_):
    # Persona rule: "Bapak/Ibu", never shaming the reader.
    assert "Bapak/Ibu" in composer.compose(request_)


def test_high_risk_uses_the_red_status_and_low_risk_the_green_one():
    assert composer.compose(FEW_SHOT[0][1]).startswith(STATUS_HIGH)
    assert composer.compose(FEW_SHOT[4][1]).startswith(STATUS_SAFE)


def test_composition_is_deterministic():
    first = composer.compose(FEW_SHOT[0][1])
    assert first == composer.compose(FEW_SHOT[0][1])


def test_knowledge_match_source_is_preferred_over_the_category_default():
    assert KITOLOD["source_url"] in composer.compose(FEW_SHOT[0][1])


def test_category_default_reference_is_used_without_a_match():
    assert "patrolisiber.id" in composer.compose(FEW_SHOT[1][1])


def test_unverified_claim_says_so_instead_of_inventing_a_verdict():
    reply = composer.compose(
        GenerationRequest(user_text="katanya besok ada bansos baru", category="GENERAL_NEWS", risk_level="MEDIUM")
    )
    assert "belum" in reply.lower()
    assert validate_response(reply).is_valid


async def test_generate_delegates_to_compose():
    request_ = FEW_SHOT[0][1]
    assert await composer.generate(request_) == composer.compose(request_)
