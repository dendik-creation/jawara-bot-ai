"""`/v1` endpoint contract: envelope, auth, structured errors, repair path."""

from typing import Any

import pytest
from fastapi.testclient import TestClient

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
# Classification (no trained model yet)
# --------------------------------------------------------------------------


def test_classify_reports_model_not_available_rather_than_faking_a_verdict(client):
    response = client.post("/v1/classify", json=envelope({"text": "halo"}), headers=HEADERS)

    assert response.status_code == 503
    assert response.json()["error_code"] == "model_not_available"
    assert response.json()["retryable"] is False


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
