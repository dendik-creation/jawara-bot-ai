"""Four-section output contract enforcement."""

import pytest

from app.llm.validator import (
    STATUS_HIGH,
    STATUS_MEDIUM,
    STATUS_SAFE,
    URL_STATUS_HIGH,
    URL_STATUS_LOW,
    URL_STATUS_MEDIUM,
    URL_STATUS_UNKNOWN,
    status_for_risk,
    validate_response,
)

VALID = """🔴 *HOAKS / BAHAYA TINGGI*

Bapak/Ibu, informasi ini tidak benar. Kemenkes menegaskan hal tersebut berbahaya.

Sumber Resmi:
https://turnbackhoax.id/

> *Pesan Penting untuk Keluarga:*
> Mohon berhati-hati dengan kabar ini ya. 🙏"""


def test_valid_response_parses_into_four_sections():
    result = validate_response(VALID)

    assert result.is_valid
    assert result.status == STATUS_HIGH
    assert result.explanation.startswith("Bapak/Ibu")
    assert "turnbackhoax.id" in result.reference
    assert result.forward.splitlines()[0].startswith(">")


def test_missing_status_indicator_is_a_violation():
    result = validate_response(VALID.replace(STATUS_HIGH, "Perhatian!"))
    assert "missing_status_indicator" in result.violations


def test_missing_forwardable_block_is_a_violation():
    text = VALID.split("> *Pesan")[0].strip()
    result = validate_response(text)
    assert "missing_forwardable_message" in result.violations


def test_unquoted_forwardable_line_is_a_violation():
    # Every line must start with `>` — a single unquoted line breaks copy-forward.
    text = VALID.replace("> Mohon berhati-hati", "Mohon berhati-hati")
    result = validate_response(text)
    assert "forwardable_message_not_quoted" in result.violations


def test_missing_reference_link_is_a_violation():
    text = VALID.replace("https://turnbackhoax.id/", "(tidak ada)")
    result = validate_response(text)
    assert "missing_reference_link" in result.violations


def test_more_than_one_reference_link_is_a_violation():
    text = VALID.replace("Sumber Resmi:", "Lihat juga https://contoh.id/ dan\nSumber Resmi:")
    result = validate_response(text)
    assert "multiple_reference_links" in result.violations


def test_missing_explanation_is_a_violation():
    text = VALID.replace(
        "Bapak/Ibu, informasi ini tidak benar. Kemenkes menegaskan hal tersebut berbahaya.\n", ""
    )
    result = validate_response(text)
    assert "missing_explanation" in result.violations


def test_empty_response_is_a_violation():
    assert "empty_response" in validate_response("").violations


def test_long_explanation_warns_but_still_passes():
    long_text = VALID.replace(
        "Bapak/Ibu, informasi ini tidak benar. Kemenkes menegaskan hal tersebut berbahaya.",
        " ".join(f"Kalimat nomor {index}." for index in range(6)),
    )
    result = validate_response(long_text)

    assert result.is_valid  # style, not contract
    assert "explanation_over_four_sentences" in result.warnings


@pytest.mark.parametrize(
    "risk,expected",
    [
        ("HIGH", STATUS_HIGH),
        ("MEDIUM", STATUS_MEDIUM),
        ("LOW", STATUS_SAFE),
        ("UNKNOWN", STATUS_MEDIUM),
        ("", STATUS_MEDIUM),
    ],
)
def test_risk_maps_to_the_documented_status_indicator(risk, expected):
    # UNKNOWN must never render as green: "we could not verify" is not "safe".
    assert status_for_risk(risk) == expected


# --------------------------------------------------------------------------
# URL-safety vocabulary (`!link` false-positive fix, Part 2) — a separate
# semantic space from the fact/hoax markers above. `category=None` (or any
# non-PHISHING_LINK category) must keep the exact pre-existing behaviour
# tested above; only PHISHING_LINK switches vocabulary.
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "risk,expected",
    [
        ("HIGH", URL_STATUS_HIGH),
        ("MEDIUM", URL_STATUS_MEDIUM),
        ("LOW", URL_STATUS_LOW),
        ("UNKNOWN", URL_STATUS_UNKNOWN),
        ("", URL_STATUS_UNKNOWN),
    ],
)
def test_phishing_link_risk_maps_to_the_url_safety_indicator(risk, expected):
    assert status_for_risk(risk, category="PHISHING_LINK") == expected


def test_url_unknown_is_its_own_marker_not_hoax_and_not_safe():
    marker = status_for_risk("UNKNOWN", category="PHISHING_LINK")
    assert marker == URL_STATUS_UNKNOWN
    assert marker not in (STATUS_HIGH, STATUS_MEDIUM, STATUS_SAFE)
    assert "HOAKS" not in marker
    assert "AMAN" not in marker  # distinct from URL_STATUS_LOW's "🟢 *AMAN*"


def test_non_phishing_categories_keep_the_fact_hoax_vocabulary():
    for category in ("HEALTH_HOAX", "FINANCIAL_FRAUD", "GENERAL_NEWS", "FILE_APK", None):
        assert status_for_risk("HIGH", category=category) == STATUS_HIGH
        assert status_for_risk("LOW", category=category) == STATUS_SAFE


# --------------------------------------------------------------------------
# Deterministic status enforcement — `expected_status` makes a structurally
# valid but wrong status line a rejected (not merely warned-about) violation.
# --------------------------------------------------------------------------


def test_status_matching_the_expected_risk_is_not_a_violation():
    result = validate_response(VALID, expected_status=STATUS_HIGH)
    assert "status_mismatch" not in result.violations
    assert result.is_valid


def test_status_disagreeing_with_the_expected_risk_is_rejected():
    # Structurally perfect four-section reply — the only problem is that the
    # LLM's status line does not match the deterministic risk it was given.
    result = validate_response(VALID, expected_status=STATUS_SAFE)
    assert "status_mismatch" in result.violations
    assert not result.is_valid


def test_url_status_can_mismatch_against_a_url_expected_status():
    reply = VALID.replace(STATUS_HIGH, URL_STATUS_HIGH)
    result = validate_response(reply, expected_status=URL_STATUS_UNKNOWN)
    assert "status_mismatch" in result.violations


def test_no_expected_status_means_no_mismatch_check():
    # Existing callers that don't pass `expected_status` keep working exactly
    # as before — purely structural validation.
    result = validate_response(VALID)
    assert "status_mismatch" not in result.violations
