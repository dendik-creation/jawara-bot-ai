"""Anonymous audit trail: one `message_logs` row per processed message.

[[Create Audit Logging]] — the system of record behind the milestone's "logging
works correctly" criterion and behind the privacy claim in the value
proposition. Two properties matter more than the write itself:

**Anonymity.** The row is keyed by `user_hash` = SHA-256(salt + ':' + chat id).
The raw WhatsApp number never reaches the database. `user_subscriptions` is
upserted first because `message_logs.user_hash` is a foreign key onto it — a
message from a chat we have never seen would otherwise fail the insert.

**Idempotency.** `waha_message_id` is UNIQUE and the insert is
`ON CONFLICT DO NOTHING`. WAHA retries webhooks; a retry that reaches the worker
must not produce a second row, and must not raise either.

Known open issue, out of scope for this task but not forgotten: `extracted_text`
is stored in plaintext with no retention window
(01_Documentation_Audit_Report finding #1). `LOG_MESSAGE_CONTENT=false` turns the
column off entirely for deployments that want the trail without the content.
"""

import logging
from dataclasses import dataclass

import asyncpg

from app.core.config import Settings, get_settings
from app.pipeline.categories import Category, InputType, RiskLevel

logger = logging.getLogger("app.services.message_log")

GROUP_SUFFIX = "@g.us"

UPSERT_SUBSCRIPTION = """
INSERT INTO user_subscriptions (user_hash, chat_type)
VALUES ($1, $2)
ON CONFLICT (user_hash) DO NOTHING
"""

INSERT_LOG = """
INSERT INTO message_logs (
    waha_message_id, waha_session_id, user_hash, chat_type, input_type,
    extracted_text, detected_intent, risk_score, matched_fact_id,
    similarity_score, response_latency_ms
)
VALUES ($1, $2, $3, $4, $5::input_type_enum, $6, $7::category_enum,
        $8::risk_level_enum, $9, $10, $11)
ON CONFLICT (waha_message_id) DO NOTHING
RETURNING id
"""


def chat_type_for(chat_id: str | None) -> str:
    """`GROUP` for `...@g.us`, `PERSONAL` otherwise — the CHECK constraint allows no third value."""
    return "GROUP" if (chat_id or "").endswith(GROUP_SUFFIX) else "PERSONAL"


@dataclass(frozen=True)
class MessageLogEntry:
    """One row of `message_logs`, already anonymised."""

    waha_message_id: str
    user_hash: str
    chat_type: str
    input_type: InputType
    waha_session_id: str = "default"
    extracted_text: str | None = None
    detected_intent: Category | None = None
    risk_score: RiskLevel = RiskLevel.UNKNOWN
    matched_fact_id: str | None = None
    similarity_score: float | None = None
    response_latency_ms: int | None = None


async def record_message(
    entry: MessageLogEntry,
    settings: Settings | None = None,
    connection: asyncpg.Connection | None = None,
) -> bool:
    """Persist one processed message. Returns False when it was already logged.

    Never raises on a duplicate; does raise if the database itself is
    unreachable, so the Celery retry policy can do its job.
    """
    settings = settings or get_settings()
    owns_connection = connection is None
    conn = connection or await asyncpg.connect(settings.database_url, timeout=5)

    try:
        async with conn.transaction():
            await conn.execute(UPSERT_SUBSCRIPTION, entry.user_hash, entry.chat_type)
            row = await conn.fetchrow(
                INSERT_LOG,
                entry.waha_message_id,
                entry.waha_session_id,
                entry.user_hash,
                entry.chat_type,
                entry.input_type.value,
                entry.extracted_text if settings.log_message_content else None,
                entry.detected_intent.value if entry.detected_intent else None,
                entry.risk_score.value,
                entry.matched_fact_id,
                entry.similarity_score,
                entry.response_latency_ms,
            )
    finally:
        if owns_connection:
            await conn.close()

    inserted = row is not None
    if not inserted:
        logger.info(
            "message already logged, skipping duplicate",
            extra={"waha_message_id": entry.waha_message_id},
        )
    return inserted
