"""Incidents (08_Dashboard/05_Incident_Management.md).

An incident groups existing Threats (message_logs rows already HIGH/MEDIUM)
into one investigation unit. MVP is operator-created/confirmed grouping only
— automatic cross-signal correlation is Post-MVP
(05_Product_Scope_and_Roadmap §4), so nothing here groups anything on its
own. "Multiple users" and "related threat categories" are derived from the
linked threats at read time, not stored — see the migration's header comment.
"""

import logging
from datetime import datetime
from typing import Any, Literal

import asyncpg

from app.core.config import Settings, get_settings
from app.services.dashboard import THREAT_LEVELS
from app.services.threats import ITEM_SQL_BASE as THREAT_ITEM_SQL_BASE
from app.services.threats import _row_to_item as threat_row_to_item

logger = logging.getLogger("app.services.incidents")

IncidentAction = Literal["ASSIGN_TO_ME", "SET_STATE", "SET_SEVERITY", "CLOSE"]

INCIDENT_SQL_BASE = """
SELECT
    i.id, i.sequence_number, i.title, i.severity::text AS severity, i.state::text AS state,
    i.assigned_operator_id, ao.full_name AS assigned_operator_name,
    i.resolution_reason, i.created_by, cb.full_name AS created_by_name,
    i.created_at, i.updated_at
FROM incidents i
LEFT JOIN operators ao ON ao.id = i.assigned_operator_id
LEFT JOIN operators cb ON cb.id = i.created_by
"""


async def _connect(settings: Settings) -> asyncpg.Connection:
    return await asyncpg.connect(settings.database_url, timeout=5)


def _code(sequence_number: int, created_at: datetime) -> str:
    return f"INC-{created_at.year}-{sequence_number:04d}"


def _incident_row_to_summary(row: asyncpg.Record, *, message_count: int, affected_user_count: int) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "code": _code(row["sequence_number"], row["created_at"]),
        "title": row["title"],
        "severity": row["severity"],
        "state": row["state"],
        "assigned_operator_id": str(row["assigned_operator_id"]) if row["assigned_operator_id"] else None,
        "assigned_operator_name": row["assigned_operator_name"],
        "resolution_reason": row["resolution_reason"],
        "created_by": str(row["created_by"]),
        "created_by_name": row["created_by_name"],
        "created_at": row["created_at"].isoformat(),
        "updated_at": row["updated_at"].isoformat(),
        "message_count": message_count,
        "affected_user_count": affected_user_count,
    }


async def list_incidents(
    limit: int = 25,
    offset: int = 0,
    *,
    severity: str | None = None,
    state: str | None = None,
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
        add("i.severity = ${}::alert_severity_enum", severity)
    if state:
        add("i.state = ${}::incident_state_enum", state)
    if date_from:
        add("i.created_at >= ${}", date_from)
    if date_to:
        add("i.created_at <= ${}", date_to)

    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows_sql = (
        f"{INCIDENT_SQL_BASE} {where_sql} ORDER BY i.created_at DESC "
        f"LIMIT ${len(params) + 1} OFFSET ${len(params) + 2}"
    )
    count_sql = f"SELECT count(*) FROM incidents i {where_sql}"

    conn = await _connect(settings)
    try:
        rows = await conn.fetch(rows_sql, *params, limit, offset)
        total = await conn.fetchval(count_sql, *params)

        items = []
        for row in rows:
            message_count = await conn.fetchval(
                "SELECT count(*) FROM incident_threats WHERE incident_id = $1", row["id"]
            )
            affected_user_count = await conn.fetchval(
                """
                SELECT count(DISTINCT m.user_hash)
                FROM incident_threats it JOIN message_logs m ON m.id = it.message_log_id
                WHERE it.incident_id = $1
                """,
                row["id"],
            )
            items.append(_incident_row_to_summary(row, message_count=message_count, affected_user_count=affected_user_count))
    finally:
        await conn.close()

    return {"total": total, "items": items}


async def get_incident(incident_id: str, settings: Settings | None = None) -> dict[str, Any] | None:
    settings = settings or get_settings()
    conn = await _connect(settings)
    try:
        row = await conn.fetchrow(f"{INCIDENT_SQL_BASE} WHERE i.id = $1", incident_id)
        if row is None:
            return None

        threat_rows = await conn.fetch(
            f"""
            {THREAT_ITEM_SQL_BASE}
            JOIN incident_threats it ON it.message_log_id = m.id
            WHERE it.incident_id = $1
            ORDER BY it.added_at
            """,
            incident_id,
        )
        note_rows = await conn.fetch(
            """
            SELECT n.id, n.note, n.created_at, n.author_operator_id, o.full_name AS author_name
            FROM incident_notes n
            JOIN operators o ON o.id = n.author_operator_id
            WHERE n.incident_id = $1
            ORDER BY n.created_at
            """,
            incident_id,
        )
    finally:
        await conn.close()

    threats = [threat_row_to_item(r) for r in threat_rows]

    return {
        **_incident_row_to_summary(row, message_count=len(threats), affected_user_count=len({t["user_hash"] for t in threats})),
        "threats": threats,
        "categories": sorted({t["threat_category"] for t in threats}),
        "notes": [
            {
                "id": str(n["id"]),
                "note": n["note"],
                "at": n["created_at"].isoformat(),
                "author_operator_id": str(n["author_operator_id"]),
                "author_name": n["author_name"],
            }
            for n in note_rows
        ],
    }


async def _validate_threats(conn: asyncpg.Connection, message_log_ids: list[str]) -> str | None:
    """Returns the first invalid id (missing, or not HIGH/MEDIUM), or `None` if all are real threats."""
    rows = await conn.fetch(
        "SELECT id::text, risk_score::text FROM message_logs WHERE id = ANY($1::uuid[])", message_log_ids
    )
    found = {row["id"]: row["risk_score"] for row in rows}
    for message_log_id in message_log_ids:
        if found.get(message_log_id) not in THREAT_LEVELS:
            return message_log_id
    return None


async def create_incident(
    title: str,
    severity: str,
    message_log_ids: list[str],
    created_by: str,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Raises `ValueError` naming the first id that isn't a real HIGH/MEDIUM threat."""
    settings = settings or get_settings()
    conn = await _connect(settings)
    try:
        invalid = await _validate_threats(conn, message_log_ids)
        if invalid is not None:
            raise ValueError(f"{invalid} is not a HIGH/MEDIUM threat")

        async with conn.transaction():
            row = await conn.fetchrow(
                """
                INSERT INTO incidents (title, severity, created_by)
                VALUES ($1, $2::alert_severity_enum, $3)
                RETURNING id
                """,
                title,
                severity,
                created_by,
            )
            incident_id = row["id"]
            for message_log_id in message_log_ids:
                await conn.execute(
                    "INSERT INTO incident_threats (incident_id, message_log_id, added_by) VALUES ($1, $2, $3)",
                    incident_id,
                    message_log_id,
                    created_by,
                )
    finally:
        await conn.close()

    result = await get_incident(str(incident_id), settings)
    assert result is not None  # just inserted, must exist
    return result


async def add_threat_to_incident(
    incident_id: str, message_log_id: str, added_by: str, settings: Settings | None = None
) -> dict[str, Any] | None:
    """Raises `ValueError` if `message_log_id` isn't a real HIGH/MEDIUM threat. `None` if the incident doesn't exist."""
    settings = settings or get_settings()
    conn = await _connect(settings)
    try:
        exists = await conn.fetchval("SELECT 1 FROM incidents WHERE id = $1", incident_id)
        if not exists:
            return None

        invalid = await _validate_threats(conn, [message_log_id])
        if invalid is not None:
            raise ValueError(f"{invalid} is not a HIGH/MEDIUM threat")

        await conn.execute(
            """
            INSERT INTO incident_threats (incident_id, message_log_id, added_by)
            VALUES ($1, $2, $3)
            ON CONFLICT (incident_id, message_log_id) DO NOTHING
            """,
            incident_id,
            message_log_id,
            added_by,
        )
    finally:
        await conn.close()

    return await get_incident(incident_id, settings)


async def remove_threat_from_incident(
    incident_id: str, message_log_id: str, settings: Settings | None = None
) -> dict[str, Any] | None:
    """`None` if the incident doesn't exist or the threat wasn't linked to it."""
    settings = settings or get_settings()
    conn = await _connect(settings)
    try:
        deleted = await conn.fetchval(
            "DELETE FROM incident_threats WHERE incident_id = $1 AND message_log_id = $2 RETURNING 1",
            incident_id,
            message_log_id,
        )
    finally:
        await conn.close()

    if not deleted:
        return None
    return await get_incident(incident_id, settings)


async def add_note(
    incident_id: str, note: str, author_operator_id: str, settings: Settings | None = None
) -> dict[str, Any] | None:
    settings = settings or get_settings()
    conn = await _connect(settings)
    try:
        exists = await conn.fetchval("SELECT 1 FROM incidents WHERE id = $1", incident_id)
        if not exists:
            return None
        await conn.execute(
            "INSERT INTO incident_notes (incident_id, author_operator_id, note) VALUES ($1, $2, $3)",
            incident_id,
            author_operator_id,
            note,
        )
    finally:
        await conn.close()

    return await get_incident(incident_id, settings)


async def apply_incident_action(
    incident_id: str,
    *,
    action: IncidentAction,
    state: str | None = None,
    severity: str | None = None,
    reason: str | None = None,
    actor_operator_id: str,
    settings: Settings | None = None,
) -> dict[str, Any] | None:
    """`None` if the incident doesn't exist. Raises `ValueError` for invalid
    action/state/severity combinations (mapped to 400 by the route).

    The returned dict carries `previous_severity` (only set for
    `SET_SEVERITY`) so the route's Audit Log call can record old+new, per
    §4's explicit requirement — same "peek at the prior value, let the route
    strip it before responding" shape Stage 2 used for Threats.
    """
    settings = settings or get_settings()

    if action == "SET_STATE" and state not in ("INVESTIGATING", "CONTAINED"):
        raise ValueError("SET_STATE only accepts INVESTIGATING or CONTAINED — use CLOSE to resolve")
    if action == "CLOSE":
        if state not in ("RESOLVED", "FALSE_POSITIVE"):
            raise ValueError("CLOSE requires state RESOLVED or FALSE_POSITIVE")
        if not reason:
            raise ValueError("closing an incident requires a reason")
    if action == "SET_SEVERITY" and not severity:
        raise ValueError("SET_SEVERITY requires a severity value")

    conn = await _connect(settings)
    try:
        current = await conn.fetchrow("SELECT state::text, severity::text FROM incidents WHERE id = $1", incident_id)
        if current is None:
            return None

        previous_severity: str | None = None

        if action == "ASSIGN_TO_ME":
            if current["state"] == "OPEN":
                await conn.execute(
                    "UPDATE incidents SET assigned_operator_id = $2, state = 'INVESTIGATING' WHERE id = $1",
                    incident_id,
                    actor_operator_id,
                )
            else:
                await conn.execute(
                    "UPDATE incidents SET assigned_operator_id = $2 WHERE id = $1", incident_id, actor_operator_id
                )
        elif action == "SET_STATE":
            await conn.execute("UPDATE incidents SET state = $2::incident_state_enum WHERE id = $1", incident_id, state)
        elif action == "SET_SEVERITY":
            previous_severity = current["severity"]
            await conn.execute(
                "UPDATE incidents SET severity = $2::alert_severity_enum WHERE id = $1", incident_id, severity
            )
        elif action == "CLOSE":
            await conn.execute(
                "UPDATE incidents SET state = $2::incident_state_enum, resolution_reason = $3 WHERE id = $1",
                incident_id,
                state,
                reason,
            )
    finally:
        await conn.close()

    result = await get_incident(incident_id, settings)
    if result is not None:
        result["previous_severity"] = previous_severity
    return result
