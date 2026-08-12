"""Threat-category classifier — TF-IDF (word + char n-gram) + LogisticRegression.

CPU-only, no external API, no GPU: the same no-heavy-deps posture as the hash
embedder (`app/embeddings/hashing.py`). This is a from-scratch fit per training
job, not a pretrained/fine-tuned model — "the first classifier"
(05_Training_Jobs.md) starts as a strong, fast baseline, not a transformer.

Artifact trust: ml-service has no database of its own, so it cannot know which
`model_version` is "production" — the gateway (which owns the model registry in
Postgres) tells it, on every call, which version to use and what sha256 to
trust. `load()` recomputes the checksum and refuses to return an artifact that
doesn't match — the "artifact unknown to the registry must not be loaded" rule
(07_Model_Registry_and_Deployment.md §7), enforced without ml-service needing
its own copy of the registry.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import joblib
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import classification_report
from sklearn.pipeline import FeatureUnion, Pipeline


class ArtifactIntegrityError(Exception):
    """A loaded artifact's checksum didn't match what the caller expected."""


def _build_pipeline() -> Pipeline:
    features = FeatureUnion(
        [
            # Word-level: catches topical vocabulary ("transfer", "admin", "menang").
            ("word", TfidfVectorizer(analyzer="word", ngram_range=(1, 2), min_df=1)),
            # Char-level: robust to the typos/slang/spacing variation Indonesian
            # WhatsApp text is full of, and to unseen word forms at inference time.
            ("char", TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), min_df=1)),
        ]
    )
    classifier = LogisticRegression(max_iter=1000, class_weight="balanced")
    return Pipeline([("features", features), ("clf", classifier)])


@dataclass
class TrainedClassifier:
    pipeline: Pipeline
    labels: list[str] = field(default_factory=list)

    def predict(self, text: str) -> tuple[str, dict[str, float]]:
        probabilities = self.pipeline.predict_proba([text])[0]
        label_probs = {
            label: float(probability) for label, probability in zip(self.pipeline.classes_, probabilities)
        }
        top_label = max(label_probs, key=label_probs.get)
        return top_label, label_probs

    def evaluate(self, samples: list[tuple[str, str]]) -> dict[str, Any]:
        texts = [text for text, _ in samples]
        true_labels = [label for _, label in samples]
        predicted = list(self.pipeline.predict(texts))

        report = classification_report(true_labels, predicted, output_dict=True, zero_division=0)
        accuracy = report.pop("accuracy")
        macro_avg = report.pop("macro avg", None)
        weighted_avg = report.pop("weighted avg", None)
        return {
            "accuracy": accuracy,
            "macro_avg": macro_avg,
            "weighted_avg": weighted_avg,
            "per_class": report,
            "sample_count": len(samples),
        }


def train(samples: list[tuple[str, str]]) -> TrainedClassifier:
    if not samples:
        raise ValueError("cannot train on an empty sample list")

    texts = [text for text, _ in samples]
    labels = [label for _, label in samples]
    pipeline = _build_pipeline()
    pipeline.fit(texts, labels)
    return TrainedClassifier(pipeline=pipeline, labels=sorted(set(labels)))


def save(model: TrainedClassifier, path: Path) -> str:
    """Serialize `model` to `path`. Returns the written file's sha256 hex digest."""
    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, path)
    return _sha256_file(path)


def load(path: Path, expected_sha256: str) -> TrainedClassifier:
    """Load and verify. Raises `FileNotFoundError` / `ArtifactIntegrityError`
    rather than returning an artifact the registry didn't vouch for.
    """
    if not path.exists():
        raise FileNotFoundError(str(path))

    actual = _sha256_file(path)
    if actual != expected_sha256:
        raise ArtifactIntegrityError(
            f"checksum mismatch for {path.name}: expected {expected_sha256}, got {actual}"
        )
    return joblib.load(path)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()
