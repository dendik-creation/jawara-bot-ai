"""AI/ML Knowledge Base — CRUD + real sync API (04_AI_and_ML/03_Knowledge_Base.md).

Sync routes proxy through `app.services.knowledge.sync_fact_items`, which
calls the real ML Service `/v1/kb/upsert` (see that module's docstring for
why no raw-document upload/parse/chunk pipeline lives here this stage).
"""

import csv
import io
import logging
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile, status
from starlette.concurrency import run_in_threadpool

from app.core.config import get_settings
from app.core.security import require_operator
from app.ingestion import available_sources
from app.schemas.knowledge import (
    FactItemActionRequest,
    FactItemCreateRequest,
    FactSourceCreateRequest,
    FactSourceUpdateRequest,
    IngestionRunRequest,
)
from app.services import fact_ingestion, knowledge
from app.services.audit import record_audit
from app.services.auth import Operator

logger = logging.getLogger("app.api.knowledge")

router = APIRouter(dependencies=[Depends(require_operator)])

CSV_MAX_BYTES = 2 * 1024 * 1024
CSV_MAX_ROWS = 500


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.get("/knowledge/facts")
async def list_fact_items(
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    category: str | None = Query(default=None),
    verdict: str | None = Query(default=None),
    is_active: bool | None = Query(default=None),
    source_id: int | None = Query(default=None),
    search: str | None = Query(default=None),
) -> dict[str, object]:
    try:
        return {
            "available": True,
            **(
                await knowledge.list_fact_items(
                    limit,
                    offset,
                    category=category,
                    verdict=verdict,
                    is_active=is_active,
                    source_id=source_id,
                    search=search,
                )
            ),
        }
    except Exception:  # noqa: BLE001
        logger.error("fact items query failed", exc_info=True)
        return {"available": False, "reason": "database_unavailable", "items": [], "total": 0}


@router.get("/knowledge/facts/{fact_item_id}")
async def get_fact_item(fact_item_id: UUID) -> dict[str, object]:
    result = await knowledge.get_fact_item(str(fact_item_id))
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="fact item not found")
    return result


@router.post("/knowledge/facts", status_code=status.HTTP_201_CREATED)
async def create_fact_item(
    payload: FactItemCreateRequest, request: Request, operator: Operator = Depends(require_operator)
) -> dict[str, object]:
    try:
        result = await knowledge.create_fact_item(
            payload.source_id,
            payload.category,
            payload.title,
            payload.claim_summary,
            payload.fact_explanation,
            payload.verdict,
            payload.source_url,
        )
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from None

    await record_audit(
        actor_operator_id=operator.id,
        action="knowledge.fact_created",
        target_type="fact_item",
        target_id=result["id"],
        result="SUCCESS",
        metadata={"title": payload.title, "category": payload.category, "verdict": payload.verdict},
        ip_address=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return result


@router.patch("/knowledge/facts/{fact_item_id}")
async def action_on_fact_item(
    fact_item_id: UUID,
    payload: FactItemActionRequest,
    request: Request,
    operator: Operator = Depends(require_operator),
) -> dict[str, object]:
    try:
        result = await knowledge.apply_fact_item_action(
            str(fact_item_id),
            action=payload.action,
            category=payload.category,
            title=payload.title,
            claim_summary=payload.claim_summary,
            fact_explanation=payload.fact_explanation,
            verdict=payload.verdict,
            source_url=payload.source_url,
        )
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from None

    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="fact item not found")

    previous_active = result.pop("previous_active", None)
    audit_action = "knowledge.fact_updated" if payload.action == "UPDATE" else "knowledge.fact_status_changed"
    await record_audit(
        actor_operator_id=operator.id,
        action=audit_action,
        target_type="fact_item",
        target_id=str(fact_item_id),
        result="SUCCESS",
        metadata={
            "action": payload.action,
            "previous_active": previous_active,
            "new_active": result["is_active"] if payload.action != "UPDATE" else None,
        },
        ip_address=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return result


@router.post("/knowledge/facts/{fact_item_id}/sync")
async def sync_fact_item(
    fact_item_id: UUID, request: Request, operator: Operator = Depends(require_operator)
) -> dict[str, object]:
    result = await knowledge.sync_fact_items([str(fact_item_id)])

    await record_audit(
        actor_operator_id=operator.id,
        action="knowledge.fact_synced",
        target_type="fact_item",
        target_id=str(fact_item_id),
        result="SUCCESS" if result["failed"] == 0 else "FAILED",
        metadata=result,
        ip_address=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return result


@router.post("/knowledge/facts/sync-all")
async def sync_all_fact_items(request: Request, operator: Operator = Depends(require_operator)) -> dict[str, object]:
    result = await knowledge.sync_fact_items(None)

    await record_audit(
        actor_operator_id=operator.id,
        action="knowledge.fact_sync_all",
        target_type="fact_item",
        target_id=None,
        result="SUCCESS" if result["failed"] == 0 else "FAILED",
        metadata=result,
        ip_address=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return result


@router.post("/knowledge/facts/import-csv")
async def import_fact_items_csv(
    request: Request,
    file: UploadFile = File(...),
    operator: Operator = Depends(require_operator),
) -> dict[str, object]:
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="file harus berformat .csv")

    raw = await file.read()
    if len(raw) > CSV_MAX_BYTES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="file melebihi 2MB")

    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="file harus berenkode UTF-8") from None

    reader = csv.DictReader(io.StringIO(text))
    required = set(knowledge.CSV_REQUIRED_COLUMNS)
    if reader.fieldnames is None or not required.issubset(set(reader.fieldnames)):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"header CSV harus memuat kolom: {', '.join(sorted(required))}",
        )

    rows = list(reader)
    if not rows:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="file CSV kosong")
    if len(rows) > CSV_MAX_ROWS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"maksimum {CSV_MAX_ROWS} baris per file")

    result = await knowledge.import_fact_items_csv(rows)

    await record_audit(
        actor_operator_id=operator.id,
        action="knowledge.facts_imported",
        target_type="fact_item",
        target_id=None,
        result="SUCCESS" if result["failed"] == 0 else "FAILED",
        metadata={"total": result["total"], "created": result["created"], "failed": result["failed"]},
        ip_address=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return result


# --------------------------------------------------------------------------
# Automatic ingestion — observability and manual trigger
#
# The crawl itself always runs in the Celery worker, never in the request:
# this route enqueues, it does not scrape. Read routes degrade the same way
# the list routes above do, so a database hiccup greys out one card instead
# of failing the page.
# --------------------------------------------------------------------------


@router.get("/knowledge/ingestion/status")
async def ingestion_status() -> dict[str, object]:
    try:
        return {**(await fact_ingestion.get_ingestion_status()), "known_sources": available_sources()}
    except Exception:  # noqa: BLE001
        logger.error("ingestion status query failed", exc_info=True)
        return {"available": False, "reason": "database_unavailable", "sources": []}


@router.get("/knowledge/ingestion/runs")
async def list_ingestion_runs(
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    source: str | None = Query(default=None),
) -> dict[str, object]:
    try:
        return {
            "available": True,
            **(await fact_ingestion.list_ingestion_runs(limit, offset, source_slug=source)),
        }
    except Exception:  # noqa: BLE001
        logger.error("ingestion runs query failed", exc_info=True)
        return {"available": False, "reason": "database_unavailable", "items": [], "total": 0}


@router.post("/knowledge/ingestion/run", status_code=status.HTTP_202_ACCEPTED)
async def trigger_ingestion(
    payload: IngestionRunRequest, request: Request, operator: Operator = Depends(require_operator)
) -> dict[str, object]:
    known = available_sources()
    if payload.source and payload.source not in known:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"sumber tidak dikenal: {payload.source} (tersedia: {', '.join(known)})",
        )

    from app.worker import TASK_INGEST_FACT_CHECKS, celery_app

    settings = get_settings()
    try:
        result = await run_in_threadpool(
            celery_app.send_task,
            TASK_INGEST_FACT_CHECKS,
            kwargs={"source": payload.source, "triggered_by": "MANUAL"},
            queue=settings.celery_ingestion_queue_name,
        )
        task_id = result.id
    except Exception:  # noqa: BLE001
        logger.error("failed to dispatch ingestion task", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="antrean tidak tersedia"
        ) from None

    await record_audit(
        actor_operator_id=operator.id,
        action="knowledge.ingestion_triggered",
        target_type="fact_source",
        target_id=payload.source,
        result="SUCCESS",
        metadata={"source": payload.source or "all", "task_id": task_id},
        ip_address=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return {"queued": True, "task_id": task_id, "source": payload.source or "all"}


@router.get("/knowledge/sources")
async def list_fact_sources() -> dict[str, object]:
    try:
        return {"available": True, "items": await knowledge.list_fact_sources()}
    except Exception:  # noqa: BLE001
        logger.error("fact sources query failed", exc_info=True)
        return {"available": False, "reason": "database_unavailable", "items": []}


@router.post("/knowledge/sources", status_code=status.HTTP_201_CREATED)
async def create_fact_source(
    payload: FactSourceCreateRequest, request: Request, operator: Operator = Depends(require_operator)
) -> dict[str, object]:
    result = await knowledge.create_fact_source(
        payload.name, payload.base_url, payload.is_trusted, payload.reliability_score
    )

    await record_audit(
        actor_operator_id=operator.id,
        action="knowledge.source_created",
        target_type="fact_source",
        target_id=str(result["id"]),
        result="SUCCESS",
        metadata={
            "name": payload.name,
            "base_url": payload.base_url,
            "is_trusted": payload.is_trusted,
            "reliability_score": result["reliability_score"],
        },
        ip_address=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return result


@router.patch("/knowledge/sources/{source_id}")
async def update_fact_source(
    source_id: int,
    payload: FactSourceUpdateRequest,
    request: Request,
    operator: Operator = Depends(require_operator),
) -> dict[str, object]:
    """Change a source's reliability score / trust flag.

    The score is denormalised into every one of this source's facts inside
    Qdrant, so unless `resync` is false the affected facts are pushed back
    through the existing sync path here — an edit that changed nothing about
    retrieval would be worse than no edit at all. A failed re-sync is reported,
    not hidden: the score change itself has already committed.
    """
    try:
        result = await knowledge.apply_fact_source_action(
            source_id,
            reliability_score=payload.reliability_score,
            is_trusted=payload.is_trusted,
        )
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from None

    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="fact source not found")

    previous = result.pop("previous_reliability", None)
    resync: dict[str, object] | None = None
    if payload.resync and payload.reliability_score is not None:
        ids = await knowledge.fact_item_ids_for_source(source_id)
        if ids:
            try:
                resync = await knowledge.sync_fact_items(ids)
            except Exception as error:  # noqa: BLE001 — the score change stands either way
                logger.error("resync after reliability change failed", exc_info=True)
                resync = {"failed": len(ids), "error": type(error).__name__}

    await record_audit(
        actor_operator_id=operator.id,
        action="knowledge.source_updated",
        target_type="fact_source",
        target_id=str(source_id),
        result="SUCCESS" if not (resync and resync.get("failed")) else "FAILED",
        metadata={
            "previous_reliability": previous,
            "reliability_score": result["reliability_score"],
            "is_trusted": result["is_trusted"],
            "resync": resync,
        },
        ip_address=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return {**result, "resync": resync}
