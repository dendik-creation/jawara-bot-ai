"""Hoax corpus import: keyword heuristic + CSV collection, no DB."""

import csv

import pytest

from app.scripts import import_hoax_corpus as script


# --------------------------------------------------------------------------
# classify_hoax_text — pure function
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Silakan instal aplikasi undangan.apk berikut untuk melihat isinya", "FILE_APK"),
        ("Buka link https://contoh-phising.test/verifikasi untuk klaim hadiah", "PHISHING_LINK"),
        ("Segera transfer biaya admin ke rekening bank agar hadiah cair", "FINANCIAL_FRAUD"),
        ("Rebusan daun kelor terbukti bisa menyembuhkan kanker stadium akhir", "HEALTH_HOAX"),
        ("Pemadaman listrik terjadwal di beberapa wilayah akhir pekan ini", "GENERAL_NEWS"),
    ],
)
def test_classify_hoax_text_matches_expected_bucket(text, expected):
    assert script.classify_hoax_text(text) == expected


def test_classify_hoax_text_prioritizes_apk_over_financial_keywords():
    text = "Instal aplikasi bukti transfer bank berikut, file .apk terlampir"
    assert script.classify_hoax_text(text) == "FILE_APK"


def test_classify_hoax_text_is_case_insensitive():
    assert script.classify_hoax_text("SEGERA KLIK LINK INI SEKARANG") == "PHISHING_LINK"


# --------------------------------------------------------------------------
# collect_samples — CSV reading + dedup
# --------------------------------------------------------------------------


def _write_csv(path, rows, fieldnames):
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


@pytest.fixture
def corpus_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(script, "_CORPUS_DIR", tmp_path)

    fieldnames = ["url", "judul", "narasi", "label", "clean_text"]
    _write_csv(
        tmp_path / "antaranews_cleaned_v3.csv",
        [
            {"url": "u1", "judul": "j1", "narasi": "Berita resmi pemerintah soal vaksinasi", "label": "0", "clean_text": "x"},
            {"url": "u2", "judul": "j2", "narasi": "Berita resmi pemerintah soal vaksinasi", "label": "0", "clean_text": "x"},
        ],
        fieldnames,
    )
    _write_csv(tmp_path / "detik_cleaned_v3.csv", [], fieldnames)
    _write_csv(
        tmp_path / "kompas_cleaned_v3.csv",
        [{"url": "u3", "judul": "j3", "narasi": "Prakiraan cuaca ekstrem pekan ini", "label": "0", "clean_text": "x"}],
        fieldnames,
    )
    _write_csv(
        tmp_path / "tbh_cleaned_v3.csv",
        [
            {"url": "u4", "judul": "j4", "narasi": "Segera transfer biaya admin ke rekening bank", "hoax": "1", "clean_text": "x"},
            {"url": "u5", "judul": "j5", "narasi": "", "hoax": "1", "clean_text": "x"},
            {"url": "u6", "judul": "j6", "narasi": "Prakiraan cuaca ekstrem pekan ini", "hoax": "1", "clean_text": "x"},
        ],
        ["url", "judul", "narasi", "hoax", "clean_text"],
    )
    return tmp_path


def test_collect_samples_dedupes_across_files_and_rows(corpus_dir):
    samples = script.collect_samples()
    texts = [text for text, _ in samples]

    assert texts.count("Berita resmi pemerintah soal vaksinasi") == 1
    assert texts.count("Prakiraan cuaca ekstrem pekan ini") == 1


def test_collect_samples_labels_legit_outlets_not_a_threat(corpus_dir):
    samples = dict(script.collect_samples())
    assert samples["Berita resmi pemerintah soal vaksinasi"] == "NOT_A_THREAT"


def test_collect_samples_skips_blank_narasi(corpus_dir):
    samples = script.collect_samples()
    assert all(text for text, _ in samples)
    assert len(samples) == 3


def test_collect_samples_first_seen_wins_on_cross_file_duplicate(corpus_dir):
    """The legit files are read before the hoax file, so a duplicate
    narasi already seen as NOT_A_THREAT keeps that label rather than being
    overwritten by the hoax file's heuristic classification.
    """
    samples = dict(script.collect_samples())
    assert samples["Prakiraan cuaca ekstrem pekan ini"] == "NOT_A_THREAT"
