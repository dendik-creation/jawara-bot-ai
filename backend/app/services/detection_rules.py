"""Detection Rules (09_Security/03_Detection_Rules.md).

Deterministic rule CRUD, kept deliberately separate from ML classification
(§2's own framing: rules and ML "saling melengkapi", neither replaces the
other). Rules are visible/manageable only this stage — matching a rule
against a live message, trigger counts, and false-positive rates (§4) all
need `app/pipeline/orchestrator.py` to evaluate rules, which is a separate,
higher-risk follow-up. Nothing here writes to the live pipeline.
"""

import json
import logging
from typing import Any, Literal

import asyncpg

from app.core.config import Settings, get_settings

logger = logging.getLogger("app.services.detection_rules")

RuleAction = Literal["UPDATE", "ACTIVATE", "DISABLE", "ARCHIVE"]

# What `condition` must contain for each rule_type — checked by
# `_validate_condition`, not by the wire schema, since the required shape
# depends on a runtime value (`rule_type`), same reasoning Alerts/Incidents
# push their reason-required checks into the service layer.
CONDITION_REQUIRED_KEYS: dict[str, list[str]] = {
    "KEYWORD": ["values"],
    "DOMAIN": ["values"],
    "URL": ["values"],
    "ALLOWLIST": ["values"],
    "BLOCKLIST": ["values"],
    "RISK_THRESHOLD": ["threshold"],
    "PATTERN": ["components"],
    "REPEATED_OFFENDER": ["occurrences", "window_hours"],
    "RATE_LIMIT": ["max_messages", "window_minutes"],
}

_STATUS_TRANSITIONS: dict[str, set[str]] = {
    "ACTIVATE": {"DRAFT", "DISABLED"},
    "DISABLE": {"ACTIVE"},
    "ARCHIVE": {"DRAFT", "ACTIVE", "DISABLED"},
}

ITEM_SQL_BASE = """
SELECT
    r.id, r.name, r.rule_type::text AS rule_type, r.condition, r.severity::text AS severity,
    r.status::text AS status, r.created_by, o.full_name AS created_by_name,
    r.created_at, r.updated_at
FROM detection_rules r
JOIN operators o ON o.id = r.created_by
"""


async def _connect(settings: Settings) -> asyncpg.Connection:
    return await asyncpg.connect(settings.database_url, timeout=5)


def _row_to_item(row: asyncpg.Record) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "name": row["name"],
        "rule_type": row["rule_type"],
        "condition": json.loads(row["condition"]) if isinstance(row["condition"], str) else row["condition"],
        "severity": row["severity"],
        "status": row["status"],
        "created_by": str(row["created_by"]),
        "created_by_name": row["created_by_name"],
        "created_at": row["created_at"].isoformat(),
        "updated_at": row["updated_at"].isoformat(),
    }


def _validate_condition(rule_type: str, condition: dict[str, Any]) -> None:
    required = CONDITION_REQUIRED_KEYS.get(rule_type, [])
    for key in required:
        if key not in condition:
            raise ValueError(f"{rule_type} condition requires '{key}'")

    if rule_type in ("KEYWORD", "DOMAIN", "URL", "ALLOWLIST", "BLOCKLIST"):
        values = condition["values"]
        if not isinstance(values, list) or not values:
            raise ValueError("'values' must be a non-empty list")
    elif rule_type == "RISK_THRESHOLD":
        threshold = condition["threshold"]
        if not isinstance(threshold, int) or not (0 <= threshold <= 100):
            raise ValueError("'threshold' must be an integer between 0 and 100")
    elif rule_type == "PATTERN":
        components = condition["components"]
        if not isinstance(components, list) or not components:
            raise ValueError("'components' must be a non-empty list")
    elif rule_type == "REPEATED_OFFENDER":
        if not isinstance(condition["occurrences"], int) or condition["occurrences"] < 2:
            raise ValueError("'occurrences' must be an integer >= 2")
        if not isinstance(condition["window_hours"], int) or condition["window_hours"] < 1:
            raise ValueError("'window_hours' must be an integer >= 1")
    elif rule_type == "RATE_LIMIT":
        if not isinstance(condition["max_messages"], int) or condition["max_messages"] < 1:
            raise ValueError("'max_messages' must be an integer >= 1")
        if not isinstance(condition["window_minutes"], int) or condition["window_minutes"] < 1:
            raise ValueError("'window_minutes' must be an integer >= 1")


async def list_detection_rules(
    limit: int = 25,
    offset: int = 0,
    *,
    rule_type: str | None = None,
    status: str | None = None,
    severity: str | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    settings = settings or get_settings()

    clauses: list[str] = []
    params: list[Any] = []

    def add(clause: str, value: Any) -> None:
        params.append(value)
        clauses.append(clause.format(len(params)))

    if rule_type:
        add("r.rule_type = ${}::detection_rule_type_enum", rule_type)
    if status:
        add("r.status = ${}::detection_rule_status_enum", status)
    if severity:
        add("r.severity = ${}::risk_level_enum", severity)

    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows_sql = (
        f"{ITEM_SQL_BASE} {where_sql} ORDER BY r.created_at DESC "
        f"LIMIT ${len(params) + 1} OFFSET ${len(params) + 2}"
    )
    count_sql = f"SELECT count(*) FROM detection_rules r {where_sql}"

    conn = await _connect(settings)
    try:
        rows = await conn.fetch(rows_sql, *params, limit, offset)
        total = await conn.fetchval(count_sql, *params)
    finally:
        await conn.close()

    return {"total": total, "items": [_row_to_item(row) for row in rows]}


async def create_detection_rule(
    name: str,
    rule_type: str,
    condition: dict[str, Any],
    severity: str,
    created_by: str,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Raises `ValueError` if `condition` doesn't match `rule_type`'s required
    shape. Always inserts `status='DRAFT'` — the spec's own lifecycle order,
    an operator must explicitly promote a new rule to ACTIVE.
    """
    _validate_condition(rule_type, condition)
    settings = settings or get_settings()

    conn = await _connect(settings)
    try:
        inserted = await conn.fetchrow(
            """
            INSERT INTO detection_rules (name, rule_type, condition, severity, created_by)
            VALUES ($1, $2::detection_rule_type_enum, $3::jsonb, $4::risk_level_enum, $5)
            RETURNING id
            """,
            name,
            rule_type,
            json.dumps(condition),
            severity,
            created_by,
        )
        row = await conn.fetchrow(f"{ITEM_SQL_BASE} WHERE r.id = $1", inserted["id"])
    finally:
        await conn.close()

    return _row_to_item(row)


async def apply_rule_action(
    rule_id: str,
    *,
    action: RuleAction,
    name: str | None = None,
    condition: dict[str, Any] | None = None,
    severity: str | None = None,
    settings: Settings | None = None,
) -> dict[str, Any] | None:
    """`None` if the rule doesn't exist. Raises `ValueError` for:
    - `UPDATE` with no fields, or on an `ARCHIVED` rule (terminal), or a
      `condition` that fails `_validate_condition` against the row's
      existing `rule_type` (immutable — not accepted as a payload field).
    - an invalid status transition (mapped to 400 by the route).

    The returned dict carries `previous_status` (only set for
    `ACTIVATE`/`DISABLE`/`ARCHIVE`) so the route's Audit Log call can record
    old+new, same "peek at the prior value" shape Incidents used for
    `SET_SEVERITY`.
    """
    settings = settings or get_settings()

    if action == "UPDATE" and name is None and condition is None and severity is None:
        raise ValueError("UPDATE requires at least one of name/condition/severity")

    conn = await _connect(settings)
    try:
        current = await conn.fetchrow(
            "SELECT rule_type::text, status::text FROM detection_rules WHERE id = $1", rule_id
        )
        if current is None:
            return None

        previous_status: str | None = None

        if action == "UPDATE":
            if current["status"] == "ARCHIVED":
                raise ValueError("an ARCHIVED rule cannot be edited")
            if condition is not None:
                _validate_condition(current["rule_type"], condition)

            sets: list[str] = []
            params: list[Any] = []
            if name is not None:
                params.append(name)
                sets.append(f"name = ${len(params)}")
            if condition is not None:
                params.append(json.dumps(condition))
                sets.append(f"condition = ${len(params)}::jsonb")
            if severity is not None:
                params.append(severity)
                sets.append(f"severity = ${len(params)}::risk_level_enum")
            params.append(rule_id)
            await conn.execute(f"UPDATE detection_rules SET {', '.join(sets)} WHERE id = ${len(params)}", *params)
        else:
            allowed_from = _STATUS_TRANSITIONS[action]
            if current["status"] not in allowed_from:
                raise ValueError(f"cannot {action} a rule in status {current['status']}")
            previous_status = current["status"]
            new_status = {"ACTIVATE": "ACTIVE", "DISABLE": "DISABLED", "ARCHIVE": "ARCHIVED"}[action]
            await conn.execute(
                "UPDATE detection_rules SET status = $2::detection_rule_status_enum WHERE id = $1",
                rule_id,
                new_status,
            )

        row = await conn.fetchrow(f"{ITEM_SQL_BASE} WHERE r.id = $1", rule_id)
    finally:
        await conn.close()

    result = _row_to_item(row)
    result["previous_status"] = previous_status
    return result
