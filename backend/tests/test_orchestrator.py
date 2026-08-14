"""End-to-end pipeline orchestration, with every external hop stubbed.

These tests are about *ordering and degradation*: which stage runs for which
intent, what the risk becomes when a stage cannot answer, and whether an audit
row still lands when something downstream fails.
"""

import base64
from datetime import datetime, timedelta, timezone

import pytest

from app.clients.ml_client import MlResponse, MlServiceError
from app.clients.waha_client import SendResult
from app.core.config import Settings
from app.pipeline import orchestrator
from app.pipeline.categories import RiskLevel
from app.pipeline.normalizer import normalize_text
from app.pipeline.url_safety import UrlRisk, UrlScanResult
from app.schemas.queue import MessageJob

HOAX_TEXT = "Tolong cek berita ini: air rebusan daun kitolod bisa sembuhkan katarak tanpa operasi"
PHISHING_TEXT = "Benar gak link ini http://bansos-pemerintah-2026.com buat klaim bantuan 2 juta?"

# What reaches claim extraction and retrieval: normalisation (stage 4) runs
# before either of them.
NORMALIZED_HOAX = normalize_text(HOAX_TEXT).text

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
    def __init__(
        self,
        matches=None,
        rag_error=None,
        generate_error=None,
        message="reply",
        classify_result=None,
        classify_error=None,
        claim=None,
        claim_error=None,
        reranked=True,
        ocr_result=None,
        ocr_error=None,
        ocr_confidence=0.9,
    ):
        self._matches = matches or []
        self._rag_error = rag_error
        self._generate_error = generate_error
        self._message = message
        self._classify_result = classify_result
        self._classify_error = classify_error
        self._claim = claim
        self._claim_error = claim_error
        self._reranked = reranked
        self._ocr_result = ocr_result
        self._ocr_error = ocr_error
        self._ocr_confidence = ocr_confidence
        self.generate_calls: list[dict] = []
        self.rag_calls: list[str] = []
        self.classify_calls: list[dict] = []
        self.claim_calls: list[str] = []
        self.ocr_calls: list[dict] = []

    async def extract_claim(self, request_id, text, category=None):
        self.claim_calls.append(text)
        if self._claim_error:
            raise self._claim_error
        # Default: the service's "message is already a claim" passthrough, so
        # tests that don't care about extraction see the text they wrote.
        claim = self._claim if self._claim is not None else text
        method = "llm" if self._claim is not None else "passthrough"
        return MlResponse(request_id, {"claim": claim, "method": method}, "claim-stub-v1")

    async def rag_query(self, request_id, query, category=None, **_):
        self.rag_calls.append(query)
        if self._rag_error:
            raise self._rag_error
        return MlResponse(
            request_id, {"matches": self._matches, "reranked": self._reranked}, "hash-embed-v0"
        )

    async def classify(self, request_id, text, model_version, expected_sha256):
        self.classify_calls.append(
            {"text": text, "model_version": model_version, "expected_sha256": expected_sha256}
        )
        if self._classify_error:
            raise self._classify_error
        category, confidence = self._classify_result or ("NOT_A_THREAT", 0.9)
        return MlResponse(request_id, {"category": category}, model_version, confidence=confidence)

    async def ocr(self, request_id, image, filename, mimetype, language=None):
        self.ocr_calls.append({"filename": filename, "mimetype": mimetype, "size": len(image)})
        if self._ocr_error:
            raise self._ocr_error
        # Default: a successful read of a news-screenshot-shaped image.
        result = self._ocr_result if self._ocr_result is not None else {
            "text": "BREAKING NEWS klaim kesehatan viral",
            "success": True,
            "language": "ind+eng",
            "error": None,
        }
        return MlResponse(request_id, result, "tesseract-ocr", confidence=self._ocr_confidence)

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
    def __init__(
        self,
        delivered: bool = True,
        bot_ids: frozenset[str] = frozenset(),
        quoted_text: str | None = None,
        quoted_media: dict | None = None,
        quoted_has_media: bool = False,
        quoted_media_after_download: dict | None = None,
        media_bytes: bytes | None = None,
    ):
        self.delivered = delivered
        self.sent: list[tuple[str, str]] = []
        self.quoted: list[str | None] = []
        self._bot_ids = bot_ids
        self._quoted_text = quoted_text
        self._quoted_media = quoted_media
        self._quoted_has_media = quoted_has_media
        self._quoted_media_after_download = quoted_media_after_download
        self._media_bytes = media_bytes
        self.get_message_calls: list[dict] = []
        self.download_media_calls: list[str] = []

    async def send_text(self, chat_id, text, session="default", reply_to=None):
        self.sent.append((chat_id, text))
        self.quoted.append(reply_to)
        return SendResult(delivered=self.delivered, chat_id=chat_id, attempts=1, error="" if self.delivered else "timeout")

    async def session_identity(self, session):
        return self._bot_ids

    async def get_message(self, session, chat_id, message_id, download_media=False):
        """Mirrors `WahaClient.get_message` — the raw message payload a
        reply's `!cek`/`!link` resolves against, text and/or media.
        `quoted_media_after_download` simulates WAHA only resolving an
        attachment once asked with `?downloadMedia=true` — absent on the
        first (plain) fetch, present only when `download_media=True`."""
        self.get_message_calls.append(
            {"session": session, "chat_id": chat_id, "message_id": message_id, "download_media": download_media}
        )
        if download_media and self._quoted_media_after_download is not None:
            data: dict = {"media": self._quoted_media_after_download, "hasMedia": True}
            if self._quoted_text is not None:
                data["body"] = self._quoted_text
            return data
        if self._quoted_text is None and self._quoted_media is None and not self._quoted_has_media:
            return None
        data = {}
        if self._quoted_text is not None:
            data["body"] = self._quoted_text
        if self._quoted_media is not None:
            data["media"] = self._quoted_media
            data["hasMedia"] = True
        elif self._quoted_has_media:
            data["hasMedia"] = True
        return data

    async def get_message_text(self, session, chat_id, message_id):
        data = await self.get_message(session, chat_id, message_id)
        return data.get("body") if data else None

    async def download_media(self, url):
        self.download_media_calls.append(url)
        return self._media_bytes


class FakeRedis:
    async def aclose(self):
        return None


@pytest.fixture
def rig(monkeypatch):
    """Stub every outbound hop; return the handles the tests assert on."""
    state: dict[str, object] = {}

    def install(ml=None, waha=None, url_scan=None, logged=True, log_error=None, production_model=None):
        ml = ml or FakeMlClient()
        waha = waha or FakeWaha()
        rows: list = []

        monkeypatch.setattr(orchestrator.aioredis, "from_url", lambda *a, **k: FakeRedis())
        monkeypatch.setattr(orchestrator, "MlClient", lambda settings: ml)
        monkeypatch.setattr(orchestrator, "WahaClient", lambda settings: waha)

        # No live Postgres in a unit test, and no promoted model by default —
        # every existing test exercises the "inert until promoted" path
        # unless it opts in via `production_model=`.
        async def fake_production_model(settings):
            return production_model

        monkeypatch.setattr(orchestrator, "_cached_production_model", fake_production_model)

        async def fake_scan(urls, redis=None, settings=None, trusted_lookup=None, request_id=None):
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
SETTINGS_OCR = Settings(user_hash_salt="test-salt", end_to_end_target_ms=3000, ocr_enabled=True)


def image_job(*, text: str = "", media_overrides: dict | None = None, **payload_overrides) -> MessageJob:
    """A message carrying an image attachment (inline base64 by default, no
    filename) — the shape `_image_attachment()` must recognise even without
    the generic `_attachment_names()` filename fields."""
    media = {"mimetype": "image/jpeg", "data": base64.b64encode(b"fake-jpeg-bytes").decode()}
    if media_overrides:
        media.update(media_overrides)
    return job(text=text, media=media, **payload_overrides)


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
    # `/v1/generate` never answering must not leave the command silent (the
    # same "always SUCCESS or USER_SAFE_FAILURE, never nothing" guarantee
    # 4d2cc1d enforces at the task-retry level, here for the one stage that
    # degrades without the task itself raising).
    assert result["response_dispatched"] is True
    assert state["waha"].sent[0][1] == orchestrator.GENERATION_UNAVAILABLE_REPLY
    assert result["logged"] is True  # the audit trail survives the outage
    assert state["rows"][0].risk_score is RiskLevel.MEDIUM


async def test_no_knowledge_match_is_unverified_not_a_weak_match(rig):
    rig(ml=FakeMlClient(matches=[]))
    result = await orchestrator.process_message_job(job(), {}, SETTINGS)

    assert result["match_count"] == 0
    assert result["risk"] == "MEDIUM"
    assert "knowledge_unverified" in result["degradations"]


# --------------------------------------------------------------------------
# Claim extraction ahead of retrieval
# --------------------------------------------------------------------------


async def test_retrieval_queries_the_extracted_claim_not_the_raw_forward(rig):
    """The point of the step: a chain letter's greeting and "TOLONG
    SEBARKAN!!!" are embedded too, and they pull the vector away from the
    curated claim the knowledge base stores."""
    claim = "Air rebusan daun kitolod menyembuhkan katarak tanpa operasi."
    state = rig(ml=FakeMlClient(matches=[KB_MATCH], claim=claim))

    result = await orchestrator.process_message_job(job(), {}, SETTINGS)

    assert state["ml"].claim_calls == [NORMALIZED_HOAX]
    assert state["ml"].rag_calls == [claim]
    assert result["claim_method"] == "llm"
    assert result["reranked"] is True


async def test_generation_still_sees_the_user_text_not_the_claim(rig):
    """Extraction improves *retrieval*. The reply still quotes what the user
    actually sent — replying to a rewritten version reads as a broken bot."""
    state = rig(ml=FakeMlClient(matches=[KB_MATCH], claim="Klaim ringkas."))

    await orchestrator.process_message_job(job(), {}, SETTINGS)

    assert state["ml"].generate_calls[0]["user_text"] == HOAX_TEXT


async def test_claim_extraction_failure_falls_back_to_the_raw_text(rig):
    state = rig(ml=FakeMlClient(matches=[KB_MATCH], claim_error=MlServiceError("ml_timeout", "slow", True)))

    result = await orchestrator.process_message_job(job(), {}, SETTINGS)

    # Retrieval still happened, on the unprocessed message.
    assert state["ml"].rag_calls == [NORMALIZED_HOAX]
    assert result["match_count"] == 1
    assert any(d.startswith("claim_extraction_unavailable") for d in result["degradations"])


async def test_an_empty_extraction_is_ignored_rather_than_queried(rig):
    """An empty query would embed to noise and retrieve nonsense — worse than
    not extracting at all."""
    state = rig(ml=FakeMlClient(matches=[KB_MATCH], claim="   "))

    await orchestrator.process_message_job(job(), {}, SETTINGS)

    assert state["ml"].rag_calls == [NORMALIZED_HOAX]


async def test_claim_extraction_can_be_switched_off(rig):
    state = rig(ml=FakeMlClient(matches=[KB_MATCH], claim="Klaim ringkas."))
    settings = Settings(
        user_hash_salt="test-salt", end_to_end_target_ms=3000, rag_claim_extraction_enabled=False
    )

    result = await orchestrator.process_message_job(job(), {}, settings)

    assert state["ml"].claim_calls == []
    assert state["ml"].rag_calls == [NORMALIZED_HOAX]
    assert result["claim_method"] is None


async def test_url_safety_path_never_pays_for_claim_extraction(rig):
    """Extraction belongs to text verification. A phishing link is checked by
    reputation providers, and an LLM round trip there is pure latency."""
    state = rig(ml=FakeMlClient(claim="tidak dipakai"))

    await orchestrator.process_message_job(job(PHISHING_TEXT), {}, SETTINGS)

    assert state["ml"].claim_calls == []


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


def group_job(text: str = f"!cek {HOAX_TEXT}", **payload_overrides) -> MessageJob:
    """A group message. `text` defaults to a valid `!cek` command — the
    strict command gate (JAWARA Strict WhatsApp Command System) means a bare
    mention no longer reaches the pipeline, so every group test that wants
    the message actually analysed needs a recognised command in the body."""
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


async def test_bare_reply_fetches_and_analyses_the_quoted_message(rig):
    """A reply with no new text of its own — the quoted message *is* the ask."""
    quoted = "Air rebusan daun kitolod bisa sembuhkan katarak tanpa operasi, sudah terbukti klinis"
    ml = FakeMlClient(matches=[KB_MATCH])
    waha = FakeWaha(quoted_text=quoted)
    rig(ml=ml, waha=waha)

    result = await orchestrator.process_message_job(
        job("", replyTo={"id": "orig-msg-1"}), {}, SETTINGS
    )

    assert waha.get_message_calls[0]["message_id"] == "orig-msg-1"
    assert ml.generate_calls[0]["user_text"] == quoted
    assert result["status"] == "processed"


async def test_reply_with_own_text_folds_quoted_message_in_first(rig):
    quoted = "Air rebusan daun kitolod bisa sembuhkan katarak tanpa operasi"
    ml = FakeMlClient(matches=[KB_MATCH])
    waha = FakeWaha(quoted_text=quoted)
    rig(ml=ml, waha=waha)

    await orchestrator.process_message_job(
        job("apa ini beneran?", replyTo={"id": "orig-msg-1"}), {}, SETTINGS
    )

    assert ml.generate_calls[0]["user_text"] == f"{quoted}\n\napa ini beneran?"


async def test_quoted_message_unavailable_degrades_without_failing(rig):
    """WAHA can't produce the quoted text (deleted, pre-pairing) — degrade, don't drop."""
    ml = FakeMlClient(matches=[])
    waha = FakeWaha(quoted_text=None)
    rig(ml=ml, waha=waha)

    result = await orchestrator.process_message_job(
        job("tolong cek ya", replyTo={"id": "orig-msg-1"}), {}, SETTINGS
    )

    assert "quoted_message_unavailable" in result["degradations"]
    assert ml.generate_calls[0]["user_text"] == "tolong cek ya"


async def test_group_bare_cek_with_quoted_message_is_not_treated_as_empty(rig):
    """'@JAWARA !cek' on a reply is a complete request once the quote resolves."""
    quoted = "Klik link ini buat klaim bansos 2 juta sebelum kuota habis"
    ml = FakeMlClient(matches=[])
    waha = FakeWaha(bot_ids=BOT_IDS, quoted_text=quoted)
    rig(ml=ml, waha=waha)

    result = await orchestrator.process_message_job(
        group_job(text="@6287712032005 !cek", mentionedIds=["6287712032005@c.us"], replyTo={"id": "orig-msg-2"}),
        {},
        SETTINGS,
    )

    assert result["status"] == "processed"
    assert ml.generate_calls[0]["user_text"] == quoted


async def test_bot_mention_is_not_analysed_as_message_content(rig):
    ml = FakeMlClient(matches=[KB_MATCH])
    rig(ml=ml, waha=FakeWaha(bot_ids=BOT_IDS))

    await orchestrator.process_message_job(
        group_job(text=f"@6287712032005 !cek {HOAX_TEXT}", mentionedIds=["6287712032005@c.us"]),
        {},
        SETTINGS,
    )

    assert "6287712032005" not in ml.generate_calls[0]["user_text"]


async def test_bare_mention_without_command_gets_guidance_and_never_calls_ai(rig):
    """'@JAWARA' alone — no `!command` — is the exact case the strict command
    gate exists to stop: it must never reach the classifier, RAG, or the LLM."""
    ml = FakeMlClient(matches=[KB_MATCH])
    state = rig(ml=ml, waha=FakeWaha(bot_ids=BOT_IDS))

    result = await orchestrator.process_message_job(
        group_job(text="@6287712032005", mentionedIds=["6287712032005@c.us"]), {}, SETTINGS
    )

    assert result["status"] == "mention_no_command"
    assert state["waha"].sent[0][1] == orchestrator.MENTION_GUIDANCE_REPLY
    assert ml.generate_calls == []
    assert ml.rag_calls == []
    assert ml.classify_calls == []
    assert ml.ocr_calls == []


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


PRODUCTION_MODEL = {"model_version": "clf-abc123", "artifact_sha256": "deadbeef"}


async def test_ml_classify_is_never_called_without_a_promoted_model(rig):
    """Inert by default (07_Model_Registry_and_Deployment §3-4): shipping the
    classifier infra must not change behaviour until an operator explicitly
    promotes a model.
    """
    state = rig(ml=FakeMlClient(matches=[KB_MATCH]))
    await orchestrator.process_message_job(job(), {}, SETTINGS)

    assert state["ml"].classify_calls == []


async def test_ml_classify_folds_into_risk_once_a_model_is_promoted(rig):
    ml = FakeMlClient(matches=[], classify_result=("FINANCIAL_FRAUD", 0.87))
    state = rig(ml=ml, production_model=PRODUCTION_MODEL)

    result = await orchestrator.process_message_job(job(HOAX_TEXT), {}, SETTINGS)

    assert ml.classify_calls == [
        {"text": orchestrator.normalize_text(HOAX_TEXT).text, "model_version": "clf-abc123", "expected_sha256": "deadbeef"}
    ]
    assert result["ml_category"] == "FINANCIAL_FRAUD"
    assert result["ml_confidence"] == 0.87
    # FINANCIAL_FRAUD -> HIGH in CATEGORY_RISK, which now wins over the
    # rules-engine's own MEDIUM (no knowledge-base match) via worst_risk.
    assert result["risk"] == "HIGH"


async def test_ml_classify_phishing_link_never_overrides_the_url_safety_verdict(rig):
    """A classifier mis-reading a bare `!link` URL body as PHISHING_LINK must
    not force risk to HIGH — the URL-safety engine's own verdict (Safe
    Browsing + VirusTotal + KB trust) is the authoritative signal for links,
    same as the LLM cannot override it in the reply-generation stage."""
    scan = UrlScanResult(
        risk=RiskLevel.LOW,
        urls=(
            UrlRisk(
                url="https://www.detik.com/pop/trending/d-8612709/example",
                domain="detik.com",
                is_shortlink=False,
                risk=RiskLevel.LOW,
                reason="no_provider_flagged",
            ),
        ),
    )
    ml = FakeMlClient(classify_result=("PHISHING_LINK", 0.8))
    state = rig(ml=ml, waha=FakeWaha(bot_ids=BOT_IDS), url_scan=scan, production_model=PRODUCTION_MODEL)

    result = await orchestrator.process_message_job(
        mentioning("!link https://www.detik.com/pop/trending/d-8612709/example"), {}, SETTINGS
    )

    assert result["ml_category"] == "PHISHING_LINK"
    assert result["risk"] == "LOW"


async def test_ml_classify_not_a_threat_does_not_suppress_a_rules_engine_high(rig):
    """Additive only: a LOW/benign ML prediction must never pull risk down."""
    ml = FakeMlClient(matches=[KB_MATCH], classify_result=("NOT_A_THREAT", 0.99))
    rig(ml=ml, production_model=PRODUCTION_MODEL)

    result = await orchestrator.process_message_job(job(), {}, SETTINGS)

    assert result["ml_category"] == "NOT_A_THREAT"
    assert result["risk"] == "HIGH"  # rules engine's own HOAX verdict still wins


async def test_ml_classify_failure_degrades_without_breaking_the_pipeline(rig):
    ml = FakeMlClient(matches=[KB_MATCH], classify_error=MlServiceError("ml_unreachable", "down", retryable=True))
    state = rig(ml=ml, production_model=PRODUCTION_MODEL)

    result = await orchestrator.process_message_job(job(), {}, SETTINGS)

    assert any(item.startswith("ml_classify_unavailable") for item in result["degradations"])
    assert result["response_dispatched"] is True
    assert len(state["rows"]) == 1


async def test_apk_attachment_is_warned_without_static_analysis(rig):
    state = rig()
    message = job(text="ini aman gak ya?", filename="Undangan_Pernikahan.apk")

    result = await orchestrator.process_message_job(message, {}, SETTINGS)

    assert result["intent"] == "FILE_APK"
    assert result["engine"] == "apk_warning"
    assert result["risk"] == "HIGH"
    assert state["rows"][0].input_type.value == "FILE_APK"


# --- OCR: image input becomes text, the rest of the pipeline never knows ----


async def test_ocr_disabled_by_default_image_attachment_is_never_sent_for_ocr(rig):
    """`OCR_ENABLED=false` (the default) must behave exactly like the
    pre-OCR codebase: an image is just an attachment nothing reads.

    `ocr_enabled` explicit here, not inherited from `SETTINGS` — `Settings()`
    reads the developer's real root `.env`, and a machine with
    `OCR_ENABLED=true` set for live testing must not flip this test."""
    ml = FakeMlClient()
    state = rig(ml=ml)
    settings_ocr_off = Settings(user_hash_salt="test-salt", end_to_end_target_ms=3000, ocr_enabled=False)

    result = await orchestrator.process_message_job(
        image_job(media_overrides={"filename": "photo.jpg"}), {}, settings_ocr_off
    )

    assert state["ml"].ocr_calls == []
    assert result["ocr_used"] is False
    assert state["rows"][0].input_type.value == "TEXT"


async def test_image_only_message_without_caption_or_filename_is_not_dropped(rig):
    """No caption, no `filename` field (only inline `media.data`) — the
    pre-OCR empty-body guard would have discarded this as
    `ignored_empty_body`; OCR is the only thing giving it content."""
    ml = FakeMlClient(matches=[KB_MATCH], message="pesan balasan", ocr_result={
        "text": HOAX_TEXT, "success": True, "language": "ind+eng", "error": None,
    })
    state = rig(ml=ml)

    result = await orchestrator.process_message_job(image_job(), {}, SETTINGS_OCR)

    assert result["status"] == "processed"
    assert result["intent"] == "HEALTH_HOAX"
    assert result["engine"] == "text_verification"
    assert result["risk"] == "HIGH"
    assert result["ocr_used"] is True
    assert result["ocr_confidence"] == 0.9
    assert state["ml"].ocr_calls == [{"filename": "image", "mimetype": "image/jpeg", "size": len(b"fake-jpeg-bytes")}]
    assert state["rows"][0].input_type.value == "IMAGE_OCR"


async def test_ocr_extracted_text_reaches_the_exact_same_verdict_as_typed_text(rig):
    """Regression proof for [[OCR Image Detection]] §14: the same claim,
    typed vs delivered as a screenshot, must produce the same outcome. The
    only fields allowed to differ are the OCR diagnostics themselves."""
    rig(ml=FakeMlClient(matches=[KB_MATCH], message="pesan balasan"))
    text_result = await orchestrator.process_message_job(job(), {}, SETTINGS)

    rig(ml=FakeMlClient(
        matches=[KB_MATCH],
        message="pesan balasan",
        ocr_result={"text": HOAX_TEXT, "success": True, "language": "ind+eng", "error": None},
    ))
    image_result = await orchestrator.process_message_job(image_job(), {}, SETTINGS_OCR)

    diagnostic_only = {"ocr_used", "ocr_confidence"}
    assert {k: v for k, v in text_result.items() if k not in diagnostic_only} == {
        k: v for k, v in image_result.items() if k not in diagnostic_only
    }
    assert text_result["ocr_used"] is False
    assert image_result["ocr_used"] is True


async def test_ocr_empty_result_never_fabricates_a_claim(rig):
    """No usable text in the image: risk stays UNKNOWN, never HOAX
    (12_Empty_Poor_OCR_Handling)."""
    ml = FakeMlClient(ocr_result={"text": "", "success": False, "language": None, "error": "no_text_detected"})
    state = rig(ml=ml)

    result = await orchestrator.process_message_job(image_job(), {}, SETTINGS_OCR)

    assert result["risk"] == "UNKNOWN"
    assert "ocr_empty_result" in result["degradations"]
    assert result["ocr_used"] is False
    assert ml.rag_calls == []  # nothing to extract a claim from, RAG never ran
    assert state["rows"][0].input_type.value == "TEXT"


async def test_ocr_low_confidence_still_feeds_the_pipeline_but_is_flagged(rig):
    """13_Low_Confidence_OCR: a shaky reading is still real evidence — it must
    not be silently discarded, but it must be visible in the audit trail."""
    ml = FakeMlClient(
        matches=[KB_MATCH],
        ocr_result={"text": HOAX_TEXT, "success": True, "language": "ind+eng", "error": None},
        ocr_confidence=0.2,  # below OCR_MIN_CONFIDENCE (0.50 default)
    )
    rig(ml=ml)

    result = await orchestrator.process_message_job(image_job(), {}, SETTINGS_OCR)

    assert "ocr_low_confidence" in result["degradations"]
    assert result["ocr_used"] is True
    assert result["match_count"] == 1  # the text still ran through RAG


async def test_ocr_service_failure_degrades_and_falls_back_to_the_caption(rig):
    """ml-service unreachable/timed out for OCR: the message must not be
    dropped, and any caption text still gets analysed as plain text."""
    ml = FakeMlClient(ocr_error=MlServiceError("ocr_timeout", "OCR exceeded the configured timeout", retryable=False))
    state = rig(ml=ml)

    result = await orchestrator.process_message_job(
        image_job(text="cek ini dong", media_overrides={"filename": "photo.jpg"}), {}, SETTINGS_OCR
    )

    assert any(item.startswith("ocr_unavailable:ocr_timeout") for item in result["degradations"])
    assert result["ocr_used"] is False
    assert ml.generate_calls[0]["user_text"] == "cek ini dong"
    assert state["rows"][0].input_type.value == "TEXT"


async def test_oversized_image_skips_the_ocr_call_entirely(rig):
    """Cheap, dependency-free rejection at the gateway: no reason to upload
    an obviously oversized file to ml-service first."""
    ml = FakeMlClient()
    rig(ml=ml)
    tiny_limit = Settings(user_hash_salt="test-salt", end_to_end_target_ms=3000, ocr_enabled=True, ocr_max_image_size_mb=0.000001)

    result = await orchestrator.process_message_job(image_job(media_overrides={"filename": "photo.jpg"}), {}, tiny_limit)

    assert ml.ocr_calls == []
    assert "ocr_image_too_large" in result["degradations"]


async def test_image_with_media_url_is_downloaded_then_ocrd(rig):
    """WAHA's other media shape: a URL to fetch rather than inline base64
    bytes — must go through `WahaClient.download_media`, authenticated the
    same way as every other WAHA call."""
    waha = FakeWaha(media_bytes=b"downloaded-jpeg-bytes")
    ml = FakeMlClient(
        matches=[KB_MATCH],
        message="pesan balasan",
        ocr_result={"text": HOAX_TEXT, "success": True, "language": "ind+eng", "error": None},
    )
    rig(ml=ml, waha=waha)

    result = await orchestrator.process_message_job(
        image_job(media_overrides={"filename": "photo.jpg", "url": "https://waha.internal/media/abc", "data": None}),
        {},
        SETTINGS_OCR,
    )

    assert waha.download_media_calls == ["https://waha.internal/media/abc"]
    assert result["ocr_used"] is True
    assert ml.ocr_calls[0]["size"] == len(b"downloaded-jpeg-bytes")


async def test_media_download_failure_degrades_without_crashing(rig):
    waha = FakeWaha(media_bytes=None)  # download fails
    ml = FakeMlClient()
    state = rig(ml=ml, waha=waha)

    result = await orchestrator.process_message_job(
        image_job(media_overrides={"filename": "photo.jpg", "url": "https://waha.internal/media/missing", "data": None}),
        {},
        SETTINGS_OCR,
    )

    assert ml.ocr_calls == []
    assert "ocr_media_unavailable" in result["degradations"]


# --------------------------------------------------------------------------
# Strict command gate (JAWARA Strict WhatsApp Command System)
#
# A group message is only ever analysed via one of four allowlisted `!name`
# commands. Every other case below must return without touching the
# classifier, RAG, URL scanner, OCR or the LLM.
# --------------------------------------------------------------------------


def mentioning(text: str, **overrides) -> MessageJob:
    return group_job(text=text, mentionedIds=["6287712032005@c.us"], **overrides)


@pytest.mark.parametrize(
    "text",
    ["Halo", "Halo JAWARA", "JAWARA tolong cek ini", "Apa kabar?"],
)
async def test_mention_without_a_command_never_reaches_ai(rig, text):
    ml = FakeMlClient(matches=[KB_MATCH])
    state = rig(ml=ml, waha=FakeWaha(bot_ids=BOT_IDS))

    result = await orchestrator.process_message_job(mentioning(text), {}, SETTINGS)

    assert result["status"] == "mention_no_command"
    assert state["waha"].sent[0][1] == orchestrator.MENTION_GUIDANCE_REPLY
    assert ml.generate_calls == []
    assert ml.rag_calls == []
    assert ml.classify_calls == []
    assert ml.ocr_calls == []
    assert state["rows"] == []  # no audit row either — nothing was analysed


@pytest.mark.parametrize("name", ["foo", "search", "ocr", "rag", "factcheck"])
async def test_unrecognised_command_never_reaches_ai(rig, name):
    ml = FakeMlClient(matches=[KB_MATCH])
    state = rig(ml=ml, waha=FakeWaha(bot_ids=BOT_IDS))

    result = await orchestrator.process_message_job(mentioning(f"!{name}"), {}, SETTINGS)

    assert result["status"] == "command_unrecognized"
    assert state["waha"].sent[0][1] == orchestrator.UNKNOWN_COMMAND_REPLY
    assert ml.generate_calls == []
    assert ml.rag_calls == []


async def test_bantu_shows_the_public_command_list_without_touching_ai(rig):
    ml = FakeMlClient(matches=[KB_MATCH])
    state = rig(ml=ml, waha=FakeWaha(bot_ids=BOT_IDS))

    result = await orchestrator.process_message_job(mentioning("!bantu"), {}, SETTINGS)

    assert result["status"] == "command_bantu"
    assert state["waha"].sent[0][1] == orchestrator.HELP_REPLY
    assert ml.generate_calls == []


async def test_status_reports_public_service_state_without_touching_ai(rig, monkeypatch):
    ml = FakeMlClient(matches=[KB_MATCH])
    waha = FakeWaha(bot_ids=BOT_IDS)
    state = rig(ml=ml, waha=waha)

    async def fake_check_waha(settings):
        return True

    monkeypatch.setattr(orchestrator, "check_waha", fake_check_waha)

    result = await orchestrator.process_message_job(mentioning("!status"), {}, SETTINGS)

    assert result["status"] == "command_status"
    assert "Online" in state["waha"].sent[0][1]
    assert "Redis" not in state["waha"].sent[0][1]
    assert "Qdrant" not in state["waha"].sent[0][1]
    assert ml.generate_calls == []


@pytest.mark.parametrize("text", ["!CEK", "!Cek", "!LINK https://example.com"])
async def test_command_name_case_is_normalised(rig, text):
    scan = UrlScanResult(risk=RiskLevel.LOW)
    ml = FakeMlClient(matches=[])
    state = rig(ml=ml, waha=FakeWaha(bot_ids=BOT_IDS), url_scan=scan)

    result = await orchestrator.process_message_job(mentioning(text), {}, SETTINGS)

    assert result["status"] != "command_unrecognized"
    assert result["status"] != "mention_no_command"


async def test_cek_without_reply_text_or_media_returns_usage_error(rig):
    ml = FakeMlClient(matches=[KB_MATCH])
    state = rig(ml=ml, waha=FakeWaha(bot_ids=BOT_IDS))

    result = await orchestrator.process_message_job(mentioning("!cek"), {}, SETTINGS)

    assert result["status"] == "command_cek_usage_error"
    assert state["waha"].sent[0][1] == orchestrator.CEK_USAGE_REPLY
    assert ml.generate_calls == []
    assert ml.rag_calls == []


async def test_link_without_a_url_returns_usage_error(rig):
    ml = FakeMlClient()
    state = rig(ml=ml, waha=FakeWaha(bot_ids=BOT_IDS))

    result = await orchestrator.process_message_job(mentioning("!link"), {}, SETTINGS)

    assert result["status"] == "command_link_usage_error"
    assert state["waha"].sent[0][1] == orchestrator.LINK_USAGE_REPLY
    assert ml.generate_calls == []


async def test_link_with_a_url_routes_only_to_url_safety(rig):
    """!link must never fall through to claim extraction or RAG — only the
    URL-safety engine the command explicitly asked for."""
    scan = UrlScanResult(
        risk=RiskLevel.HIGH,
        urls=(
            UrlRisk(
                url="https://bansos-pemerintah-2026.com",
                domain="bansos-pemerintah-2026.com",
                is_shortlink=False,
                risk=RiskLevel.HIGH,
                reason="flagged_by=safe_browsing",
            ),
        ),
    )
    ml = FakeMlClient(matches=[KB_MATCH])  # would prove RAG ran, if it did
    state = rig(ml=ml, waha=FakeWaha(bot_ids=BOT_IDS), url_scan=scan)

    result = await orchestrator.process_message_job(
        mentioning("!link https://bansos-pemerintah-2026.com"), {}, SETTINGS
    )

    assert result["status"] == "processed"
    assert result["engine"] == "url_safety"
    assert result["risk"] == "HIGH"
    assert ml.rag_calls == []
    assert ml.claim_calls == []
    assert ml.generate_calls[0]["url_verdicts"][0]["risk"] == "HIGH"


async def test_inline_cek_text_is_checked_directly(rig):
    ml = FakeMlClient(matches=[KB_MATCH], message="pesan balasan")
    state = rig(ml=ml, waha=FakeWaha(bot_ids=BOT_IDS))

    result = await orchestrator.process_message_job(mentioning(f"!cek {HOAX_TEXT}"), {}, SETTINGS)

    assert result["status"] == "processed"
    assert ml.generate_calls[0]["user_text"] == HOAX_TEXT
    assert state["waha"].sent[0][1] == "pesan balasan"
    assert result["ocr_used"] is False
    assert state["rows"][0].input_type.value == "TEXT"


async def test_image_with_cek_command_uses_the_existing_ocr_flow(rig):
    """Image + '@JAWARA !cek', no caption text of its own — the user does not
    need a separate `!ocr` command; `!cek` reuses the existing OCR pipeline."""
    ml = FakeMlClient(
        matches=[KB_MATCH],
        message="pesan balasan",
        ocr_result={"text": HOAX_TEXT, "success": True, "language": "ind+eng", "error": None},
    )
    state = rig(ml=ml, waha=FakeWaha(bot_ids=BOT_IDS))

    result = await orchestrator.process_message_job(
        image_job(
            text="@6287712032005 !cek",
            **{"from": GROUP_ID, "id": "x1", "participant": "628999@c.us", "mentionedIds": ["6287712032005@c.us"]},
        ),
        {},
        SETTINGS_OCR,
    )

    assert result["status"] == "processed"
    assert result["ocr_used"] is True
    assert ml.generate_calls[0]["user_text"] == HOAX_TEXT
    assert state["rows"][0].input_type.value == "IMAGE_OCR"


# --------------------------------------------------------------------------
# Reply-to-media resolution: "@JAWARA !cek <question>" replying to SOMEONE
# ELSE'S image must read the replied image, not just the question text next
# to it (the bug where JAWARA answered "I can't see the image").
# --------------------------------------------------------------------------


async def test_reply_to_image_is_ocrd_using_the_replied_message_not_the_current_one(rig):
    ml = FakeMlClient(
        matches=[KB_MATCH],
        message="pesan balasan",
        ocr_result={"text": HOAX_TEXT, "success": True, "language": "ind+eng", "error": None},
    )
    waha = FakeWaha(
        bot_ids=BOT_IDS,
        quoted_media={"mimetype": "image/jpeg", "url": "http://waha:3000/api/files/abc.jpg"},
        media_bytes=b"fake-jpeg-bytes",
    )
    state = rig(ml=ml, waha=waha)

    result = await orchestrator.process_message_job(
        mentioning("!cek apakah informasi di gambar itu benar?", replyTo={"id": "orig-msg-1"}),
        {},
        SETTINGS_OCR,
    )

    assert result["status"] == "processed"
    assert result["ocr_used"] is True
    assert state["rows"][0].input_type.value == "IMAGE_OCR"
    # Both preserved: the OCR'd content of the image AND the user's own
    # question — one must never silently replace the other (§12).
    checked = ml.generate_calls[0]["user_text"]
    assert HOAX_TEXT in checked
    assert "apakah informasi di gambar itu benar?" in checked
    assert waha.download_media_calls == ["http://waha:3000/api/files/abc.jpg"]


async def test_reply_to_image_with_inline_reply_to_never_calls_waha_get_message(rig):
    """Production incident: on this WAHA build `replyTo` already carries the
    full quoted message inline (`body`, `media.url`), and
    `GET .../messages/{id}` 500s unconditionally regardless of id shape —
    every `!cek` on a reply-to-image usage-errored until the inline path
    existed. With the content already inline, WAHA must never be asked to
    fetch the message at all."""
    ml = FakeMlClient(
        matches=[KB_MATCH],
        message="pesan balasan",
        ocr_result={"text": HOAX_TEXT, "success": True, "language": "ind+eng", "error": None},
    )
    waha = FakeWaha(bot_ids=BOT_IDS, media_bytes=b"fake-jpeg-bytes")
    state = rig(ml=ml, waha=waha)

    result = await orchestrator.process_message_job(
        mentioning(
            "!cek",
            replyTo={
                "id": "3EB0DAF7516034EE5BE090",
                "participant": "99669027872892@lid",
                "body": "apakah ini nyata",
                "hasMedia": True,
                "media": {"mimetype": "image/jpeg", "url": "http://waha:3000/api/files/abc.jpg"},
            },
        ),
        {},
        SETTINGS_OCR,
    )

    assert result["status"] == "processed"
    assert result["ocr_used"] is True
    assert waha.get_message_calls == []
    assert waha.download_media_calls == ["http://waha:3000/api/files/abc.jpg"]


async def test_reply_to_image_falls_back_to_download_media_when_no_inline_reference(rig):
    """`replyTo.hasMedia: true` but no inline `media.url`/`media.data` on the
    first fetch — must retry with `?downloadMedia=true` rather than give up."""
    ml = FakeMlClient(
        matches=[KB_MATCH],
        message="pesan balasan",
        ocr_result={"text": HOAX_TEXT, "success": True, "language": "ind+eng", "error": None},
    )
    waha = FakeWaha(
        bot_ids=BOT_IDS,
        quoted_has_media=True,
        quoted_media_after_download={"mimetype": "image/jpeg", "data": "ZmFrZS1qcGVn"},
    )
    state = rig(ml=ml, waha=waha)

    result = await orchestrator.process_message_job(
        mentioning("!cek", replyTo={"id": "orig-msg-1"}), {}, SETTINGS_OCR
    )

    assert result["status"] == "processed"
    assert result["ocr_used"] is True
    assert state["rows"][0].input_type.value == "IMAGE_OCR"
    assert [c["download_media"] for c in waha.get_message_calls] == [False, True]


async def test_reply_to_image_still_unresolvable_after_fallback_is_a_safe_degradation(rig):
    """No usable image even after the fallback fetch: `!cek` must still end
    in a response (falls through to 'nothing to check'), never a crash or
    silence."""
    ml = FakeMlClient(matches=[])
    waha = FakeWaha(bot_ids=BOT_IDS, quoted_has_media=True)
    state = rig(ml=ml, waha=waha)

    result = await orchestrator.process_message_job(
        mentioning("!cek", replyTo={"id": "orig-msg-1"}), {}, SETTINGS_OCR
    )

    assert result["status"] == "command_cek_usage_error"
    assert "reply_media_unavailable" in result["degradations"]
    assert state["waha"].sent[0][1] == orchestrator.CEK_USAGE_REPLY


async def test_reply_to_link_via_cek_still_routes_to_url_safety(rig):
    """`!cek` on a reply containing a URL must not force the user to
    `!link` — the existing auto-routing already handles it (§13)."""
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
    waha = FakeWaha(bot_ids=BOT_IDS, quoted_text=PHISHING_TEXT)
    state = rig(url_scan=scan, waha=waha)

    result = await orchestrator.process_message_job(
        mentioning("!cek", replyTo={"id": "orig-msg-1"}), {}, SETTINGS
    )

    assert result["status"] == "processed"
    assert result["engine"] == "url_safety"
    assert result["risk"] == "HIGH"
