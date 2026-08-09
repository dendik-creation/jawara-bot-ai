"""End-to-end orchestration of one WhatsApp message.

Stages 4–12 of 02_Architecture/02_Data_Pipeline.md, in order:

    normalise → extract indicators → classify (rules, ML when available)
    → verify (RAG or URL reputation) → risk assessment → policy
    → generate reply → dispatch via WAHA → audit row

The worker owns the *ordering*; each stage owns its logic. Every stage is
allowed to degrade: a missing ML Service falls back to rules-only, a missing
threat-intel key produces `UNKNOWN` instead of an exception, an undeliverable
reply still leaves an audit row. The one thing the pipeline never does is claim
more certainty than it has — `UNKNOWN` never renders as "safe".
"""

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import redis.asyncio as aioredis

from app.clients.ml_client import MlClient, MlServiceError
from app.clients.waha_client import WahaClient
from app.core.config import Settings, get_settings
from app.core.hashing import hash_user_identifier
from app.pipeline import group_policy, intent_router
from app.pipeline.categories import Category, InputType, RiskLevel, Verdict, worst_risk
from app.pipeline.normalizer import normalize_text
from app.pipeline.url_extractor import extract_urls
from app.pipeline.url_safety import UrlScanResult, scan_urls
from app.schemas.queue import MessageJob
from app.services.message_log import MessageLogEntry, chat_type_for, record_message

logger = logging.getLogger("app.pipeline.orchestrator")

# Events that carry a user message. `session.status` and friends arrive on the
# same webhook and must not be run through detection.
MESSAGE_EVENTS = frozenset({"message", "message.any"})

# Answer to a bare mention. Fixed text, not LLM-generated: there is nothing to
# analyse, and a generated reply to an empty prompt is where a chatbot starts
# making things up.
EMPTY_MENTION_REPLY = (
    "Halo! 👋 Saya JAWARA, asisten pemeriksa hoaks dan penipuan.\n\n"
    "Silakan sebut saya sambil menyertakan pesannya, misalnya:\n"
    "• Balas (reply) pesan yang mencurigakan, lalu sebut saya\n"
    "• Atau tulis: @JAWARA tolong cek kabar ini ...\n\n"
    "Saya bisa memeriksa klaim kesehatan, link mencurigakan, dan file APK."
)

# A knowledge-base verdict is a statement about the claim, so it maps directly
# onto risk. UNVERIFIED is MEDIUM, never LOW: "no one has checked this" is not
# reassurance.
VERDICT_RISK: dict[str, RiskLevel] = {
    Verdict.HOAX.value: RiskLevel.HIGH,
    Verdict.MISLEADING.value: RiskLevel.MEDIUM,
    Verdict.UNVERIFIED.value: RiskLevel.MEDIUM,
    Verdict.FACT.value: RiskLevel.LOW,
}


@dataclass
class PipelineOutcome:
    """What happened to one message, in the shape the log and the caller want."""

    status: str = "processed"
    intent: str = "UNKNOWN"
    intent_confidence: float = 0.0
    engine: str = intent_router.ENGINE_NONE
    risk: str = RiskLevel.UNKNOWN.value
    url_count: int = 0
    match_count: int = 0
    similarity_score: float | None = None
    matched_fact_id: str | None = None
    response_dispatched: bool = False
    response_latency_ms: int | None = None
    logged: bool = False
    degradations: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "intent": self.intent,
            "intent_confidence": round(self.intent_confidence, 3),
            "engine": self.engine,
            "risk": self.risk,
            "url_count": self.url_count,
            "match_count": self.match_count,
            "similarity_score": self.similarity_score,
            "response_dispatched": self.response_dispatched,
            "response_latency_ms": self.response_latency_ms,
            "logged": self.logged,
            "degradations": self.degradations,
        }


def _payload_of(message: MessageJob) -> dict[str, Any]:
    payload = message.event.get("payload")
    return payload if isinstance(payload, dict) else {}


def _attachment_names(payload: dict[str, Any]) -> list[str]:
    """Filenames WAHA reports for an attachment, across engine payload shapes."""
    names: list[str] = []
    for key in ("filename", "fileName"):
        value = payload.get(key)
        if isinstance(value, str):
            names.append(value)
    media = payload.get("media")
    if isinstance(media, dict):
        for key in ("filename", "fileName"):
            value = media.get(key)
            if isinstance(value, str):
                names.append(value)
    return names


def _input_type(urls_found: int, apk: bool) -> InputType:
    if apk:
        return InputType.FILE_APK
    if urls_found:
        return InputType.URL_LINK
    return InputType.TEXT


def _elapsed_ms(received_at: datetime) -> int:
    return max(0, int((datetime.now(timezone.utc) - received_at).total_seconds() * 1000))


async def process_message_job(
    message: MessageJob,
    log_context: dict[str, Any],
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Run one queued message through the whole pipeline."""
    settings = settings or get_settings()
    outcome = PipelineOutcome()
    started = time.perf_counter()

    if message.event_name not in MESSAGE_EVENTS:
        outcome.status = "ignored_non_message_event"
        return outcome.as_dict()

    payload = _payload_of(message)
    if payload.get("fromMe") is True:
        # Our own outbound reply comes back as an event; analysing it would put
        # the bot in a loop with itself.
        outcome.status = "ignored_own_message"
        return outcome.as_dict()

    chat_id = message.chat_id or payload.get("from")
    if not chat_id:
        outcome.status = "ignored_missing_chat_id"
        return outcome.as_dict()

    body = payload.get("body") or payload.get("caption") or ""
    attachments = _attachment_names(payload)
    if not body.strip() and not attachments:
        outcome.status = "ignored_empty_body"
        return outcome.as_dict()

    # --- stage 3b: may the bot speak here? -------------------------------
    # Decided before any analysis, deliberately. A group message the bot was not
    # addressed in costs no ML call, and — more importantly — leaves no
    # `extracted_text` row: the system reads what it is asked to read, not
    # everything said in the room.
    bot_ids = (
        await WahaClient(settings).session_identity(message.session)
        if group_policy.is_group_chat(chat_id)
        else frozenset()
    )
    decision = group_policy.decide(
        payload,
        chat_id,
        body,
        bot_ids=bot_ids,
        require_trigger=settings.group_reply_requires_trigger,
    )
    if not decision.should_reply:
        logger.info(
            "group message not addressed to the bot, skipped",
            extra={**log_context, "reason": decision.reason},
        )
        outcome.status = "ignored_group_not_addressed"
        return outcome.as_dict()

    if decision.is_group:
        body = group_policy.strip_bot_mentions(body, bot_ids)
        if not body.strip() and not attachments:
            # "@JAWARA" and nothing else: called, but given nothing to check.
            # Silence would read as a broken bot, so say what it needs — and say
            # it as a quote of the summons, so the group sees who asked.
            send = await WahaClient(settings).send_text(
                chat_id, EMPTY_MENTION_REPLY, session=message.session, reply_to=message.waha_message_id
            )
            outcome.status = "mention_without_content"
            outcome.response_dispatched = send.delivered
            return outcome.as_dict()

    # --- stage 4: preprocessing ------------------------------------------
    normalized = normalize_text(body)
    urls = extract_urls(body)
    outcome.url_count = len(urls)
    has_apk = any(name.lower().endswith(".apk") for name in attachments)

    # --- stage 5a: deterministic detection rules --------------------------
    intent = intent_router.classify(
        normalized.text,
        urls=urls,
        attachment_names=attachments,
    )
    outcome.intent = intent.category.value if intent.category else "UNKNOWN"
    outcome.intent_confidence = intent.confidence
    outcome.engine = intent.engine

    redis = aioredis.from_url(settings.redis_url, socket_connect_timeout=2, decode_responses=True)
    ml = MlClient(settings)
    request_id = message.waha_message_id or f"{message.session}:{chat_id}"

    matches: list[dict[str, Any]] = []
    url_scan: UrlScanResult | None = None
    risk_signals: list[RiskLevel] = []

    try:
        # --- stage 5b/6: verification ------------------------------------
        if intent.engine == intent_router.ENGINE_URL_SAFETY and urls:
            url_scan = await scan_urls(urls, redis=redis, settings=settings)
            risk_signals.append(url_scan.risk)
            if url_scan.degraded:
                outcome.degradations.append("url_intel_unavailable")

        elif intent.engine == intent_router.ENGINE_TEXT_VERIFICATION:
            try:
                response = await ml.rag_query(
                    request_id,
                    query=normalized.text,
                    category=intent.category.value if intent.category else None,
                )
                matches = list(response.result.get("matches") or [])
            except MlServiceError as exc:
                outcome.degradations.append(f"ml_unavailable:{exc.error_code}")
            if matches:
                top = matches[0]
                outcome.match_count = len(matches)
                outcome.similarity_score = float(top.get("score", 0.0))
                outcome.matched_fact_id = top.get("fact_item_id")
                risk_signals.append(VERDICT_RISK.get(str(top.get("verdict")), RiskLevel.MEDIUM))
            else:
                # Nothing above the similarity threshold: explicitly unverified,
                # never "closest weak match wins".
                risk_signals.append(RiskLevel.MEDIUM)
                outcome.degradations.append("knowledge_unverified")

        elif intent.engine == intent_router.ENGINE_APK_WARNING:
            # MVP recognises the attachment and warns. Static analysis of the APK
            # is Optional/Future (06_Optional_APK_Inspector).
            risk_signals.append(RiskLevel.HIGH if has_apk else RiskLevel.MEDIUM)

        elif intent.engine == intent_router.ENGINE_UNSUPPORTED:
            outcome.degradations.append(f"engine_unsupported:{outcome.intent}")

        # A dangerous link inside an otherwise text-shaped message still counts.
        if url_scan is None and urls and intent.engine != intent_router.ENGINE_URL_SAFETY:
            url_scan = await scan_urls(urls, redis=redis, settings=settings)
            risk_signals.append(url_scan.risk)

        # --- stage 7: risk assessment ------------------------------------
        risk = worst_risk(*risk_signals) if risk_signals else RiskLevel.UNKNOWN
        outcome.risk = risk.value

        # --- stage 8/9: policy + action ----------------------------------
        # MVP policy: the system is consent-based — the user asked, so the user
        # gets an answer. Graded ALLOW/WARN/BLOCK/ESCALATE actions arrive with
        # the Security Policy engine (02_Security_Policies, Planned).
        reply_text = ""
        try:
            generated = await ml.generate(
                request_id,
                user_text=normalized.raw,
                category=intent.category.value if intent.category else None,
                risk_level=risk.value,
                context=matches,
                url_verdicts=[item.as_dict() for item in (url_scan.urls if url_scan else ())],
            )
            reply_text = str(generated.result.get("message") or "")
            if generated.result.get("fallback_used"):
                outcome.degradations.append(
                    f"llm_fallback:{generated.result.get('fallback_reason', 'unknown')}"
                )
        except MlServiceError as exc:
            outcome.degradations.append(f"generation_unavailable:{exc.error_code}")

        # --- stage 11: dispatch ------------------------------------------
        if reply_text:
            # Quote the message that summoned the bot, but only in groups: in a
            # one-to-one chat there is nothing to disambiguate, and the quote
            # would just add clutter.
            send = await WahaClient(settings).send_text(
                chat_id,
                reply_text,
                session=message.session,
                reply_to=message.waha_message_id if decision.is_group else None,
            )
            outcome.response_dispatched = send.delivered
            if not send.delivered:
                outcome.degradations.append(f"dispatch_failed:{send.error}")

        outcome.response_latency_ms = _elapsed_ms(message.received_at)
        if outcome.response_latency_ms > settings.end_to_end_target_ms:
            logger.warning(
                "end-to-end latency over target",
                extra={
                    **log_context,
                    "response_latency_ms": outcome.response_latency_ms,
                    "target_ms": settings.end_to_end_target_ms,
                },
            )

        # --- stage 10: audit row -----------------------------------------
        outcome.logged = await _write_audit_row(
            message=message,
            chat_id=chat_id,
            normalized_raw=normalized.raw,
            intent_category=intent.category,
            risk=risk,
            outcome=outcome,
            has_apk=has_apk,
            settings=settings,
        )
    finally:
        await redis.aclose()

    logger.info(
        "pipeline complete",
        extra={
            **log_context,
            **outcome.as_dict(),
            "worker_ms": int((time.perf_counter() - started) * 1000),
        },
    )
    return outcome.as_dict()


async def _write_audit_row(
    message: MessageJob,
    chat_id: str,
    normalized_raw: str,
    intent_category: Category | None,
    risk: RiskLevel,
    outcome: PipelineOutcome,
    has_apk: bool,
    settings: Settings,
) -> bool:
    """Persist the audit row. A logging failure must not lose the reply already sent."""
    if not message.waha_message_id:
        outcome.degradations.append("audit_skipped_no_message_id")
        return False

    entry = MessageLogEntry(
        waha_message_id=message.waha_message_id,
        waha_session_id=message.session,
        user_hash=hash_user_identifier(chat_id, settings),
        chat_type=chat_type_for(chat_id),
        input_type=_input_type(outcome.url_count, has_apk),
        extracted_text=normalized_raw,
        detected_intent=intent_category,
        risk_score=risk,
        matched_fact_id=outcome.matched_fact_id,
        similarity_score=outcome.similarity_score,
        response_latency_ms=outcome.response_latency_ms,
    )

    try:
        return await record_message(entry, settings)
    except Exception:  # noqa: BLE001
        logger.error(
            "audit row write failed",
            extra={"waha_message_id": message.waha_message_id},
            exc_info=True,
        )
        outcome.degradations.append("audit_write_failed")
        return False
