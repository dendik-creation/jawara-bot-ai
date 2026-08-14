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

    # Category filter and threshold are the documented contract and unchanged.
    # `top_k` asked of Qdrant is larger than the `top_k` returned: re-ranking
    # overfetches so a trustworthy fourth match can overtake a shaky third.
    settings = get_settings()
    assert repository.last_query["category"] == "HEALTH_HOAX"
    assert repository.last_query["score_threshold"] == 0.80
    assert repository.last_query["top_k"] == settings.rag_top_k * settings.rag_rerank_overfetch
    assert body["result"]["top_k"] == settings.rag_top_k
    assert body["result"]["unverified"] is False
    assert body["confidence"] == 0.91


def test_rag_query_without_reranking_asks_for_exactly_top_k(client):
    repository = FakeRepository(hits=[{**KITOLOD_PAYLOAD, "score": 0.91}])
    client.app.state.qdrant = repository

    body = client.post(
        "/v1/rag-query",
        json=envelope({"query": "daun kitolod katarak", "rerank": False}),
        headers=HEADERS,
    ).json()

    assert repository.last_query["top_k"] == get_settings().rag_top_k
    assert body["result"]["reranked"] is False


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
# Deterministic status enforcement (`!link` false-positive fix, Part 1/12
# Cases 3-4) — the LLM's own status marker must never reach the user when it
# disagrees with the risk the URL-safety engine (or knowledge base) computed,
# even when the rest of the reply is perfectly well-formed.
# --------------------------------------------------------------------------


def _four_section_reply(status_line: str) -> str:
    return (
        f"{status_line}\n\n"
        "Bapak/Ibu, ini penjelasan singkat mengenai tautan tersebut.\n\n"
        "Sumber Resmi:\nhttps://cekbansos.kemensos.go.id/\n\n"
        "> *Pesan Penting untuk Keluarga:*\n"
        "> Mohon berhati-hati ya. 🙏"
    )


class FixedStatusProvider(LlmProvider):
    name = "fixed-status"
    version = "test"

    def __init__(self, status_line: str) -> None:
        self._status_line = status_line

    async def generate(self, request):
        return _four_section_reply(self._status_line)


def test_llm_cannot_upgrade_a_computed_unknown_to_a_dangerous_status(client, monkeypatch):
    # Case 3: computed risk_level=UNKNOWN, LLM prints the HIGH-shaped URL
    # marker anyway. The reply is otherwise perfectly well-formed — only the
    # status line disagrees with the deterministic risk — so this proves
    # `status_mismatch` specifically triggers the repair, not some other
    # structural defect.
    monkeypatch.setattr(registry, "llm", lambda *_: FixedStatusProvider("🔴 *BERBAHAYA*"))

    body = client.post(
        "/v1/generate",
        json=envelope(
            {
                "user_text": "!link https://contoh-domain-baru.com",
                "category": "PHISHING_LINK",
                "risk_level": "UNKNOWN",
                "url_verdicts": [{"url": "https://contoh-domain-baru.com", "risk": "UNKNOWN", "reason": "no_provider_available"}],
            }
        ),
        headers=HEADERS,
    ).json()

    assert body["result"]["fallback_used"] is True
    assert "status_mismatch" in body["result"]["fallback_reason"]
    # UNKNOWN's own marker — never the HIGH one the LLM tried to print, and
    # never rendered as if it were a confirmed hoax either.
    assert body["result"]["sections"]["status"] == "⚪ *BELUM TERVERIFIKASI*"
    assert "BERBAHAYA" not in body["result"]["message"]
    assert "HOAKS" not in body["result"]["message"]


def test_llm_cannot_downgrade_a_computed_high_risk_to_safe(client, monkeypatch):
    # Case 4: computed risk_level=HIGH (a provider confirmed the threat), LLM
    # prints the safe URL marker. HIGH must stand.
    monkeypatch.setattr(registry, "llm", lambda *_: FixedStatusProvider("🟢 *AMAN*"))

    body = client.post(
        "/v1/generate",
        json=envelope(
            {
                "user_text": "!link http://bansos-pemerintah-2026.com",
                "category": "PHISHING_LINK",
                "risk_level": "HIGH",
                "url_verdicts": [
                    {"url": "http://bansos-pemerintah-2026.com", "risk": "HIGH", "reason": "flagged_by=safe_browsing"}
                ],
            }
        ),
        headers=HEADERS,
    ).json()

    assert body["result"]["fallback_used"] is True
    assert "status_mismatch" in body["result"]["fallback_reason"]
    assert body["result"]["sections"]["status"] == "🔴 *BERBAHAYA*"


def test_llm_status_matching_the_computed_risk_is_dispatched_unmodified(client, monkeypatch):
    # The mirror case: agreement is not a violation, and the LLM's own text
    # (not the deterministic composer's) reaches the user.
    monkeypatch.setattr(registry, "llm", lambda *_: FixedStatusProvider("⚪ *BELUM TERVERIFIKASI*"))

    body = client.post(
        "/v1/generate",
        json=envelope({"user_text": "!link https://contoh-baru.com", "category": "PHISHING_LINK", "risk_level": "UNKNOWN"}),
        headers=HEADERS,
    ).json()

    assert body["result"]["fallback_used"] is False
    assert body["result"]["sections"]["status"] == "⚪ *BELUM TERVERIFIKASI*"


def test_trusted_domain_evidence_reaches_the_prompt_payload(client, monkeypatch):
    # Part 9: the model must be able to see *why* — not just the bare risk.
    captured: dict[str, object] = {}

    class RecordingProvider(LlmProvider):
        name = "recording"
        version = "test"

        async def generate(self, request):
            captured["url_verdicts"] = request.url_verdicts
            return _four_section_reply("🟢 *AMAN*")

    monkeypatch.setattr(registry, "llm", lambda *_: RecordingProvider())

    client.post(
        "/v1/generate",
        json=envelope(
            {
                "user_text": "!link https://www.pln.co.id",
                "category": "PHISHING_LINK",
                "risk_level": "LOW",
                "url_verdicts": [
                    {
                        "url": "https://www.pln.co.id",
                        "risk": "LOW",
                        "reason": "no_provider_flagged;trusted_official_domain=PLN",
                        "is_trusted": True,
                        "trusted_source_name": "PLN",
                    }
                ],
            }
        ),
        headers=HEADERS,
    )

    assert captured["url_verdicts"][0]["is_trusted"] is True
    assert captured["url_verdicts"][0]["trusted_source_name"] == "PLN"


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
