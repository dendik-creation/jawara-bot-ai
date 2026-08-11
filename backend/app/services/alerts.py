"""Alerts (09_Security/04_Alert_Center.md).

Only one source is wired today: a Threat resolved with the `ESCALATE` action
(`app/api/v1/endpoints/threats.py` calls `create_from_threat_escalation` after
a successful escalate). `source` stays a plain string, not an enum, so later
sources (platform health, aggregate thresholds, AI/ML ops — §5 of the spec
doc) can be added without a migration.
"""

import logging
from datetime import datetime
from typing import Any, Literal

import asyncpg

from app.core.config import Settings, get_settings

logger = logging.getLogger("app.services.alerts")

AlertAction = Literal["ACKNOWLEDGE", "RESOLVE", "ASSIGN_TO_ME"]

# Escalating a HIGH-risk threat is worse than escalating a MEDIUM one — this
# mapping is JAWARA's own default (the spec doesn't define one) and lives in
# one place so it's easy to revise.
_SEVERITY_FROM_RISK = {"HIGH": "CRITICAL", "MEDIUM": "HIGH"}

ITEM_SQL_BASE = """
SELECT
    a.id, a.severity::text AS severity, a.title, a.source, a.source_threat_id, a.source_incident_id,
    a.state::text AS state, a.assigned_operator_id, o.full_name AS assigned_operator_name,
    a.resolution_reason, a.created_at, a.updated_at
FROM alerts a
LEFT JOIN operators o ON o.id = a.assigned_operator_id
"""


async def _connect(settings: Settings) -> asyncpg.Connection:
    return await asyncpg.connect(settings.database_url, timeout=5)


def _row_to_item(row: asyncpg.Record) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "severity": row["severity"],
        "title": row["title"],
        "source": row["source"],
        "source_threat_id": str(row["source_threat_id"]) if row["source_threat_id"] else None,
        "source_incident_id": str(row["source_incident_id"]) if row["source_incident_id"] else None,
        "state": row["state"],
        "assigned_operator_id": str(row["assigned_operator_id"]) if row["assigned_operator_id"] else None,
        "assigned_operator_name": row["assigned_operator_name"],
        "resolution_reason": row["resolution_reason"],
        "created_at": row["created_at"].isoformat(),
        "updated_at": row["updated_at"].isoformat(),
    }


async def list_alerts(
    limit: int = 25,
    offset: int = 0,
    *,
    severity: str | None = None,
    state: str | None = None,
    source: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    settings = settings or get_settings()

    clauses: list[str] = []
    params: list[Any] = []

    def add(clause: str, value: Any) -> None:
        params.append(value)
        clauses.append(clause.format(len(params)))

    if severity:
        add("a.severity = ${}::alert_severity_enum", severity)
    if state:
        add("a.state = ${}::alert_state_enum", state)
    if source:
        add("a.source = ${}", source)
    if date_from:
        add("a.created_at >= ${}", date_from)
    if date_to:
        add("a.created_at <= ${}", date_to)

    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows_sql = (
        f"{ITEM_SQL_BASE} {where_sql} ORDER BY a.created_at DESC "
        f"LIMIT ${len(params) + 1} OFFSET ${len(params) + 2}"
    )
    count_sql = f"SELECT count(*) FROM alerts a {where_sql}"

    conn = await _connect(settings)
    try:
        rows = await conn.fetch(rows_sql, *params, limit, offset)
        total = await conn.fetchval(count_sql, *params)
    finally:
        await conn.close()

    return {"total": total, "items": [_row_to_item(row) for row in rows]}


async def create_from_threat_escalation(
    message_log_id: str,
    *,
    risk: str,
    threat_category: str,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Inserts one alert row for an escalated Threat. Called by the Threats
    route after a successful `ESCALATE` action — kept out of
    `services/threats.py` so Threats and Alerts don't import each other.
    """
    settings = settings or get_settings()
    severity = _SEVERITY_FROM_RISK.get(risk, "MEDIUM")
    title = f"Threat escalated: {threat_category} ({risk})"

    conn = await _connect(settings)
    try:
        inserted = await conn.fetchrow(
            """
            INSERT INTO alerts (severity, title, source, source_threat_id)
            VALUES ($1::alert_severity_enum, $2, 'threat_escalation', $3)
            RETURNING id
            """,
            severity,
            title,
            message_log_id,
        )
        row = await conn.fetchrow(f"{ITEM_SQL_BASE} WHERE a.id = $1", inserted["id"])
    finally:
        await conn.close()

    return _row_to_item(row)


async def create_from_incident_escalation(
    incident_id: str,
    *,
    severity: str,
    title: str,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Same shape as `create_from_threat_escalation`, sourced from an Incident
    instead of a Threat. Incident severity passes straight through — both
    already share `alert_severity_enum`, so there's no risk-to-severity guess
    to make this time.
    """
    settings = settings or get_settings()
    conn = await _connect(settings)
    try:
        inserted = await conn.fetchrow(
            """
            INSERT INTO alerts (severity, title, source, source_incident_id)
            VALUES ($1::alert_severity_enum, $2, 'incident_escalation', $3)
            RETURNING id
            """,
            severity,
            f"Incident escalated: {title}",
            incident_id,
        )
        row = await conn.fetchrow(f"{ITEM_SQL_BASE} WHERE a.id = $1", inserted["id"])
    finally:
        await conn.close()

    return _row_to_item(row)


async def apply_alert_action(
    alert_id: str,
    *,
    action: AlertAction,
    reason: str | None,
    actor_operator_id: str,
    settings: Settings | None = None,
) -> dict[str, Any] | None:
    """`None` means the alert doesn't exist. Raises `ValueError` if `RESOLVE`
    is attempted without a `reason` — the one hard rule the spec states (§4).
    """
    settings = settings or get_settings()

    if action == "RESOLVE" and not reason:
        raise ValueError("resolving an alert requires a reason")

    conn = await _connect(settings)
    try:
        exists = await conn.fetchval("SELECT 1 FROM alerts WHERE id = $1", alert_id)
        if not exists:
            return None

        if action == "ACKNOWLEDGE":
            # Only NEW -> ACKNOWLEDGED; already past NEW is a no-op, not an
            # error ("ada yang melihat" already happened).
            await conn.execute(
                "UPDATE alerts SET state = 'ACKNOWLEDGED' WHERE id = $1 AND state = 'NEW'", alert_id
            )
        elif action == "RESOLVE":
            await conn.execute(
                "UPDATE alerts SET state = 'RESOLVED', resolution_reason = $2 WHERE id = $1",
                alert_id,
                reason,
            )
        elif action == "ASSIGN_TO_ME":
            await conn.execute(
                "UPDATE alerts SET assigned_operator_id = $2 WHERE id = $1", alert_id, actor_operator_id
            )

        row = await conn.fetchrow(f"{ITEM_SQL_BASE} WHERE a.id = $1", alert_id)
    finally:
        await conn.close()

    return _row_to_item(row) if row else None
