"""Corpus-driven tests for the text normalizer.

The corpus is representative WhatsApp Indonesian: forwarded hoaxes, slang,
shouting, emoji, invisible characters, and links. Ten samples is the acceptance
floor from [[Implement Text Normalizer]], not the target.
"""

import pytest

from app.pipeline.normalizer import MAX_LENGTH, normalize_text

# (raw message, expected normalised text)
CORPUS: list[tuple[str, str]] = [
    (
        "Tolong cek berita ini: Air rebusan daun kitolod bisa sembuhkan katarak!!!",
        "tolong cek berita ini: air rebusan daun kitolod bisa sembuhkan katarak!",
    ),
    (
        "BAPAK/IBU HARAP HATI2 YAAA",
        "bapak/ibu harap hati2 ya",
    ),
    (
        "gak usah kuatir bu, sy udh cek kok",
        "tidak usah kuatir bu, saya sudah cek kok",
    ),
    (
        "Bnr gak sih klo minum air rebusan bs nyembuhin diabetes?",
        "benar tidak sih kalau minum air rebusan bisa nyembuhin diabetes?",
    ),
    (
        "Selamat!!! Anda menang hadiah 50jt 🎉🎉🎉 transfer biaya admin dulu ya",
        "selamat! anda menang hadiah 50jt transfer biaya admin dulu ya",
    ),
    (
        "*PENTING* _mohon disebarkan_ ~grup keluarga~",
        "penting mohon disebarkan grup keluarga",
    ),
    (
        "cek link ini https://Bansos-Pemerintah.com/Klaim?id=99 ya pak",
        "cek link ini https://Bansos-Pemerintah.com/Klaim?id=99 ya pak",
    ),
    (
        "info dr grup sebelah, katanya bantuan 2jt cair minggu depan",
        "informasi dr grup sebelah, katanya bantuan 2jt cair minggu depan",
    ),
    (
        "Bagusss sekaliii infonyaaa",
        "bagus sekali infonya",
    ),
    (
        "aq mau tanya dgn bpk, ini hoax bkn?",
        "saya mau tanya dengan bapak, ini hoax bukan?",
    ),
    (
        "   Mohon    dibaca\n\n\n  ya bu   ",
        "mohon dibaca ya bu",
    ),
    (
        "b​ansos cair, klik sekarang",
        "bansos cair, klik sekarang",
    ),
]


@pytest.mark.parametrize("raw,expected", CORPUS)
def test_corpus_normalises_as_documented(raw: str, expected: str):
    assert normalize_text(raw).text == expected


@pytest.mark.parametrize("raw,_expected", CORPUS)
def test_normalisation_is_deterministic(raw: str, _expected: str):
    # Same input, same output — the embedding and the intent score both depend
    # on this, and a nondeterministic normaliser makes both irreproducible.
    assert normalize_text(raw).text == normalize_text(raw).text


def test_urls_survive_case_and_punctuation_squashing():
    result = normalize_text("Klik https://Contoh.COM/Path/Aa?x=YY sekarang!!!")
    assert "https://Contoh.COM/Path/Aa?x=YY" in result.text
    assert result.urls_masked == 1


def test_emoji_are_stripped_but_counted():
    result = normalize_text("hati hati ya 🙏🙏 semoga sehat 💚")
    assert "🙏" not in result.text
    assert result.emoji_count == 3


def test_empty_and_none_input_are_handled():
    assert normalize_text(None).text == ""
    assert normalize_text("").is_empty
    assert normalize_text("   ").is_empty


def test_slang_expansions_are_reported():
    result = normalize_text("sy udh cek yg tadi")
    assert set(result.slang_replaced) == {"sy", "udh", "yg"}


def test_long_message_is_truncated_not_dropped():
    result = normalize_text("a" * (MAX_LENGTH + 500))
    assert result.was_truncated
    assert len(result.text) <= MAX_LENGTH


def test_ambiguous_abbreviations_are_not_expanded():
    # "dr" is both "dari" and "dokter"; guessing wrong rewrites the claim the
    # classifier is about to read.
    from app.pipeline.normalizer import AMBIGUOUS_ABBREVIATIONS, SLANG

    assert not AMBIGUOUS_ABBREVIATIONS & set(SLANG)
    assert normalize_text("kata dr budi").text == "kata dr budi"


def test_doubled_letters_are_left_alone():
    # "maaf" and "massa" are ordinary Indonesian; only runs of 3+ collapse.
    assert normalize_text("maaf massa saat").text == "maaf massa saat"
