"""Aggregation queries behind the Command Center ([[Implement Command Center Dashboard]]).

Aggregation happens here, in the gateway, straight from PostgreSQL. A dedicated
Analytics Service is **Deferred** (05_Product_Scope_and_Roadmap §6) and must not
reappear as a component.

Two rules shape every query in this module:

**Never return message content.** `extracted_text` is not selected anywhere. The
Control Panel shows metadata and classifications; reading message bodies is a
separate screen with its own privacy policy (04_Message_Inspection).

**Never invent a number.** Threats, incidents and alerts have no tables yet.
Those blocks return `available: false` with a reason instead of a zero, because
a zero is indistinguishable from "quiet day" and would be read as one.
"""

import logging
from typing import Any

import asyncpg

from app.core.config import Settings, get_settings
from app.pipeline.threat_categories import to_threat_category

logger = logging.getLogger("app.services.dashboard")

# Risk levels that count as a detected threat. UNKNOWN is excluded: it means the
# checks could not run, not that something was found.
THREAT_LEVELS = ("HIGH", "MEDIUM")

SUMMARY_SQL = """
SELECT
    count(*)                                            AS messages_processed,
    count(*) FILTER (WHERE risk_score = ANY($2::risk_level_enum[])) AS threats_detected,
    count(*) FILTER (WHERE risk_score = 'HIGH')         AS critical_threats,
    count(DISTINCT user_hash)                           AS active_users,
    avg(response_latency_ms) FILTER (WHERE response_latency_ms IS NOT NULL) AS avg_latency_ms
FROM message_logs
WHERE created_at >= now() - make_interval(hours => $1)
"""

SEVERITY_SQL = """
SELECT risk_score::text AS risk, count(*) AS total
FROM message_logs
WHERE created_at >= now() - make_interval(hours => $1)
GROUP BY risk_score
"""

INTENT_SQL = """
SELECT coalesce(detected_intent::text, 'UNCLASSIFIED') AS intent, count(*) AS total
FROM message_logs
WHERE created_at >= now() - make_interval(hours => $1)
GROUP BY detected_intent
"""

ACTIVITY_SQL = """
SELECT
    id,
    created_at,
    waha_session_id,
    chat_type,
    input_type::text  AS input_type,
    detected_intent::text AS detected_intent,
    risk_score::text  AS risk_score,
    similarity_score,
    response_latency_ms
FROM message_logs
ORDER BY created_at DESC
LIMIT $1
"""

RECENT_THREATS_SQL = """
SELECT
    id,
    created_at,
    waha_session_id,
    chat_type,
    detected_intent::text AS detected_intent,
    risk_score::text      AS risk_score
FROM message_logs
WHERE risk_score = ANY($1::risk_level_enum[])
ORDER BY created_at DESC
LIMIT $2
"""

MESSAGES_SQL = """
SELECT
    id,
    created_at,
    waha_session_id,
    chat_type,
    input_type::text AS input_type,
    extracted_text,
    detected_intent::text AS detected_intent,
    risk_score::text AS risk_score,
    similarity_score,
    response_latency_ms
FROM message_logs
ORDER BY created_at DESC
LIMIT $1 OFFSET $2
"""

MESSAGES_COUNT_SQL = "SELECT count(*) FROM message_logs"


async def _connect(settings: Settings) -> asyncpg.Connection:
    return await asyncpg.connect(settings.database_url, timeout=5)


async def summary(settings: Settings | None = None) -> dict[str, Any]:
    """Command Center headline metrics for the configured window."""
    settings = settings or get_settings()
    hours = settings.dashboard_window_hours

    conn = await _connect(settings)
    try:
        row = await conn.fetchrow(SUMMARY_SQL, hours, list(THREAT_LEVELS))
        severity = await conn.fetch(SEVERITY_SQL, hours)
        intents = await conn.fetch(INTENT_SQL, hours)
    finally:
        await conn.close()

    return {
        "window_hours": hours,
        "messages_processed": row["messages_processed"],
        "threats_detected": row["threats_detected"],
        "critical_threats": row["critical_threats"],
        "active_users": row["active_users"],
        "avg_response_latency_ms": (
            int(row["avg_latency_ms"]) if row["avg_latency_ms"] is not None else None
        ),
        "severity_breakdown": {record["risk"]: record["total"] for record in severity},
        "intent_breakdown": {record["intent"]: record["total"] for record in intents},
    }


async def recent_activity(limit: int | None = None, settings: Settings | None = None) -> list[dict[str, Any]]:
    """Live Activity feed rows, newest first.

    Event naming follows 08_Dashboard/02_Command_Center.md §3: a processed
    message is `MESSAGE_ANALYZED`, one that came out at HIGH/MEDIUM risk is
    `THREAT_DETECTED`. `ACTION_APPLIED`, `INCIDENT_UPDATED` and `ALERT_RAISED`
    need the policy and incident engines, which do not exist yet.
    """
    settings = settings or get_settings()
    conn = await _connect(settings)
    try:
        rows = await conn.fetch(ACTIVITY_SQL, limit or settings.dashboard_activity_limit)
    finally:
        await conn.close()

    return [
        {
            "id": str(row["id"]),
            "at": row["created_at"].isoformat(),
            "event": "THREAT_DETECTED" if row["risk_score"] in THREAT_LEVELS else "MESSAGE_ANALYZED",
            "session": row["waha_session_id"],
            "chat_type": row["chat_type"],
            "input_type": row["input_type"],
            "intent": row["detected_intent"],
            "threat_category": to_threat_category(row["detected_intent"]).value,
            "risk": row["risk_score"],
            "similarity_score": row["similarity_score"],
            "latency_ms": row["response_latency_ms"],
        }
        for row in rows
    ]


async def recent_threats(limit: int = 10, settings: Settings | None = None) -> list[dict[str, Any]]:
    settings = settings or get_settings()
    conn = await _connect(settings)
    try:
        rows = await conn.fetch(RECENT_THREATS_SQL, list(THREAT_LEVELS), limit)
    finally:
        await conn.close()

    return [
        {
            "id": str(row["id"]),
            "at": row["created_at"].isoformat(),
            "session": row["waha_session_id"],
            "chat_type": row["chat_type"],
            "intent": row["detected_intent"],
            "threat_category": to_threat_category(row["detected_intent"]).value,
            "risk": row["risk_score"],
        }
        for row in rows
    ]


async def list_messages(
    limit: int = 25, offset: int = 0, settings: Settings | None = None
) -> dict[str, Any]:
    """Message Inspection ([[04_Message_Inspection]]) — the one query in this
    module that selects `extracted_text`.

    Every other function here follows "never return message content"
    deliberately, because they serve screens with no reason to show it. This
    one is the screen whose entire purpose is showing it to a signed-in
    operator — the retention decision ([[Open_Decisions_Carried_Forward]]
    §2.3) settled on "keep it, readable by any operator, deleted only by
    explicit action" rather than a time-based policy.
    """
    settings = settings or get_settings()
    conn = await _connect(settings)
    try:
        rows = await conn.fetch(MESSAGES_SQL, limit, offset)
        total = await conn.fetchval(MESSAGES_COUNT_SQL)
    finally:
        await conn.close()

    return {
        "total": total,
        "items": [
            {
                "id": str(row["id"]),
                "at": row["created_at"].isoformat(),
                "session": row["waha_session_id"],
                "chat_type": row["chat_type"],
                "input_type": row["input_type"],
                "extracted_text": row["extracted_text"],
                "intent": row["detected_intent"],
                "threat_category": to_threat_category(row["detected_intent"]).value,
                "risk": row["risk_score"],
                "similarity_score": row["similarity_score"],
                "latency_ms": row["response_latency_ms"],
            }
            for row in rows
        ],
    }


async def delete_message(message_id: str, settings: Settings | None = None) -> bool:
    """Remove one message log row. Returns False if it was already gone."""
    settings = settings or get_settings()
    conn = await _connect(settings)
    try:
        result = await conn.execute("DELETE FROM message_logs WHERE id = $1", message_id)
    finally:
        await conn.close()
    return result.endswith(" 1")


def unavailable(reason: str) -> dict[str, Any]:
    """Honest empty state for a block whose data source does not exist yet."""
    return {"available": False, "reason": reason, "items": []}
