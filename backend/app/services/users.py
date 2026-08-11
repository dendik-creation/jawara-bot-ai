"""Users & Risk (08_Dashboard/07_Users_and_Risk.md) — the WhatsApp end-user
population, not to be confused with `operators` (the Control Panel's own
accounts). Identity is `user_hash` only, never a raw phone number.

Risk scoring is JAWARA's own v1 default: the spec states the score must be
*derived* (never a manual input) but leaves the formula undecided. Two
numbers are kept deliberately separate:

- `tier` (HIGH/MEDIUM/NONE) — purely `MAX(risk_score)` among a user's
  threats, expressed as one SQL aggregate so it stays a real, correctly
  paginated filter (same reason Stage 2 pushed the category filter into SQL).
- `score` (0-100, informational only, not filterable) — frequency + severity
  + block-history, computed in Python by `compute_risk_score` so the formula
  can be revised without touching the query layer.
"""

import logging
from typing import Any, Literal

import asyncpg

from app.core.config import Settings, get_settings
from app.pipeline.threat_categories import to_threat_category
from app.services.dashboard import THREAT_LEVELS
from app.services.threats import ITEM_SQL_BASE as THREAT_ITEM_SQL_BASE
from app.services.threats import _row_to_item as threat_row_to_item

logger = logging.getLogger("app.services.users")

UserAction = Literal["BLOCK", "UNBLOCK"]

# Shared between LIST_SQL_BASE and list_users' count query so both always
# reference `$1` (THREAT_LEVELS) identically — a count query with a WHERE
# clause numbered starting at $2 but no $1 anywhere in its own text is an
# asyncpg "server expects N arguments" error waiting to happen.
_JOINS_SQL = """
FROM user_subscriptions u
LEFT JOIN (
    SELECT
        user_hash,
        count(*) FILTER (WHERE risk_score = ANY($1::risk_level_enum[])) AS threat_count,
        min(CASE risk_score WHEN 'HIGH' THEN 1 WHEN 'MEDIUM' THEN 2 END) AS severity_rank,
        max(created_at) AS last_seen
    FROM message_logs
    GROUP BY user_hash
) t ON t.user_hash = u.user_hash
LEFT JOIN user_blocks b ON b.user_hash = u.user_hash
LEFT JOIN operators bo ON bo.id = b.actor_operator_id
"""

LIST_SQL_BASE = f"""
SELECT
    u.user_hash, u.chat_type, u.is_active, u.created_at AS subscribed_at,
    COALESCE(t.threat_count, 0) AS threat_count,
    t.severity_rank,
    t.last_seen,
    COALESCE(b.blocked, FALSE) AS blocked,
    b.reason AS block_reason,
    b.actor_operator_id AS blocked_by,
    bo.full_name AS blocked_by_name,
    b.updated_at AS blocked_at
{_JOINS_SQL}
"""


async def _connect(settings: Settings) -> asyncpg.Connection:
    return await asyncpg.connect(settings.database_url, timeout=5)


def compute_risk_score(threat_count: int, highest_severity: str | None, ever_blocked: bool) -> int:
    """JAWARA's own v1 default (spec leaves the formula undecided) — frequency
    (capped), highest severity seen, and whether a block record exists at all
    (an approximation of "sudah pernah diblokir": the table only tracks
    current state, not full history, so a user unblocked without ever truly
    having been blocked would still count here — a known, documented edge case).
    """
    score = min(threat_count, 10) * 5
    if highest_severity == "HIGH":
        score += 30
    elif highest_severity == "MEDIUM":
        score += 15
    if ever_blocked:
        score += 20
    return min(score, 100)


def _tier_from_rank(rank: int | None) -> str:
    if rank == 1:
        return "HIGH"
    if rank == 2:
        return "MEDIUM"
    return "NONE"


def _row_to_summary(row: asyncpg.Record) -> dict[str, Any]:
    rank = row["severity_rank"]
    highest_severity = "HIGH" if rank == 1 else "MEDIUM" if rank == 2 else None
    ever_blocked = row["blocked_by"] is not None

    return {
        "user_hash": row["user_hash"],
        "chat_type": row["chat_type"],
        "is_active": row["is_active"],
        "subscribed_at": row["subscribed_at"].isoformat(),
        "threat_count": row["threat_count"],
        "tier": _tier_from_rank(rank),
        "score": compute_risk_score(row["threat_count"], highest_severity, ever_blocked),
        "last_seen": row["last_seen"].isoformat() if row["last_seen"] else None,
        "blocked": row["blocked"],
        "block_reason": row["block_reason"],
        "blocked_by": str(row["blocked_by"]) if row["blocked_by"] else None,
        "blocked_by_name": row["blocked_by_name"],
        "blocked_at": row["blocked_at"].isoformat() if row["blocked_at"] else None,
    }


async def list_users(
    limit: int = 25,
    offset: int = 0,
    *,
    tier: str | None = None,
    chat_type: str | None = None,
    is_active: bool | None = None,
    blocked: bool | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    settings = settings or get_settings()

    clauses: list[str] = []
    params: list[Any] = [list(THREAT_LEVELS)]

    def add(clause: str, value: Any) -> None:
        params.append(value)
        clauses.append(clause.format(len(params)))

    if tier == "HIGH":
        clauses.append("t.severity_rank = 1")
    elif tier == "MEDIUM":
        clauses.append("t.severity_rank = 2")
    elif tier == "NONE":
        clauses.append("t.severity_rank IS NULL")

    if chat_type:
        add("u.chat_type = ${}", chat_type)
    if is_active is not None:
        add("u.is_active = ${}", is_active)
    if blocked is not None:
        add("COALESCE(b.blocked, FALSE) = ${}", blocked)

    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows_sql = (
        f"{LIST_SQL_BASE} {where_sql} ORDER BY u.created_at DESC "
        f"LIMIT ${len(params) + 1} OFFSET ${len(params) + 2}"
    )
    count_sql = f"SELECT count(*) {_JOINS_SQL} {where_sql}"

    conn = await _connect(settings)
    try:
        rows = await conn.fetch(rows_sql, *params, limit, offset)
        total = await conn.fetchval(count_sql, *params)
    finally:
        await conn.close()

    return {"total": total, "items": [_row_to_summary(row) for row in rows]}


async def get_user(user_hash: str, settings: Settings | None = None) -> dict[str, Any] | None:
    settings = settings or get_settings()
    conn = await _connect(settings)
    try:
        row = await conn.fetchrow(f"{LIST_SQL_BASE} WHERE u.user_hash = $2", list(THREAT_LEVELS), user_hash)
        if row is None:
            return None

        dominant_row = await conn.fetchrow(
            """
            SELECT detected_intent, count(*) AS c
            FROM message_logs
            WHERE user_hash = $2 AND risk_score = ANY($1::risk_level_enum[])
            GROUP BY detected_intent
            ORDER BY c DESC
            LIMIT 1
            """,
            list(THREAT_LEVELS),
            user_hash,
        )
        threat_rows = await conn.fetch(
            f"{THREAT_ITEM_SQL_BASE} WHERE m.user_hash = $2 AND m.risk_score = ANY($1::risk_level_enum[]) "
            f"ORDER BY m.created_at DESC LIMIT 10",
            list(THREAT_LEVELS),
            user_hash,
        )
    finally:
        await conn.close()

    summary = _row_to_summary(row)
    summary["dominant_category"] = (
        to_threat_category(dominant_row["detected_intent"]).value if dominant_row else None
    )
    summary["recent_threats"] = [threat_row_to_item(r) for r in threat_rows]
    return summary


async def apply_user_action(
    user_hash: str,
    *,
    action: UserAction,
    reason: str,
    actor_operator_id: str,
    settings: Settings | None = None,
) -> dict[str, Any] | None:
    """`None` if `user_hash` has no `user_subscriptions` row. The returned
    dict carries `previous_blocked` (the prior `blocked` value, or `None` if
    this is the first action ever taken) for the route's Audit Log call.
    """
    settings = settings or get_settings()
    conn = await _connect(settings)
    try:
        exists = await conn.fetchval("SELECT 1 FROM user_subscriptions WHERE user_hash = $1", user_hash)
        if not exists:
            return None

        previous_blocked = await conn.fetchval("SELECT blocked FROM user_blocks WHERE user_hash = $1", user_hash)

        await conn.execute(
            """
            INSERT INTO user_blocks (user_hash, blocked, reason, actor_operator_id)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (user_hash) DO UPDATE
            SET blocked = EXCLUDED.blocked, reason = EXCLUDED.reason, actor_operator_id = EXCLUDED.actor_operator_id
            """,
            user_hash,
            action == "BLOCK",
            reason,
            actor_operator_id,
        )
    finally:
        await conn.close()

    result = await get_user(user_hash, settings)
    if result is not None:
        result["previous_blocked"] = previous_blocked
    return result
