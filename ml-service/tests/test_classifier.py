"""`app.models.classifier`: train/save/load roundtrip and artifact integrity."""

import pytest

from app.models import classifier as classifier_module

SAMPLES = [
    ("Air rebusan daun kitolod sembuhkan katarak tanpa operasi", "HEALTH_HOAX"),
    ("Obat herbal ampuh sembuhkan kanker tanpa efek samping", "HEALTH_HOAX"),
    ("Selamat anda menang hadiah 100 juta transfer biaya admin", "FINANCIAL_FRAUD"),
    ("Rekening anda diblokir kirim kode OTP sekarang", "FINANCIAL_FRAUD"),
    ("Oke nanti malam jadi ketemuan jam 7 ya", "NOT_A_THREAT"),
    ("Makasih infonya, aku otw ke kantor", "NOT_A_THREAT"),
]


def test_train_rejects_an_empty_sample_list():
    with pytest.raises(ValueError):
        classifier_module.train([])


def test_predict_returns_a_label_and_a_full_probability_distribution():
    model = classifier_module.train(SAMPLES)

    label, probabilities = model.predict("Klik link ini transfer dulu biar hadiah cair")

    assert label in probabilities
    assert set(probabilities) == {"HEALTH_HOAX", "FINANCIAL_FRAUD", "NOT_A_THREAT"}
    assert abs(sum(probabilities.values()) - 1.0) < 1e-6
    assert max(probabilities, key=probabilities.get) == label


def test_evaluate_reports_accuracy_and_per_class_metrics():
    model = classifier_module.train(SAMPLES)

    metrics = model.evaluate(SAMPLES)

    assert 0.0 <= metrics["accuracy"] <= 1.0
    assert metrics["sample_count"] == len(SAMPLES)
    assert set(metrics["per_class"]) == {"HEALTH_HOAX", "FINANCIAL_FRAUD", "NOT_A_THREAT"}


def test_save_then_load_with_the_right_checksum_roundtrips(tmp_path):
    model = classifier_module.train(SAMPLES)
    path = tmp_path / "clf-test.joblib"

    sha256 = classifier_module.save(model, path)
    loaded = classifier_module.load(path, sha256)

    assert loaded.predict("Rekening anda diblokir")[0] == model.predict("Rekening anda diblokir")[0]


def test_load_rejects_a_mismatched_checksum(tmp_path):
    model = classifier_module.train(SAMPLES)
    path = tmp_path / "clf-test.joblib"
    classifier_module.save(model, path)

    with pytest.raises(classifier_module.ArtifactIntegrityError):
        classifier_module.load(path, "0" * 64)


def test_load_rejects_a_missing_artifact(tmp_path):
    with pytest.raises(FileNotFoundError):
        classifier_module.load(tmp_path / "does-not-exist.joblib", "0" * 64)


def test_a_tampered_artifact_is_rejected_even_with_the_originally_correct_checksum(tmp_path):
    """The whole point of the checksum: bytes on disk changed after `save()`
    recorded its hash must never be trusted just because a caller still
    quotes the old (now-wrong) value.
    """
    model = classifier_module.train(SAMPLES)
    path = tmp_path / "clf-test.joblib"
    original_sha256 = classifier_module.save(model, path)

    path.write_bytes(path.read_bytes() + b"tampered")

    with pytest.raises(classifier_module.ArtifactIntegrityError):
        classifier_module.load(path, original_sha256)
