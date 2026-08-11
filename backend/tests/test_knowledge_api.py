"""AI/ML Knowledge Base: fact_item guards, sync outcomes, and routes."""

from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.core.security import require_operator
from app.main import app
from app.services import knowledge
from app.services.auth import Operator

client = TestClient(app)

OPERATOR = Operator(
    id="11111111-1111-1111-1111-111111111111",
    email="ops@example.com",
    full_name="Operator Satu",
    is_active=True,
)

FACT_ID = "66666666-6666-6666-6666-666666666666"


@pytest.fixture(autouse=True)
def signed_in():
    app.dependency_overrides[require_operator] = lambda: OPERATOR
    yield
    app.dependency_overrides.pop(require_operator, None)


def _item(**overrides: object) -> dict[str, object]:
    base = {
        "id": FACT_ID,
        "source_id": 1,
        "source_name": "Kominfo",
        "category": "HEALTH_HOAX",
        "title": "Vaksin mengandung chip",
        "claim_summary": "Klaim bahwa vaksin mengandung microchip pelacak",
        "fact_explanation": "Tidak ada bukti ilmiah yang mendukung klaim ini",
        "verdict": "HOAX",
        "source_url": "https://kominfo.go.id/hoax/123",
        "is_active": True,
        "synced_at": None,
        "sync_error": None,
        "created_at": "2026-08-11T10:00:00+00:00",
        "updated_at": "2026-08-11T10:00:00+00:00",
    }
    base.update(overrides)
    return base


# --------------------------------------------------------------------------
# `apply_fact_item_action` guard — raises before touching the database
# --------------------------------------------------------------------------


async def test_update_with_no_fields_is_rejected_before_touching_the_database():
    with pytest.raises(ValueError, match="requires at least one field"):
        await knowledge.apply_fact_item_action(FACT_ID, action="UPDATE")


# --------------------------------------------------------------------------
# Routes — facts
# --------------------------------------------------------------------------


def test_list_fact_items_route_returns_available_payload(monkeypatch):
    monkeypatch.setattr(
        "app.services.knowledge.list_fact_items",
        AsyncMock(return_value={"total": 1, "items": [_item()]}),
    )

    body = client.get("/api/v1/knowledge/facts").json()

    assert body["available"] is True
    assert body["total"] == 1
    assert body["items"][0]["verdict"] == "HOAX"


def test_list_fact_items_route_reports_unavailable_on_db_outage(monkeypatch):
    monkeypatch.setattr(
        "app.services.knowledge.list_fact_items", AsyncMock(side_effect=ConnectionError("db down"))
    )

    body = client.get("/api/v1/knowledge/facts").json()

    assert body["available"] is False
    assert body["reason"] == "database_unavailable"


def test_get_fact_item_404s_when_missing(monkeypatch):
    monkeypatch.setattr("app.services.knowledge.get_fact_item", AsyncMock(return_value=None))

    response = client.get(f"/api/v1/knowledge/facts/{FACT_ID}")

    assert response.status_code == 404


def test_create_fact_item_writes_audit_log(monkeypatch):
    monkeypatch.setattr("app.services.knowledge.create_fact_item", AsyncMock(return_value=_item()))
    audit_mock = AsyncMock()
    monkeypatch.setattr("app.api.v1.endpoints.knowledge.record_audit", audit_mock)

    response = client.post(
        "/api/v1/knowledge/facts",
        json={
            "source_id": 1,
            "category": "HEALTH_HOAX",
            "title": "Vaksin mengandung chip",
            "claim_summary": "Klaim bahwa vaksin mengandung microchip pelacak",
            "fact_explanation": "Tidak ada bukti ilmiah yang mendukung klaim ini",
            "verdict": "HOAX",
            "source_url": "https://kominfo.go.id/hoax/123",
        },
    )

    assert response.status_code == 201
    audit_mock.assert_awaited_once()
    assert audit_mock.await_args.kwargs["action"] == "knowledge.fact_created"


def test_create_fact_item_rejects_unknown_source(monkeypatch):
    monkeypatch.setattr(
        "app.services.knowledge.create_fact_item",
        AsyncMock(side_effect=ValueError("source_id 999 does not exist")),
    )

    response = client.post(
        "/api/v1/knowledge/facts",
        json={
            "source_id": 999,
            "category": "HEALTH_HOAX",
            "title": "x",
            "claim_summary": "x",
            "fact_explanation": "x",
            "verdict": "HOAX",
            "source_url": "https://example.com",
        },
    )

    assert response.status_code == 400


def test_create_fact_item_rejects_unknown_category():
    response = client.post(
        "/api/v1/knowledge/facts",
        json={
            "source_id": 1,
            "category": "NOT_A_CATEGORY",
            "title": "x",
            "claim_summary": "x",
            "fact_explanation": "x",
            "verdict": "HOAX",
            "source_url": "https://example.com",
        },
    )
    assert response.status_code == 422


def test_action_on_fact_item_deactivates_and_writes_audit_log(monkeypatch):
    deactivated = _item(is_active=False)
    deactivated["previous_active"] = True
    monkeypatch.setattr("app.services.knowledge.apply_fact_item_action", AsyncMock(return_value=deactivated))
    audit_mock = AsyncMock()
    monkeypatch.setattr("app.api.v1.endpoints.knowledge.record_audit", audit_mock)

    response = client.patch(f"/api/v1/knowledge/facts/{FACT_ID}", json={"action": "DEACTIVATE"})

    assert response.status_code == 200
    assert response.json()["is_active"] is False
    assert "previous_active" not in response.json()
    metadata = audit_mock.await_args.kwargs["metadata"]
    assert metadata["previous_active"] is True
    assert metadata["new_active"] is False
    assert audit_mock.await_args.kwargs["action"] == "knowledge.fact_status_changed"


def test_action_on_fact_item_404s_when_missing(monkeypatch):
    monkeypatch.setattr("app.services.knowledge.apply_fact_item_action", AsyncMock(return_value=None))

    response = client.patch(f"/api/v1/knowledge/facts/{FACT_ID}", json={"action": "ACTIVATE"})

    assert response.status_code == 404


def test_action_on_fact_item_update_uses_updated_audit_action(monkeypatch):
    updated = _item(title="Judul baru")
    updated["previous_active"] = None
    monkeypatch.setattr("app.services.knowledge.apply_fact_item_action", AsyncMock(return_value=updated))
    audit_mock = AsyncMock()
    monkeypatch.setattr("app.api.v1.endpoints.knowledge.record_audit", audit_mock)

    response = client.patch(f"/api/v1/knowledge/facts/{FACT_ID}", json={"action": "UPDATE", "title": "Judul baru"})

    assert response.status_code == 200
    assert audit_mock.await_args.kwargs["action"] == "knowledge.fact_updated"


# --------------------------------------------------------------------------
# Routes — sync
# --------------------------------------------------------------------------


def test_sync_fact_item_route_reports_success(monkeypatch):
    monkeypatch.setattr(
        "app.services.knowledge.sync_fact_items",
        AsyncMock(return_value={"total": 1, "upserted": 1, "failed": 0, "rejected": []}),
    )
    audit_mock = AsyncMock()
    monkeypatch.setattr("app.api.v1.endpoints.knowledge.record_audit", audit_mock)

    response = client.post(f"/api/v1/knowledge/facts/{FACT_ID}/sync")

    assert response.status_code == 200
    assert response.json()["upserted"] == 1
    assert audit_mock.await_args.kwargs["result"] == "SUCCESS"
    assert audit_mock.await_args.kwargs["action"] == "knowledge.fact_synced"


def test_sync_fact_item_route_reports_failure_honestly(monkeypatch):
    monkeypatch.setattr(
        "app.services.knowledge.sync_fact_items",
        AsyncMock(return_value={"total": 1, "upserted": 0, "failed": 1, "rejected": []}),
    )
    audit_mock = AsyncMock()
    monkeypatch.setattr("app.api.v1.endpoints.knowledge.record_audit", audit_mock)

    response = client.post(f"/api/v1/knowledge/facts/{FACT_ID}/sync")

    assert response.status_code == 200
    assert response.json()["failed"] == 1
    assert audit_mock.await_args.kwargs["result"] == "FAILED"


def test_sync_all_fact_items_route(monkeypatch):
    monkeypatch.setattr(
        "app.services.knowledge.sync_fact_items",
        AsyncMock(return_value={"total": 5, "upserted": 4, "failed": 1, "rejected": [{"fact_item_id": "x"}]}),
    )
    audit_mock = AsyncMock()
    monkeypatch.setattr("app.api.v1.endpoints.knowledge.record_audit", audit_mock)

    response = client.post("/api/v1/knowledge/facts/sync-all")

    assert response.status_code == 200
    assert response.json()["total"] == 5
    assert audit_mock.await_args.kwargs["target_id"] is None
    assert audit_mock.await_args.kwargs["action"] == "knowledge.fact_sync_all"


# --------------------------------------------------------------------------
# Routes — sources
# --------------------------------------------------------------------------


def test_list_fact_sources_route(monkeypatch):
    monkeypatch.setattr(
        "app.services.knowledge.list_fact_sources",
        AsyncMock(return_value=[{"id": 1, "name": "Kominfo", "base_url": "https://kominfo.go.id", "is_trusted": True, "created_at": "2026-08-11T10:00:00+00:00"}]),
    )

    body = client.get("/api/v1/knowledge/sources").json()

    assert body["available"] is True
    assert body["items"][0]["name"] == "Kominfo"


# --------------------------------------------------------------------------
# Routes — CSV import
# --------------------------------------------------------------------------

CSV_HEADER = "source_id,category,title,claim_summary,fact_explanation,verdict,source_url\n"


def test_import_csv_rejects_non_csv_extension():
    response = client.post(
        "/api/v1/knowledge/facts/import-csv",
        files={"file": ("facts.txt", CSV_HEADER + "1,HOAX,x,x,x,HOAX,https://x\n", "text/plain")},
    )
    assert response.status_code == 400


def test_import_csv_rejects_oversized_file():
    huge_bytes = (CSV_HEADER + ("x" * (2 * 1024 * 1024 + 1))).encode()
    response = client.post(
        "/api/v1/knowledge/facts/import-csv",
        files={"file": ("facts.csv", huge_bytes, "text/csv")},
    )
    assert response.status_code == 400


def test_import_csv_rejects_missing_required_header():
    response = client.post(
        "/api/v1/knowledge/facts/import-csv",
        files={"file": ("facts.csv", b"title,category\nx,HOAX\n", "text/csv")},
    )
    assert response.status_code == 400


def test_import_csv_rejects_empty_file():
    response = client.post(
        "/api/v1/knowledge/facts/import-csv",
        files={"file": ("facts.csv", CSV_HEADER.encode(), "text/csv")},
    )
    assert response.status_code == 400


def test_import_csv_rejects_too_many_rows():
    rows = "\n".join(f"1,HEALTH_HOAX,t{i},c,e,HOAX,https://x/{i}" for i in range(1, 502))
    response = client.post(
        "/api/v1/knowledge/facts/import-csv",
        files={"file": ("facts.csv", (CSV_HEADER + rows).encode(), "text/csv")},
    )
    assert response.status_code == 400


def test_import_csv_success_writes_audit_log(monkeypatch):
    monkeypatch.setattr(
        "app.services.knowledge.import_fact_items_csv",
        AsyncMock(return_value={"total": 2, "created": 1, "failed": 1, "errors": [{"row": 2, "reason": "category tidak valid: X"}]}),
    )
    audit_mock = AsyncMock()
    monkeypatch.setattr("app.api.v1.endpoints.knowledge.record_audit", audit_mock)

    body = (
        CSV_HEADER
        + "1,HEALTH_HOAX,Judul,Klaim,Penjelasan,HOAX,https://x/1\n"
        + "1,X,Judul,Klaim,Penjelasan,HOAX,https://x/2\n"
    ).encode()

    response = client.post("/api/v1/knowledge/facts/import-csv", files={"file": ("facts.csv", body, "text/csv")})

    assert response.status_code == 200
    assert response.json()["created"] == 1
    assert response.json()["failed"] == 1
    assert audit_mock.await_args.kwargs["action"] == "knowledge.facts_imported"
    assert audit_mock.await_args.kwargs["result"] == "FAILED"


def test_create_fact_source_writes_audit_log(monkeypatch):
    monkeypatch.setattr(
        "app.services.knowledge.create_fact_source",
        AsyncMock(return_value={"id": 2, "name": "Turnbackhoax", "base_url": "https://turnbackhoax.id", "is_trusted": True, "created_at": "2026-08-11T10:00:00+00:00"}),
    )
    audit_mock = AsyncMock()
    monkeypatch.setattr("app.api.v1.endpoints.knowledge.record_audit", audit_mock)

    response = client.post(
        "/api/v1/knowledge/sources",
        json={"name": "Turnbackhoax", "base_url": "https://turnbackhoax.id", "is_trusted": True},
    )

    assert response.status_code == 201
    assert audit_mock.await_args.kwargs["action"] == "knowledge.source_created"
