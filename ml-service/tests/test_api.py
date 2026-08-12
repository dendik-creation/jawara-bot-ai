"""`/v1` endpoint contract: envelope, auth, structured errors, repair path."""

import hashlib
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api.v1.endpoints import inference as inference_endpoints
from app.core.config import get_settings
from app.llm.base import LlmProvider
from app.main import app
from app.models.registry import registry

API_KEY = get_settings().ml_service_api_key
HEADERS = {"X-Internal-Api-Key": API_KEY}

KITOLOD_PAYLOAD = {
    "fact_item_id": "c39a04f2-5b9e-4a6c-9407-1d82136e0510",
    "category": "HEALTH_HOAX",
    "title": "Klaim Daun Kitolod",
    "claim_text": "Air rebusan daun kitolod menyembuhkan katarak.",
    "fact_explanation": "Kemenkes menegaskan hal ini berbahaya.",
    "verdict": "HOAX",
    "source_url": "https://turnbackhoax.id/x",
    "is_active": True,
}


class FakeRepository:
    """Stands in for Qdrant: records upserts, replays canned search hits."""

    def __init__(self, hits: list[dict[str, Any]] | None = None, fail: Exception | None = None) -> None:
        self.hits = hits or []
        self.fail = fail
        self.upserted: list[Any] = []

    async def health(self):
        if self.fail:
            raise self.fail
        return {"collection": "fact_knowledge_base", "vector_size": 1536, "points_count": len(self.upserted)}

    async def search(self, vector, category=None, top_k=None, score_threshold=None):
        if self.fail:
            raise self.fail
        self.last_query = {"category": category, "top_k": top_k, "score_threshold": score_threshold}
        return self.hits

    async def upsert_facts(self, points):
        if self.fail:
            raise self.fail
        self.upserted.extend(points)
        return len(points)

    @staticmethod
    def build_point(fact_item_id, vector, payload):
        return {"id": fact_item_id, "vector": vector, "payload": payload}

    async def close(self):
        return None


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        test_client.app.state.qdrant = FakeRepository()
        yield test_client


def envelope(payload: dict[str, Any]) -> dict[str, Any]:
    return {"request_id": "req-1", "payload": payload, "metadata": {}}


# --------------------------------------------------------------------------
# Auth and envelope
# --------------------------------------------------------------------------


def test_inference_requires_the_internal_api_key(client):
    response = client.post("/v1/embed", json=envelope({"texts": ["halo"]}))

    assert response.status_code == 401
    assert response.json()["error_code"] == "unauthorized"


def test_liveness_is_unauthenticated_for_the_container_healthcheck(client):
    assert client.get("/v1/health").json() == {"status": "ok"}


def test_response_carries_request_id_and_model_version(client):
    body = client.post("/v1/embed", json=envelope({"texts": ["halo"]}), headers=HEADERS).json()

    assert body["request_id"] == "req-1"
    assert body["model_version"] == registry.active_embedder
    assert body["latency_ms"] is not None
    assert body["result"]["dim"] == get_settings().embedding_dim


def test_invalid_payload_returns_a_structured_error(client):
    body = client.post("/v1/embed", json=envelope({"texts": "halo"}), headers=HEADERS).json()

    assert body["error_code"] == "invalid_payload"
    assert body["retryable"] is False


# --------------------------------------------------------------------------
# RAG retrieval
# --------------------------------------------------------------------------


def test_rag_query_applies_the_documented_filters_and_threshold(client):
    repository = FakeRepository(hits=[{**KITOLOD_PAYLOAD, "score": 0.91}])
    client.app.state.qdrant = repository

    body = client.post(
        "/v1/rag-query",
        json=envelope({"query": "daun kitolod katarak", "category": "HEALTH_HOAX"}),
        headers=HEADERS,
    ).json()

    assert repository.last_query == {"category": "HEALTH_HOAX", "top_k": 3, "score_threshold": 0.80}
    assert body["result"]["unverified"] is False
    assert body["confidence"] == 0.91


def test_below_threshold_query_returns_an_explicit_unverified_signal(client):
    client.app.state.qdrant = FakeRepository(hits=[])

    body = client.post(
        "/v1/rag-query", json=envelope({"query": "sesuatu yang tak dikenal"}), headers=HEADERS
    ).json()

    # Not "here is the closest thing we had".
    assert body["result"]["matches"] == []
    assert body["result"]["unverified"] is True
    assert body["confidence"] == 0.0


def test_vector_store_outage_is_retryable_and_structured(client):
    client.app.state.qdrant = FakeRepository(fail=ConnectionError("qdrant down"))

    response = client.post("/v1/rag-query", json=envelope({"query": "halo"}), headers=HEADERS)

    assert response.status_code == 503
    assert response.json()["error_code"] == "retrieval_unavailable"
    assert response.json()["retryable"] is True


# --------------------------------------------------------------------------
# Generation
# --------------------------------------------------------------------------


def test_generate_returns_the_four_sections(client):
    body = client.post(
        "/v1/generate",
        json=envelope(
            {
                "user_text": "benarkah daun kitolod menyembuhkan katarak?",
                "category": "HEALTH_HOAX",
                "risk_level": "HIGH",
                "context": [{**KITOLOD_PAYLOAD, "score": 0.91}],
            }
        ),
        headers=HEADERS,
    ).json()

    sections = body["result"]["sections"]
    assert set(sections) == {"status", "explanation", "reference", "forward"}
    assert all(sections[name] for name in sections)
    assert all(line.startswith(">") for line in sections["forward"].splitlines())


def test_malformed_llm_output_is_repaired_before_dispatch(client, monkeypatch):
    class BrokenProvider(LlmProvider):
        name = "broken"
        version = "test"

        async def generate(self, request):
            return "ini balasan tanpa struktur apa pun"

    monkeypatch.setattr(registry, "llm", lambda *_: BrokenProvider())

    body = client.post(
        "/v1/generate",
        json=envelope({"user_text": "halo", "category": "GENERAL_NEWS", "risk_level": "MEDIUM"}),
        headers=HEADERS,
    ).json()

    assert body["result"]["fallback_used"] is True
    assert body["result"]["fallback_reason"].startswith("contract:")
    # The user never sees the broken text.
    assert body["result"]["message"] != "ini balasan tanpa struktur apa pun"
    assert body["result"]["sections"]["forward"].startswith(">")


def test_provider_failure_falls_back_instead_of_returning_an_error(client, monkeypatch):
    from app.core.errors import MlError

    class DownProvider(LlmProvider):
        name = "down"
        version = "test"

        async def generate(self, request):
            raise MlError("llm_timeout", "timed out", status_code=504, retryable=False)

    monkeypatch.setattr(registry, "llm", lambda *_: DownProvider())

    body = client.post(
        "/v1/generate",
        json=envelope({"user_text": "halo", "category": "GENERAL_NEWS", "risk_level": "MEDIUM"}),
        headers=HEADERS,
    ).json()

    assert body["result"]["fallback_used"] is True
    assert body["result"]["fallback_reason"] == "llm_timeout"
    assert body["model_version"] == "template-composer-v1"


def test_empty_user_text_is_rejected(client):
    body = client.post("/v1/generate", json=envelope({"user_text": "  "}), headers=HEADERS).json()
    assert body["error_code"] == "invalid_payload"


# --------------------------------------------------------------------------
# Classification: train, evaluate, classify
# --------------------------------------------------------------------------

TRAIN_SAMPLES = [
    {"text": "Air rebusan daun kitolod sembuhkan katarak tanpa operasi", "label": "HEALTH_HOAX"},
    {"text": "Obat herbal ampuh sembuhkan kanker tanpa efek samping", "label": "HEALTH_HOAX"},
    {"text": "Jahe merah terbukti sembuhkan diabetes permanen", "label": "HEALTH_HOAX"},
    {"text": "Selamat anda menang hadiah 100 juta transfer biaya admin dulu", "label": "FINANCIAL_FRAUD"},
    {"text": "Rekening anda diblokir kirim kode OTP sekarang", "label": "FINANCIAL_FRAUD"},
    {"text": "Anda menang undian segera transfer biaya pajak hadiah", "label": "FINANCIAL_FRAUD"},
    {"text": "Oke nanti malam jadi ketemuan jam 7 ya", "label": "NOT_A_THREAT"},
    {"text": "Makasih infonya, aku otw ke kantor", "label": "NOT_A_THREAT"},
    {"text": "Besok libur, jangan lupa bawa laptop buat presentasi", "label": "NOT_A_THREAT"},
]

EVAL_SAMPLES = [
    {"text": "Minyak kutus kutus ampuh sembuhkan stroke tanpa efek samping", "label": "HEALTH_HOAX"},
    {"text": "Kartu ATM anda akan diblokir, balas dengan PIN untuk verifikasi", "label": "FINANCIAL_FRAUD"},
    {"text": "Udah sampai rumah, kamu udah makan belum", "label": "NOT_A_THREAT"},
]


@pytest.fixture
def isolated_classifier(tmp_path, monkeypatch):
    """Artifacts land in a throwaway directory, and each test starts with an
    empty in-memory cache — the registry singleton is shared across the whole
    test module, so a leaked path or a leaked cached model would bleed into
    unrelated tests.
    """
    monkeypatch.setattr(registry, "_artifact_dir", tmp_path)
    monkeypatch.setattr(registry, "_classifiers", {})
    monkeypatch.setattr(inference_endpoints, "_artifact_path", lambda model_version: tmp_path / f"{model_version}.joblib")
    return tmp_path


def _train(client, samples=TRAIN_SAMPLES) -> dict[str, Any]:
    return client.post(
        "/v1/train",
        json=envelope({"dataset": {"id": "ds-1", "name": "train", "version": 1, "samples": samples}, "base_model": "tfidf-logreg", "config": {}}),
        headers=HEADERS,
    ).json()


def test_train_produces_a_real_artifact_with_a_verifiable_checksum(client, isolated_classifier):
    body = _train(client)

    assert body["result"]["train_metrics"]["accuracy"] > 0
    assert body["result"]["label_counts"] == {"HEALTH_HOAX": 3, "FINANCIAL_FRAUD": 3, "NOT_A_THREAT": 3}
    model_version = body["model_version"]
    artifact_path = isolated_classifier / f"{model_version}.joblib"
    assert artifact_path.exists()
    assert hashlib.sha256(artifact_path.read_bytes()).hexdigest() == body["result"]["artifact_sha256"]


def test_train_rejects_an_empty_sample_list(client, isolated_classifier):
    body = client.post(
        "/v1/train",
        json=envelope({"dataset": {"samples": []}, "base_model": "tfidf-logreg", "config": {}}),
        headers=HEADERS,
    ).json()

    assert body["error_code"] == "invalid_payload"


def test_evaluate_scores_a_trained_model_against_held_out_samples(client, isolated_classifier):
    trained = _train(client)

    body = client.post(
        "/v1/evaluate",
        json=envelope(
            {
                "model_version": trained["model_version"],
                "expected_sha256": trained["result"]["artifact_sha256"],
                "dataset": {"id": "ds-2", "name": "eval", "version": 1, "samples": EVAL_SAMPLES},
            }
        ),
        headers=HEADERS,
    ).json()

    assert body["model_version"] == trained["model_version"]
    assert 0.0 <= body["result"]["accuracy"] <= 1.0
    assert body["result"]["sample_count"] == len(EVAL_SAMPLES)
    assert body["confidence"] == body["result"]["accuracy"]


def test_evaluate_rejects_a_checksum_that_does_not_match_the_artifact(client, isolated_classifier):
    trained = _train(client)

    response = client.post(
        "/v1/evaluate",
        json=envelope(
            {
                "model_version": trained["model_version"],
                "expected_sha256": "0" * 64,
                "dataset": {"samples": EVAL_SAMPLES},
            }
        ),
        headers=HEADERS,
    )

    assert response.status_code == 409
    assert response.json()["error_code"] == "artifact_integrity_failed"


def test_evaluate_rejects_an_unknown_model_version(client, isolated_classifier):
    response = client.post(
        "/v1/evaluate",
        json=envelope({"model_version": "clf-does-not-exist", "expected_sha256": "a" * 64, "dataset": {"samples": EVAL_SAMPLES}}),
        headers=HEADERS,
    )

    assert response.status_code == 503
    assert response.json()["error_code"] == "model_not_available"


def test_classify_predicts_with_a_trained_and_verified_model(client, isolated_classifier):
    trained = _train(client)

    body = client.post(
        "/v1/classify",
        json=envelope(
            {
                "text": "Anda terpilih menang hadiah, segera transfer biaya admin",
                "model_version": trained["model_version"],
                "expected_sha256": trained["result"]["artifact_sha256"],
            }
        ),
        headers=HEADERS,
    ).json()

    assert body["result"]["category"] in {"HEALTH_HOAX", "FINANCIAL_FRAUD", "NOT_A_THREAT"}
    assert body["confidence"] == body["result"]["probabilities"][body["result"]["category"]]
    assert body["model_version"] == trained["model_version"]


def test_classify_rejects_a_checksum_that_does_not_match_the_artifact(client, isolated_classifier):
    trained = _train(client)

    response = client.post(
        "/v1/classify",
        json=envelope({"text": "halo", "model_version": trained["model_version"], "expected_sha256": "0" * 64}),
        headers=HEADERS,
    )

    assert response.status_code == 409
    assert response.json()["error_code"] == "artifact_integrity_failed"


def test_classify_reports_model_not_available_rather_than_faking_a_verdict(client):
    response = client.post("/v1/classify", json=envelope({"text": "halo"}), headers=HEADERS)

    assert response.status_code == 503
    assert response.json()["error_code"] == "model_not_available"
    assert response.json()["retryable"] is False


def test_classify_rejects_empty_text(client):
    body = client.post(
        "/v1/classify", json=envelope({"text": "  ", "model_version": "clf-x", "expected_sha256": "a" * 64}), headers=HEADERS
    ).json()

    assert body["error_code"] == "invalid_payload"


# --------------------------------------------------------------------------
# Knowledge ingestion
# --------------------------------------------------------------------------


def test_kb_upsert_embeds_and_stores_with_the_fact_item_id_as_point_id(client):
    repository = FakeRepository()
    client.app.state.qdrant = repository

    body = client.post(
        "/v1/kb/upsert", json=envelope({"items": [KITOLOD_PAYLOAD]}), headers=HEADERS
    ).json()

    assert body["result"]["upserted"] == 1
    point = repository.upserted[0]
    assert point["id"] == KITOLOD_PAYLOAD["fact_item_id"]
    assert point["payload"]["category"] == "HEALTH_HOAX"
    assert point["payload"]["is_active"] is True
    assert len(point["vector"]) == get_settings().embedding_dim


def test_kb_upsert_rejects_incomplete_items_but_keeps_the_good_ones(client):
    repository = FakeRepository()
    client.app.state.qdrant = repository

    body = client.post(
        "/v1/kb/upsert",
        json=envelope({"items": [KITOLOD_PAYLOAD, {"fact_item_id": "x", "category": "HEALTH_HOAX"}]}),
        headers=HEADERS,
    ).json()

    assert body["result"]["upserted"] == 1
    assert body["result"]["rejected"][0]["fact_item_id"] == "x"


# --------------------------------------------------------------------------
# Readiness
# --------------------------------------------------------------------------


def test_ready_reports_models_and_vector_store(client):
    body = client.get("/v1/ready", headers=HEADERS).json()

    assert body["status"] == "ready"
    assert body["models"]["loaded"] is True
    assert body["models"]["embedder"]
    assert body["models"]["llm"]


def test_ready_is_not_ready_when_the_vector_store_is_down(client):
    client.app.state.qdrant = FakeRepository(fail=ConnectionError("down"))

    response = client.get("/v1/ready", headers=HEADERS)

    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"
