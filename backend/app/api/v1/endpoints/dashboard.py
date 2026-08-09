"""Control Panel read APIs.

The browser talks to this gateway and to nothing else — never to WAHA, Qdrant,
Redis, PostgreSQL or the ML Service (08_Dashboard/01_Control_Panel_Overview.md
§4). Everything here is read-only, aggregate, and free of message content.

Auth: every endpoint here requires a signed-in operator (`app/core/security.py`,
`require_operator`). The old `DASHBOARD_API_KEY` shared secret is gone — it
authenticated a deployment rather than a person, and its "empty means open"
default meant the gate was off exactly where it was easiest to forget. RBAC is
still Planned: any operator who can sign in sees everything on this router.
"""

import logging

from fastapi import APIRouter, Depends, Query

from app.core.config import get_settings
from app.core.security import require_operator
from app.services import dashboard
from app.services.health import service_health

logger = logging.getLogger("app.api.dashboard")

# One gate for the whole router: a new endpoint is protected by existing, not by
# the author remembering to add a dependency.
router = APIRouter(dependencies=[Depends(require_operator)])


@router.get("/dashboard/summary")
async def dashboard_summary() -> dict[str, object]:
    settings = get_settings()
    try:
        return {"available": True, **(await dashboard.summary(settings))}
    except Exception:  # noqa: BLE001
        logger.error("dashboard summary query failed", exc_info=True)
        return {
            "available": False,
            "reason": "database_unavailable",
            "window_hours": settings.dashboard_window_hours,
        }


@router.get("/dashboard/activity")
async def dashboard_activity(limit: int = Query(default=25, ge=1, le=100)) -> dict[str, object]:
    """Live Activity feed.

    Polling, not SSE/WebSocket: the transport decision is still open
    (08_Dashboard/02_Command_Center.md §4), so the simplest option that needs no
    extra Redis pub/sub channel is used and marked temporary.
    """
    settings = get_settings()
    try:
        return {"available": True, "transport": "polling", "items": await dashboard.recent_activity(limit, settings)}
    except Exception:  # noqa: BLE001
        logger.error("dashboard activity query failed", exc_info=True)
        return {"available": False, "reason": "database_unavailable", "items": []}


@router.get("/dashboard/recent")
async def dashboard_recent(limit: int = Query(default=10, ge=1, le=50)) -> dict[str, object]:
    """Recent threats / incidents / alerts.

    Only threats have a data source today. Incidents and alerts report
    `available: false` rather than an empty list that would read as "none
    happened" (08_Dashboard, 05_Incident_Management and 04_Alert_Center are
    Planned).
    """
    settings = get_settings()
    try:
        threats = {"available": True, "items": await dashboard.recent_threats(limit, settings)}
    except Exception:  # noqa: BLE001
        logger.error("recent threats query failed", exc_info=True)
        threats = {"available": False, "reason": "database_unavailable", "items": []}

    return {
        "threats": threats,
        "incidents": dashboard.unavailable("incidents_table_not_implemented"),
        "alerts": dashboard.unavailable("alerts_table_not_implemented"),
    }


@router.get("/system/services")
async def system_services() -> dict[str, object]:
    return await service_health(get_settings())


@router.get("/whatsapp/sessions")
async def whatsapp_sessions() -> dict[str, object]:
    """Normalised WAHA session list — the frontend never calls WAHA itself."""
    from app.clients.waha_client import WahaClient

    sessions = await WahaClient(get_settings()).list_sessions()
    return {
        "available": bool(sessions),
        "active": sum(1 for session in sessions if session.get("status") == "WORKING"),
        "sessions": sessions,
    }
