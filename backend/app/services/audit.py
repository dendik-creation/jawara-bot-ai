"""Operator action audit trail (09_Security/05_Audit_Logs.md).

Distinct from `message_logs` (a *message processing* trail keyed by anonymous
`user_hash`): this module records what a signed-in *operator* did — actor,
action, target, timestamp, result, metadata. Every mutating action added in a
later stage (threat actions, policy edits, blocklist changes, ...) is expected
to call `record_audit` rather than invent its own write path.

`record_audit` swallows its own failures: a failed audit write must never be
the reason a login, logout, or password change itself fails.
"""

import json
import logging
from datetime import datetime
from typing import Any

import asyncpg

from app.core.config import Settings, get_settings

logger = logging.getLogger("app.services.audit")

INSERT_SQL = """
INSERT INTO audit_log (actor_operator_id, action, target_type, target_id, result, metadata, ip_address, user_agent)
VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7, $8)
"""


async def _connect(settings: Settings) -> asyncpg.Connection:
    return await asyncpg.connect(settings.database_url, timeout=5)


async def record_audit(
    *,
    actor_operator_id: str | None,
    action: str,
    target_type: str,
    target_id: str | None = None,
    result: str,
    metadata: dict[str, Any] | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    settings: Settings | None = None,
) -> None:
    settings = settings or get_settings()
    try:
        conn = await _connect(settings)
    except Exception:  # noqa: BLE001
        logger.error("audit log write failed: cannot connect", exc_info=True)
        return

    try:
        await conn.execute(
            INSERT_SQL,
            actor_operator_id,
            action,
            target_type,
            target_id,
            result,
            json.dumps(metadata or {}),
            ip_address,
            user_agent,
        )
    except Exception:  # noqa: BLE001
        logger.error("audit log write failed", extra={"action": action}, exc_info=True)
    finally:
        await conn.close()


async def list_audit_log(
    limit: int = 25,
    offset: int = 0,
    *,
    action: str | None = None,
    actor_operator_id: str | None = None,
    target_type: str | None = None,
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

    if action:
        add("a.action = ${}", action)
    if actor_operator_id:
        add("a.actor_operator_id = ${}", actor_operator_id)
    if target_type:
        add("a.target_type = ${}", target_type)
    if date_from:
        add("a.created_at >= ${}", date_from)
    if date_to:
        add("a.created_at <= ${}", date_to)

    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""

    rows_sql = f"""
        SELECT a.id, a.created_at, a.actor_operator_id, o.full_name AS actor_name,
               a.action, a.target_type, a.target_id, a.result, a.metadata, a.ip_address
        FROM audit_log a
        LEFT JOIN operators o ON o.id = a.actor_operator_id
        {where_sql}
        ORDER BY a.created_at DESC
        LIMIT ${len(params) + 1} OFFSET ${len(params) + 2}
    """
    count_sql = f"SELECT count(*) FROM audit_log a {where_sql}"

    conn = await _connect(settings)
    try:
        rows = await conn.fetch(rows_sql, *params, limit, offset)
        total = await conn.fetchval(count_sql, *params)
    finally:
        await conn.close()

    return {
        "total": total,
        "items": [
            {
                "id": str(row["id"]),
                "at": row["created_at"].isoformat(),
                "actor_operator_id": str(row["actor_operator_id"]) if row["actor_operator_id"] is not None else None,
                "actor_name": row["actor_name"],
                "action": row["action"],
                "target_type": row["target_type"],
                "target_id": row["target_id"],
                "result": row["result"],
                "metadata": json.loads(row["metadata"]) if isinstance(row["metadata"], str) else row["metadata"],
                "ip_address": str(row["ip_address"]) if row["ip_address"] is not None else None,
            }
            for row in rows
        ],
    }
