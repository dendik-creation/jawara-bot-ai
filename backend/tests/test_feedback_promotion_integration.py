"""Feedback -> dataset promotion against a live PostgreSQL.

The eligibility query (`NOT EXISTS ... source_feedback_id`), the label
derivation from real `feedback_type`/`original_classification` enum values,
and the DRAFT-only guard are all database facts a mocked connection could
only pretend to have. Skipped when Postgres is unreachable, same as the
other integration suites.
"""

import uuid

import asyncpg
import pytest

from app.core.config import Settings
from app.services import datasets
from app.services import feedback as feedback_service

pytestmark = pytest.mark.integration


@pytest.fixture
def promo_settings(postgres_dsn):
    return Settings(database_url=postgres_dsn)


@pytest.fixture
async def env(promo_settings):
    """Operator + dataset + four message_logs/operator_feedback rows
    covering: a normal CONFIRM, a normal FALSE_POSITIVE, a CONFIRM with no
    `original_classification`, and a FALSE_POSITIVE on a message with no
    `extracted_text`. Cleaned up afterwards regardless of outcome.
    """
    conn = await asyncpg.connect(promo_settings.database_url)

    operator_id = await conn.fetchval(
        """
        INSERT INTO operators (email, full_name, password_hash)
        VALUES ($1, 'Promo Test Operator', 'x')
        RETURNING id
        """,
        f"promo-test-{uuid.uuid4()}@example.com",
    )

    dataset = await datasets.create_dataset(
        f"promo-test-{uuid.uuid4()}", 1, "OPERATOR_FEEDBACK", "promotion integration test", str(operator_id),
        settings=promo_settings,
    )
    dataset_id = dataset["id"]

    user_hash = f"promo-test-{uuid.uuid4().hex}"
    await conn.execute("INSERT INTO user_subscriptions (user_hash, chat_type) VALUES ($1, 'PERSONAL')", user_hash)

    async def _message(text: str | None, intent: str | None) -> str:
        return await conn.fetchval(
            """
            INSERT INTO message_logs (waha_message_id, user_hash, chat_type, input_type, extracted_text, detected_intent)
            VALUES ($1, $2, 'PERSONAL', 'TEXT', $3, $4::category_enum)
            RETURNING id
            """,
            f"promo-test-{uuid.uuid4()}",
            user_hash,
            text,
            intent,
        )

    msg_confirm = await _message("pesan hoax soal obat kanker", "HEALTH_HOAX")
    msg_false_positive = await _message("pesan biasa yang ternyata aman", "PHISHING_LINK")
    msg_confirm_no_intent = await _message("pesan yang belum pernah diklasifikasi", None)
    msg_empty_text = await _message(None, "FINANCIAL_FRAUD")

    async def _feedback(message_log_id: str, feedback_type: str) -> str:
        return await conn.fetchval(
            """
            INSERT INTO operator_feedback (message_log_id, original_classification, feedback_type, actor_operator_id)
            VALUES ($1, (SELECT detected_intent FROM message_logs WHERE id = $1), $2::feedback_type_enum, $3)
            RETURNING id
            """,
            message_log_id,
            feedback_type,
            operator_id,
        )

    feedback_confirm = await _feedback(msg_confirm, "CONFIRM")
    feedback_false_positive = await _feedback(msg_false_positive, "FALSE_POSITIVE")
    feedback_confirm_no_intent = await _feedback(msg_confirm_no_intent, "CONFIRM")
    feedback_empty_text = await _feedback(msg_empty_text, "FALSE_POSITIVE")

    try:
        yield {
            "conn": conn,
            "settings": promo_settings,
            "operator_id": str(operator_id),
            "dataset_id": dataset_id,
            "feedback_confirm": str(feedback_confirm),
            "feedback_false_positive": str(feedback_false_positive),
            "feedback_confirm_no_intent": str(feedback_confirm_no_intent),
            "feedback_empty_text": str(feedback_empty_text),
        }
    finally:
        await conn.execute("DELETE FROM dataset_samples WHERE dataset_id = $1", dataset_id)
        await conn.execute("DELETE FROM datasets WHERE id = $1", dataset_id)
        await conn.execute(
            "DELETE FROM operator_feedback WHERE id = ANY($1::uuid[])",
            [feedback_confirm, feedback_false_positive, feedback_confirm_no_intent, feedback_empty_text],
        )
        await conn.execute(
            "DELETE FROM message_logs WHERE id = ANY($1::uuid[])",
            [msg_confirm, msg_false_positive, msg_confirm_no_intent, msg_empty_text],
        )
        await conn.execute("DELETE FROM user_subscriptions WHERE user_hash = $1", user_hash)
        await conn.execute("DELETE FROM operators WHERE id = $1", operator_id)
        await conn.close()


async def test_promotes_confirm_and_false_positive_with_derived_labels(env):
    result = await feedback_service.promote_to_dataset(
        env["dataset_id"], env["operator_id"], settings=env["settings"]
    )

    assert result["considered"] == 4
    assert result["promoted"] == 2
    assert result["skipped"] == 2
    assert result["skipped_reasons"] == {
        "confirm_without_original_classification": 1,
        "empty_message_text": 1,
    }

    rows = await env["conn"].fetch(
        "SELECT label, source_feedback_id FROM dataset_samples WHERE dataset_id = $1", env["dataset_id"]
    )
    by_feedback = {str(row["source_feedback_id"]): row["label"] for row in rows}
    assert by_feedback[env["feedback_confirm"]] == "HEALTH_HOAX"
    assert by_feedback[env["feedback_false_positive"]] == "NOT_A_THREAT"


async def test_rerunning_only_picks_up_unlinked_feedback(env):
    first = await feedback_service.promote_to_dataset(env["dataset_id"], env["operator_id"], settings=env["settings"])
    assert first["promoted"] == 2

    second = await feedback_service.promote_to_dataset(env["dataset_id"], env["operator_id"], settings=env["settings"])
    assert second["promoted"] == 0
    assert second["considered"] == 2  # the two still-unpromoted skip cases


async def test_feedback_type_filter_narrows_eligibility(env):
    result = await feedback_service.promote_to_dataset(
        env["dataset_id"], env["operator_id"], feedback_type="FALSE_POSITIVE", settings=env["settings"]
    )
    assert result["considered"] == 2  # both FALSE_POSITIVE rows, one skipped for empty text
    assert result["promoted"] == 1


async def test_unknown_dataset_is_none_not_an_error(env):
    result = await feedback_service.promote_to_dataset(
        str(uuid.uuid4()), env["operator_id"], settings=env["settings"]
    )
    assert result is None


async def test_non_draft_dataset_is_rejected(env):
    await datasets.apply_dataset_action(env["dataset_id"], action="VALIDATE", settings=env["settings"])

    with pytest.raises(ValueError, match="cannot promote feedback"):
        await feedback_service.promote_to_dataset(env["dataset_id"], env["operator_id"], settings=env["settings"])
