import re
from pathlib import Path

import pytest

from app.pipeline import intent_router
from app.pipeline.categories import Category, RiskLevel, worst_risk
from app.pipeline.normalizer import normalize_text
from app.pipeline.url_extractor import extract_urls

MIGRATION = Path(__file__).resolve().parents[1] / "app" / "db" / "migrations" / "001_init_schema.sql"


def _classify(message: str, attachments: tuple[str, ...] = ()):
    normalized = normalize_text(message)
    return intent_router.classify(
        normalized.text,
        urls=extract_urls(message),
        attachment_names=attachments,
    )


def _enum_members(name: str) -> set[str]:
    sql = MIGRATION.read_text(encoding="utf-8")
    block = re.search(rf"CREATE TYPE {name} AS ENUM \((.*?)\);", sql, re.DOTALL)
    assert block, f"{name} not found in migration 001"
    return set(re.findall(r"'([A-Z_]+)'", block.group(1)))


def test_category_enum_matches_the_migration_exactly():
    # Acceptance criterion: no drift between code and schema. If someone adds a
    # category to the SQL and forgets the enum here (or the reverse), this fails
    # before the mismatch reaches a `detected_intent` insert.
    assert {category.value for category in Category} == _enum_members("category_enum")


def test_risk_level_enum_matches_the_migration_exactly():
    assert {level.value for level in RiskLevel} == _enum_members("risk_level_enum")


def test_every_category_has_a_route():
    # A new category without a route would fall through to whatever the router
    # happened to return last.
    assert set(intent_router.ROUTES) == set(Category)


@pytest.mark.parametrize(
    "message,expected",
    [
        (
            "Tolong cek berita ini: Air rebusan daun kitolod bisa sembuhkan katarak tanpa perlu operasi dokter.",
            Category.HEALTH_HOAX,
        ),
        (
            "Benar gak link ini http://bansos-pemerintah-2026.com buat klaim bantuan 2 juta rupiah?",
            Category.PHISHING_LINK,
        ),
        (
            "Apakah benar Puskesmas membuka vaksinasi flu gratis minggu depan?",
            Category.GENERAL_NEWS,
        ),
    ],
)
def test_detects_the_three_sprint_one_categories(message: str, expected: Category):
    assert _classify(message).category is expected


def test_routes_each_category_to_its_verification_engine():
    assert _classify("air rebusan daun kitolod menyembuhkan katarak").engine == (
        intent_router.ENGINE_TEXT_VERIFICATION
    )
    assert _classify("klik link ini bit.ly/bansos untuk klaim bantuan").engine == (
        intent_router.ENGINE_URL_SAFETY
    )
    assert _classify("ada file Undangan.apk", ("Undangan.apk",)).engine == (
        intent_router.ENGINE_APK_WARNING
    )


def test_apk_attachment_is_classified_and_warned_not_analysed():
    result = _classify("Ini aman gak ya?", ("Undangan_Pernikahan.apk",))
    assert result.category is Category.FILE_APK
    assert result.engine == intent_router.ENGINE_APK_WARNING
    assert "file:apk_attachment" in result.signals


def test_financial_fraud_classifies_but_routes_to_unsupported():
    # Post-MVP: the category exists, the engine does not. It must say so rather
    # than silently borrowing another engine.
    result = _classify(
        "Saya menang hadiah undian, disuruh transfer biaya administrasi ke rekening pribadi"
    )
    assert result.category is Category.FINANCIAL_FRAUD
    assert result.engine == intent_router.ENGINE_UNSUPPORTED


def test_unknown_input_is_handled_explicitly_and_does_not_crash():
    result = _classify("halo pak apa kabar")
    assert result.category is None
    assert result.engine == intent_router.ENGINE_NONE
    assert result.is_confident is False


def test_empty_input_is_handled():
    result = intent_router.classify("")
    assert result.category is None
    assert result.engine == intent_router.ENGINE_NONE


def test_ambiguous_input_below_threshold_is_reported_as_unknown():
    # Score split across two categories: confidence is the winner's share, so a
    # contested message never presents as a confident classification.
    result = intent_router.classify(
        "rekening obat herbal transfer khasiat saldo kanker",
        confidence_threshold=0.9,
    )
    assert result.category is None
    assert 0.0 < result.confidence < 0.9


def test_confidence_threshold_is_configurable_not_hardcoded():
    text = normalize_text("apakah benar ada berita vaksinasi gratis").text
    permissive = intent_router.classify(text, confidence_threshold=0.1)
    strict = intent_router.classify(text, confidence_threshold=0.99)
    assert permissive.category is Category.GENERAL_NEWS
    assert strict.category is None


def test_route_for_maps_unknown_category_to_no_engine():
    assert intent_router.route_for(None) == intent_router.ENGINE_NONE
    assert intent_router.route_for(Category.PHISHING_LINK) == intent_router.ENGINE_URL_SAFETY


def test_unknown_risk_never_outranks_a_clean_result_but_never_reads_as_clean():
    assert worst_risk(RiskLevel.LOW, RiskLevel.UNKNOWN) is RiskLevel.UNKNOWN
    assert worst_risk(RiskLevel.HIGH, RiskLevel.UNKNOWN) is RiskLevel.HIGH
    assert worst_risk() is RiskLevel.UNKNOWN
