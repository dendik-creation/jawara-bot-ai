"""Four-section output contract enforcement."""

import pytest

from app.llm.validator import (
    STATUS_HIGH,
    STATUS_MEDIUM,
    STATUS_SAFE,
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
