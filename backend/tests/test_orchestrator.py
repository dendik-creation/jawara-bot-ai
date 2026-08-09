"""End-to-end pipeline orchestration, with every external hop stubbed.

These tests are about *ordering and degradation*: which stage runs for which
intent, what the risk becomes when a stage cannot answer, and whether an audit
row still lands when something downstream fails.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.clients.ml_client import MlResponse, MlServiceError
from app.clients.waha_client import SendResult
from app.core.config import Settings
from app.pipeline import orchestrator
from app.pipeline.categories import RiskLevel
from app.pipeline.url_safety import UrlRisk, UrlScanResult
from app.schemas.queue import MessageJob

HOAX_TEXT = "Tolong cek berita ini: air rebusan daun kitolod bisa sembuhkan katarak tanpa operasi"
PHISHING_TEXT = "Benar gak link ini http://bansos-pemerintah-2026.com buat klaim bantuan 2 juta?"

KB_MATCH = {
    "fact_item_id": "c39a04f2-5b9e-4a6c-9407-1d82136e0510",
    "title": "Klaim Daun Kitolod",
    "claim_text": "Air rebusan daun kitolod menyembuhkan katarak.",
    "fact_explanation": "Kemenkes menegaskan hal ini berbahaya.",
    "verdict": "HOAX",
    "source_url": "https://turnbackhoax.id/x",
    "score": 0.91,
}


def job(text: str = HOAX_TEXT, **payload_overrides) -> MessageJob:
    payload = {"id": "false_628111@c.us_ABCDEF", "from": "628111@c.us", "body": text}
    payload.update(payload_overrides)
    return MessageJob(
        waha_message_id=payload.get("id"),
        session="default",
        event_name="message.any",
        chat_id=payload.get("from"),
        event={"event": "message.any", "session": "default", "payload": payload},
    )


class FakeMlClient:
    def __init__(self, matches=None, rag_error=None, generate_error=None, message="reply"):
        self._matches = matches or []
        self._rag_error = rag_error
        self._generate_error = generate_error
        self._message = message
        self.generate_calls: list[dict] = []
        self.rag_calls: list[str] = []

    async def rag_query(self, request_id, query, category=None, **_):
        self.rag_calls.append(query)
        if self._rag_error:
            raise self._rag_error
        return MlResponse(request_id, {"matches": self._matches}, "hash-embed-v0")

    async def generate(self, request_id, user_text, category, risk_level, context=None, url_verdicts=None):
        self.generate_calls.append(
            {
                "user_text": user_text,
                "category": category,
                "risk_level": risk_level,
                "context": context,
                "url_verdicts": url_verdicts,
            }
        )
        if self._generate_error:
            raise self._generate_error
        return MlResponse(request_id, {"message": self._message}, "template-composer-v1")


class FakeWaha:
    def __init__(self, delivered: bool = True, bot_ids: frozenset[str] = frozenset()):
        self.delivered = delivered
        self.sent: list[tuple[str, str]] = []
        self.quoted: list[str | None] = []
        self._bot_ids = bot_ids

    async def send_text(self, chat_id, text, session="default", reply_to=None):
        self.sent.append((chat_id, text))
        self.quoted.append(reply_to)
        return SendResult(delivered=self.delivered, chat_id=chat_id, attempts=1, error="" if self.delivered else "timeout")

    async def session_identity(self, session):
        return self._bot_ids


class FakeRedis:
    async def aclose(self):
        return None


@pytest.fixture
def rig(monkeypatch):
    """Stub every outbound hop; return the handles the tests assert on."""
    state: dict[str, object] = {}

    def install(ml=None, waha=None, url_scan=None, logged=True, log_error=None):
        ml = ml or FakeMlClient()
        waha = waha or FakeWaha()
        rows: list = []

        monkeypatch.setattr(orchestrator.aioredis, "from_url", lambda *a, **k: FakeRedis())
        monkeypatch.setattr(orchestrator, "MlClient", lambda settings: ml)
        monkeypatch.setattr(orchestrator, "WahaClient", lambda settings: waha)

        async def fake_scan(urls, redis=None, settings=None):
            return url_scan or UrlScanResult(risk=RiskLevel.UNKNOWN)

        monkeypatch.setattr(orchestrator, "scan_urls", fake_scan)

        async def fake_record(entry, settings=None):
            if log_error:
                raise log_error
            rows.append(entry)
            return logged

        monkeypatch.setattr(orchestrator, "record_message", fake_record)

        state.update(ml=ml, waha=waha, rows=rows)
        return state

    return install


SETTINGS = Settings(user_hash_salt="test-salt", end_to_end_target_ms=3000)


async def test_text_hoax_runs_rag_then_generates_and_dispatches(rig):
    state = rig(ml=FakeMlClient(matches=[KB_MATCH], message="pesan balasan"))

    result = await orchestrator.process_message_job(job(), {}, SETTINGS)

    assert result["intent"] == "HEALTH_HOAX"
    assert result["engine"] == "text_verification"
    assert result["risk"] == "HIGH"  # verdict HOAX
    assert result["match_count"] == 1
    assert result["similarity_score"] == 0.91
    assert result["response_dispatched"] is True
    assert state["waha"].sent[0][1] == "pesan balasan"


async def test_generation_receives_the_raw_user_text_not_the_normalised_one(rig):
    state = rig(ml=FakeMlClient(matches=[KB_MATCH]))
    await orchestrator.process_message_job(job(), {}, SETTINGS)

    # The reply quotes the user back; a mangled quote reads as broken.
    assert state["ml"].generate_calls[0]["user_text"] == HOAX_TEXT


async def test_phishing_link_runs_url_safety_not_rag(rig):
    scan = UrlScanResult(
        risk=RiskLevel.HIGH,
        urls=(
            UrlRisk(
                url="http://bansos-pemerintah-2026.com",
                domain="bansos-pemerintah-2026.com",
                is_shortlink=False,
                risk=RiskLevel.HIGH,
                reason="flagged_by=safe_browsing",
            ),
        ),
    )
    state = rig(url_scan=scan)

    result = await orchestrator.process_message_job(job(PHISHING_TEXT), {}, SETTINGS)

    assert result["engine"] == "url_safety"
    assert result["risk"] == "HIGH"
    assert result["match_count"] == 0
    assert state["ml"].generate_calls[0]["url_verdicts"][0]["risk"] == "HIGH"


async def test_ml_service_down_degrades_to_rules_only_and_still_logs(rig):
    state = rig(
        ml=FakeMlClient(
            rag_error=MlServiceError("ml_unreachable", "down", retryable=True),
            generate_error=MlServiceError("ml_unreachable", "down", retryable=True),
        )
    )

    result = await orchestrator.process_message_job(job(), {}, SETTINGS)

    assert any(item.startswith("ml_unavailable") for item in result["degradations"])
    assert any(item.startswith("generation_unavailable") for item in result["degradations"])
    assert result["response_dispatched"] is False
    assert result["logged"] is True  # the audit trail survives the outage
    assert state["rows"][0].risk_score is RiskLevel.MEDIUM


async def test_no_knowledge_match_is_unverified_not_a_weak_match(rig):
    rig(ml=FakeMlClient(matches=[]))
    result = await orchestrator.process_message_job(job(), {}, SETTINGS)

    assert result["match_count"] == 0
    assert result["risk"] == "MEDIUM"
    assert "knowledge_unverified" in result["degradations"]


async def test_audit_row_carries_intent_risk_latency_and_hashed_user(rig):
    state = rig(ml=FakeMlClient(matches=[KB_MATCH]))
    message = job()
    message.received_at = datetime.now(timezone.utc) - timedelta(milliseconds=120)

    await orchestrator.process_message_job(message, {}, SETTINGS)

    entry = state["rows"][0]
    assert entry.waha_message_id == "false_628111@c.us_ABCDEF"
    assert entry.detected_intent.value == "HEALTH_HOAX"
    assert entry.risk_score is RiskLevel.HIGH
    assert entry.matched_fact_id == KB_MATCH["fact_item_id"]
    assert entry.similarity_score == 0.91
    assert entry.response_latency_ms >= 100
    assert entry.chat_type == "PERSONAL"
    assert len(entry.user_hash) == 64 and "628111" not in entry.user_hash


GROUP_ID = "62811-1234@g.us"
BOT_IDS = frozenset({"6287712032005@c.us"})


def group_job(text: str = HOAX_TEXT, **payload_overrides) -> MessageJob:
    return job(text, id="x1", **{"from": GROUP_ID, "participant": "628999@c.us", **payload_overrides})


async def test_group_chat_is_recorded_as_group_when_the_bot_is_addressed(rig):
    state = rig(ml=FakeMlClient(matches=[KB_MATCH]), waha=FakeWaha(bot_ids=BOT_IDS))

    await orchestrator.process_message_job(
        group_job(mentionedIds=["6287712032005@c.us"]), {}, SETTINGS
    )

    assert state["rows"][0].chat_type == "GROUP"


async def test_group_message_the_bot_was_not_addressed_in_is_dropped_before_any_work(rig):
    """No reply, no ML call, and no audit row holding what the group said."""
    ml = FakeMlClient(matches=[KB_MATCH])
    state = rig(ml=ml, waha=FakeWaha(bot_ids=BOT_IDS))

    result = await orchestrator.process_message_job(group_job(), {}, SETTINGS)

    assert result["status"] == "ignored_group_not_addressed"
    assert state["waha"].sent == []
    assert state["rows"] == []
    assert ml.rag_calls == []


async def test_group_reply_quotes_the_message_that_summoned_the_bot(rig):
    state = rig(ml=FakeMlClient(matches=[KB_MATCH]), waha=FakeWaha(bot_ids=BOT_IDS))

    await orchestrator.process_message_job(
        group_job(mentionedIds=["6287712032005@c.us"]), {}, SETTINGS
    )

    assert state["waha"].quoted == ["x1"]


async def test_direct_chat_reply_is_not_quoted(rig):
    """Nothing to disambiguate in a one-to-one chat; the quote would be clutter."""
    state = rig(ml=FakeMlClient(matches=[KB_MATCH]), waha=FakeWaha(bot_ids=BOT_IDS))

    await orchestrator.process_message_job(job(), {}, SETTINGS)

    assert state["waha"].quoted == [None]


async def test_bot_mention_is_not_analysed_as_message_content(rig):
    ml = FakeMlClient(matches=[KB_MATCH])
    rig(ml=ml, waha=FakeWaha(bot_ids=BOT_IDS))

    await orchestrator.process_message_job(
        group_job(text=f"@6287712032005 {HOAX_TEXT}", mentionedIds=["6287712032005@c.us"]),
        {},
        SETTINGS,
    )

    assert "6287712032005" not in ml.generate_calls[0]["user_text"]


async def test_bare_mention_answers_with_instructions_instead_of_silence(rig):
    ml = FakeMlClient(matches=[KB_MATCH])
    state = rig(ml=ml, waha=FakeWaha(bot_ids=BOT_IDS))

    result = await orchestrator.process_message_job(
        group_job(text="@6287712032005", mentionedIds=["6287712032005@c.us"]), {}, SETTINGS
    )

    assert result["status"] == "mention_without_content"
    assert state["waha"].sent[0][1] == orchestrator.EMPTY_MENTION_REPLY
    assert ml.generate_calls == []  # nothing to analyse, so nothing is generated


async def test_dispatch_failure_is_recorded_and_still_audited(rig):
    state = rig(ml=FakeMlClient(matches=[KB_MATCH]), waha=FakeWaha(delivered=False))

    result = await orchestrator.process_message_job(job(), {}, SETTINGS)

    assert result["response_dispatched"] is False
    assert any(item.startswith("dispatch_failed") for item in result["degradations"])
    assert len(state["rows"]) == 1


async def test_audit_write_failure_does_not_lose_the_sent_reply(rig):
    rig(ml=FakeMlClient(matches=[KB_MATCH]), log_error=RuntimeError("db down"))

    result = await orchestrator.process_message_job(job(), {}, SETTINGS)

    assert result["response_dispatched"] is True
    assert result["logged"] is False
    assert "audit_write_failed" in result["degradations"]


async def test_own_outbound_message_is_ignored(rig):
    state = rig()
    result = await orchestrator.process_message_job(job(fromMe=True), {}, SETTINGS)

    assert result["status"] == "ignored_own_message"
    assert state["waha"].sent == []


async def test_session_status_event_is_not_run_through_detection(rig):
    state = rig()
    message = job()
    message.event_name = "session.status"

    result = await orchestrator.process_message_job(message, {}, SETTINGS)

    assert result["status"] == "ignored_non_message_event"
    assert state["rows"] == []


async def test_empty_body_without_attachment_is_ignored(rig):
    rig()
    result = await orchestrator.process_message_job(job(text="   "), {}, SETTINGS)
    assert result["status"] == "ignored_empty_body"


async def test_apk_attachment_is_warned_without_static_analysis(rig):
    state = rig()
    message = job(text="ini aman gak ya?", filename="Undangan_Pernikahan.apk")

    result = await orchestrator.process_message_job(message, {}, SETTINGS)

    assert result["intent"] == "FILE_APK"
    assert result["engine"] == "apk_warning"
    assert result["risk"] == "HIGH"
    assert state["rows"][0].input_type.value == "FILE_APK"
