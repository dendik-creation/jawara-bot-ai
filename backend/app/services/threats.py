"""Threats (08_Dashboard/03_Threat_Monitoring.md).

A threat is not a new fact — it is any `message_logs` row with
`risk_score IN ('HIGH','MEDIUM')`, viewed through an operator's triage lens.
`threat_cases` (migration 004) holds only the part that doesn't already exist
anywhere: the operator's resolving action. `state` is therefore derived, not
stored — `RESOLVED` when a `threat_cases` row exists, `ANALYZED` otherwise.
`DETECTED` and `ACTIONED` describe pipeline/policy stages this system cannot
produce yet (see the migration's header comment); `list_threats` returns an
honest empty result for them instead of guessing.
"""

import logging
from datetime import datetime
from typing import Any, Literal

import asyncpg

from app.core.config import Settings, get_settings
from app.pipeline.categories import Category
from app.pipeline.threat_categories import ThreatCategory, to_threat_category
from app.services.dashboard import THREAT_LEVELS

logger = logging.getLogger("app.services.threats")

State = Literal["DETECTED", "ANALYZED", "ACTIONED", "RESOLVED"]

ITEM_SQL_BASE = """
SELECT
    m.id AS message_log_id,
    m.created_at,
    m.waha_session_id,
    m.chat_type,
    m.user_hash,
    m.detected_intent::text AS detected_intent,
    m.risk_score::text AS risk_score,
    m.similarity_score,
    t.action::text AS action,
    t.notes,
    t.actor_operator_id,
    o.full_name AS actor_name,
    t.updated_at AS action_at
FROM message_logs m
LEFT JOIN threat_cases t ON t.message_log_id = m.id
LEFT JOIN operators o ON o.id = t.actor_operator_id
"""


def categories_for_threat(threat_category: ThreatCategory) -> list[str]:
    """Pipeline `category_enum` values that map onto one Control Panel threat
    category — lets a category filter run as a real SQL `WHERE`, not a
    post-fetch filter that would break pagination.
    """
    return [category.value for category in Category if to_threat_category(category) == threat_category]


async def _connect(settings: Settings) -> asyncpg.Connection:
    return await asyncpg.connect(settings.database_url, timeout=5)


def _row_to_item(row: asyncpg.Record) -> dict[str, Any]:
    has_action = row["action"] is not None
    return {
        "message_log_id": str(row["message_log_id"]),
        "at": row["created_at"].isoformat(),
        "session": row["waha_session_id"],
        "chat_type": row["chat_type"],
        "user_hash": row["user_hash"],
        "intent": row["detected_intent"],
        "threat_category": to_threat_category(row["detected_intent"]).value,
        "risk": row["risk_score"],
        "similarity_score": row["similarity_score"],
        "state": "RESOLVED" if has_action else "ANALYZED",
        "action": row["action"],
        "action_by": row["actor_name"],
        "action_at": row["action_at"].isoformat() if row["action_at"] else None,
        "notes": row["notes"],
    }


async def list_threats(
    limit: int = 25,
    offset: int = 0,
    *,
    severity: str | None = None,
    category: ThreatCategory | None = None,
    state: State | None = None,
    action: str | None = None,
    user_hash: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    settings = settings or get_settings()

    # DETECTED/ACTIONED cannot exist yet (see module docstring) — an honest
    # empty page beats a query that would silently return the wrong thing.
    if state in ("DETECTED", "ACTIONED"):
        return {"total": 0, "items": []}

    clauses: list[str] = []
    params: list[Any] = []

    def add(clause: str, value: Any) -> None:
        params.append(value)
        clauses.append(clause.format(len(params)))

    add("m.risk_score = ANY(${}::risk_level_enum[])", [severity] if severity else list(THREAT_LEVELS))

    if category is not None:
        matching = categories_for_threat(category)
        if not matching:
            # No pipeline Category maps onto this threat category today
            # (see threat_categories.py) — genuinely zero results, not a bug.
            return {"total": 0, "items": []}
        add("m.detected_intent = ANY(${}::category_enum[])", matching)

    if state == "RESOLVED":
        clauses.append("t.message_log_id IS NOT NULL")
    elif state == "ANALYZED":
        clauses.append("t.message_log_id IS NULL")

    if action:
        add("t.action = ${}::threat_action_enum", action)
    if user_hash:
        add("m.user_hash = ${}", user_hash)
    if date_from:
        add("m.created_at >= ${}", date_from)
    if date_to:
        add("m.created_at <= ${}", date_to)

    where_sql = f"WHERE {' AND '.join(clauses)}"
    rows_sql = f"{ITEM_SQL_BASE} {where_sql} ORDER BY m.created_at DESC LIMIT ${len(params) + 1} OFFSET ${len(params) + 2}"
    count_sql = f"SELECT count(*) FROM message_logs m LEFT JOIN threat_cases t ON t.message_log_id = m.id {where_sql}"

    conn = await _connect(settings)
    try:
        rows = await conn.fetch(rows_sql, *params, limit, offset)
        total = await conn.fetchval(count_sql, *params)
    finally:
        await conn.close()

    return {"total": total, "items": [_row_to_item(row) for row in rows]}


async def get_threat(message_log_id: str, settings: Settings | None = None) -> dict[str, Any] | None:
    settings = settings or get_settings()
    conn = await _connect(settings)
    try:
        row = await conn.fetchrow(f"{ITEM_SQL_BASE} WHERE m.id = $1", message_log_id)
    finally:
        await conn.close()
    return _row_to_item(row) if row else None


async def action_on_threat(
    message_log_id: str,
    *,
    action: str,
    notes: str | None,
    actor_operator_id: str,
    settings: Settings | None = None,
) -> dict[str, Any] | None:
    """Resolve a threat with an operator action. Re-actioning (correcting a
    prior call) is allowed — each call still gets its own Audit Log entry
    (written by the route), so the history survives even though this table
    only keeps the current action.

    Returns `None` if `message_log_id` doesn't exist or isn't HIGH/MEDIUM —
    there is nothing to action, whether or not the id is real.
    """
    settings = settings or get_settings()
    conn = await _connect(settings)
    try:
        risk = await conn.fetchval(
            "SELECT risk_score::text FROM message_logs WHERE id = $1", message_log_id
        )
        if risk not in THREAT_LEVELS:
            return None

        previous_action = await conn.fetchval(
            "SELECT action::text FROM threat_cases WHERE message_log_id = $1", message_log_id
        )

        await conn.execute(
            """
            INSERT INTO threat_cases (message_log_id, action, notes, actor_operator_id)
            VALUES ($1, $2::threat_action_enum, $3, $4)
            ON CONFLICT (message_log_id) DO UPDATE
            SET action = EXCLUDED.action, notes = EXCLUDED.notes, actor_operator_id = EXCLUDED.actor_operator_id
            """,
            message_log_id,
            action,
            notes,
            actor_operator_id,
        )
        row = await conn.fetchrow(f"{ITEM_SQL_BASE} WHERE m.id = $1", message_log_id)
    finally:
        await conn.close()

    item = _row_to_item(row) if row else None
    if item is not None:
        item["previous_action"] = previous_action
    return item
