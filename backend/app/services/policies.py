"""Security Policies (09_Security/02_Security_Policies.md).

IF <condition> THEN <action> response configuration, kept deliberately
separate from Detection Rules (§5's own framing: rules answer "is this
suspicious?", policies answer "what do we do about it?"). Policies are
visible/manageable only this stage — evaluating them against live messages
needs `app/pipeline/orchestrator.py`, a separate, higher-risk follow-up.
Nothing here writes to the live pipeline.
"""

import json
import logging
from typing import Any, Literal

import asyncpg

from app.core.config import Settings, get_settings
from app.pipeline.threat_categories import ThreatCategory

logger = logging.getLogger("app.services.policies")

PolicyOperation = Literal["UPDATE", "ACTIVATE", "DISABLE", "ARCHIVE"]

_STATUS_TRANSITIONS: dict[str, set[str]] = {
    "ACTIVATE": {"DRAFT", "DISABLED"},
    "DISABLE": {"ACTIVE"},
    "ARCHIVE": {"DRAFT", "ACTIVE", "DISABLED"},
}

_THREAT_CATEGORY_VALUES = {c.value for c in ThreatCategory}

ITEM_SQL_BASE = """
SELECT
    p.id, p.name, p.scope::text AS scope, p.condition, p.action::text AS action,
    p.priority, p.status::text AS status, p.created_by, o.full_name AS created_by_name,
    p.created_at, p.updated_at
FROM policies p
JOIN operators o ON o.id = p.created_by
"""


async def _connect(settings: Settings) -> asyncpg.Connection:
    return await asyncpg.connect(settings.database_url, timeout=5)


def _row_to_item(row: asyncpg.Record) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "name": row["name"],
        "scope": row["scope"],
        "condition": json.loads(row["condition"]) if isinstance(row["condition"], str) else row["condition"],
        "action": row["action"],
        "priority": row["priority"],
        "status": row["status"],
        "created_by": str(row["created_by"]),
        "created_by_name": row["created_by_name"],
        "created_at": row["created_at"].isoformat(),
        "updated_at": row["updated_at"].isoformat(),
    }


async def _validate_policy_condition(scope: str, condition: dict[str, Any], conn: asyncpg.Connection) -> None:
    if scope == "DEFAULT":
        if condition != {}:
            raise ValueError("DEFAULT policy condition must be empty")
    elif scope == "CATEGORY_THRESHOLD":
        if "threat_category" not in condition:
            raise ValueError("CATEGORY_THRESHOLD condition requires 'threat_category'")
        if "threshold" not in condition:
            raise ValueError("CATEGORY_THRESHOLD condition requires 'threshold'")
        if condition["threat_category"] not in _THREAT_CATEGORY_VALUES:
            raise ValueError(f"'threat_category' must be one of {sorted(_THREAT_CATEGORY_VALUES)}")
        threshold = condition["threshold"]
        if not isinstance(threshold, int) or not (0 <= threshold <= 100):
            raise ValueError("'threshold' must be an integer between 0 and 100")
    elif scope == "USER_SPECIFIC":
        if "user_hash" not in condition:
            raise ValueError("USER_SPECIFIC condition requires 'user_hash'")
        user_hash = condition["user_hash"]
        if not isinstance(user_hash, str) or not user_hash:
            raise ValueError("'user_hash' must be a non-empty string")
        exists = await conn.fetchval("SELECT 1 FROM user_subscriptions WHERE user_hash = $1", user_hash)
        if not exists:
            raise ValueError(f"no user found with user_hash '{user_hash}'")


async def list_policies(
    limit: int = 25,
    offset: int = 0,
    *,
    scope: str | None = None,
    status: str | None = None,
    action: str | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    settings = settings or get_settings()

    clauses: list[str] = []
    params: list[Any] = []

    def add(clause: str, value: Any) -> None:
        params.append(value)
        clauses.append(clause.format(len(params)))

    if scope:
        add("p.scope = ${}::policy_scope_enum", scope)
    if status:
        add("p.status = ${}::policy_status_enum", status)
    if action:
        add("p.action = ${}::policy_action_enum", action)

    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows_sql = (
        f"{ITEM_SQL_BASE} {where_sql} ORDER BY p.priority ASC, p.created_at DESC "
        f"LIMIT ${len(params) + 1} OFFSET ${len(params) + 2}"
    )
    count_sql = f"SELECT count(*) FROM policies p {where_sql}"

    conn = await _connect(settings)
    try:
        rows = await conn.fetch(rows_sql, *params, limit, offset)
        total = await conn.fetchval(count_sql, *params)
    finally:
        await conn.close()

    return {"total": total, "items": [_row_to_item(row) for row in rows]}


async def create_policy(
    name: str,
    scope: str,
    condition: dict[str, Any],
    action: str,
    priority: int,
    created_by: str,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Raises `ValueError` if `condition` doesn't match `scope`'s required
    shape. Always inserts `status='DRAFT'` — an operator must explicitly
    promote a new policy to ACTIVE.
    """
    settings = settings or get_settings()

    conn = await _connect(settings)
    try:
        await _validate_policy_condition(scope, condition, conn)
        inserted = await conn.fetchrow(
            """
            INSERT INTO policies (name, scope, condition, action, priority, created_by)
            VALUES ($1, $2::policy_scope_enum, $3::jsonb, $4::policy_action_enum, $5, $6)
            RETURNING id
            """,
            name,
            scope,
            json.dumps(condition),
            action,
            priority,
            created_by,
        )
        row = await conn.fetchrow(f"{ITEM_SQL_BASE} WHERE p.id = $1", inserted["id"])
    finally:
        await conn.close()

    return _row_to_item(row)


async def apply_policy_action(
    policy_id: str,
    *,
    operation: PolicyOperation,
    name: str | None = None,
    condition: dict[str, Any] | None = None,
    action: str | None = None,
    priority: int | None = None,
    settings: Settings | None = None,
) -> dict[str, Any] | None:
    """`None` if the policy doesn't exist. Raises `ValueError` for:
    - `UPDATE` with no fields, or on an `ARCHIVED` policy (terminal), or a
      `condition` that fails `_validate_policy_condition` against the row's
      existing `scope` (immutable — not accepted as a payload field).
    - an invalid status transition.
    - `ACTIVATE` on a `DEFAULT`-scoped policy while another `DEFAULT` policy
      is already `ACTIVE` — a fallback must be singular.

    The returned dict carries `previous_status` (only set for
    `ACTIVATE`/`DISABLE`/`ARCHIVE`) so the route's Audit Log call can record
    old+new, same shape Detection Rules used.
    """
    settings = settings or get_settings()

    if operation == "UPDATE" and name is None and condition is None and action is None and priority is None:
        raise ValueError("UPDATE requires at least one of name/condition/action/priority")

    conn = await _connect(settings)
    try:
        current = await conn.fetchrow("SELECT scope::text, status::text FROM policies WHERE id = $1", policy_id)
        if current is None:
            return None

        previous_status: str | None = None

        if operation == "UPDATE":
            if current["status"] == "ARCHIVED":
                raise ValueError("an ARCHIVED policy cannot be edited")
            if condition is not None:
                await _validate_policy_condition(current["scope"], condition, conn)

            sets: list[str] = []
            params: list[Any] = []
            if name is not None:
                params.append(name)
                sets.append(f"name = ${len(params)}")
            if condition is not None:
                params.append(json.dumps(condition))
                sets.append(f"condition = ${len(params)}::jsonb")
            if action is not None:
                params.append(action)
                sets.append(f"action = ${len(params)}::policy_action_enum")
            if priority is not None:
                params.append(priority)
                sets.append(f"priority = ${len(params)}")
            params.append(policy_id)
            await conn.execute(f"UPDATE policies SET {', '.join(sets)} WHERE id = ${len(params)}", *params)
        else:
            allowed_from = _STATUS_TRANSITIONS[operation]
            if current["status"] not in allowed_from:
                raise ValueError(f"cannot {operation} a policy in status {current['status']}")
            if operation == "ACTIVATE" and current["scope"] == "DEFAULT":
                other_active_default = await conn.fetchval(
                    "SELECT 1 FROM policies WHERE scope = 'DEFAULT' AND status = 'ACTIVE' AND id != $1",
                    policy_id,
                )
                if other_active_default:
                    raise ValueError("another DEFAULT policy is already ACTIVE")
            previous_status = current["status"]
            new_status = {"ACTIVATE": "ACTIVE", "DISABLE": "DISABLED", "ARCHIVE": "ARCHIVED"}[operation]
            await conn.execute(
                "UPDATE policies SET status = $2::policy_status_enum WHERE id = $1",
                policy_id,
                new_status,
            )

        row = await conn.fetchrow(f"{ITEM_SQL_BASE} WHERE p.id = $1", policy_id)
    finally:
        await conn.close()

    result = _row_to_item(row)
    result["previous_status"] = previous_status
    return result
