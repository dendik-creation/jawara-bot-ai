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
from app.pipeline import commands, group_policy, input_resolver, intent_router
from app.pipeline.categories import Category, InputType, RiskLevel, Verdict, worst_risk
from app.pipeline.media import ImageAttachment, attachment_names, image_attachment_of
from app.pipeline.normalizer import normalize_text
from app.pipeline.url_extractor import extract_urls
from app.pipeline.url_safety import UrlScanResult, scan_urls
from app.schemas.queue import MessageJob
from app.services.health import check_waha
from app.services.message_log import MessageLogEntry, chat_type_for, record_message
from app.services.model_versions import get_production_model

logger = logging.getLogger("app.pipeline.orchestrator")

# Events that carry a user message. `session.status` and friends arrive on the
# same webhook and must not be run through detection.
MESSAGE_EVENTS = frozenset({"message", "message.any"})

# Fixed, non-LLM replies for the strict command gate (JAWARA Strict WhatsApp
# Command System §§6-9, 14). Every one of these is a static string precisely
# because the whole point of the gate is that no AI call happens before a
# recognised command has been identified.

# `@JAWARA` mentioned with no `!command` at all — a greeting, small talk, or
# natural language that only *sounds* like a request ("tolong cek ini"). This
# doubles as JAWARA's introduction: there is no separate first-interaction
# state to track, so every bare mention gets the same informative overview
# rather than a one-line reminder — `!bantu` is where the deeper, step-by-step
# guide lives (see HELP_REPLY).
MENTION_GUIDANCE_REPLY = (
    "Halo! Saya JAWARA — asisten pemeriksa informasi dan ancaman di WhatsApp.\n\n"
    "Saya dapat membantu memeriksa:\n"
    "• Klaim atau berita yang meragukan\n"
    "• Informasi dari gambar/screenshot\n"
    "• Link yang mencurigakan\n\n"
    "Cara menggunakan:\n"
    "• Reply pesan yang ingin diperiksa, lalu tulis @JAWARA !cek\n"
    "• Kirim teks langsung dengan @JAWARA !cek <pesan>\n"
    "• Periksa link dengan @JAWARA !link <URL>\n\n"
    "Command:\n"
    "• !cek — periksa pesan, klaim, atau gambar\n"
    "• !link — analisis link\n"
    "• !bantu — panduan lengkap\n"
    "• !status — status layanan\n\n"
    "Contoh:\n"
    "Reply gambar → @JAWARA !cek\n"
    "@JAWARA !cek Apakah informasi ini benar?\n\n"
    "Catatan: mention tanpa command tidak akan menjalankan pemeriksaan."
)

# `!something` where `something` is not in commands.KNOWN_COMMANDS.
UNKNOWN_COMMAND_REPLY = (
    "Command tidak dikenali.\n\n"
    "Gunakan @JAWARA !bantu untuk melihat command yang tersedia."
)

# `!bantu` — the complete guide MENTION_GUIDANCE_REPLY only summarises.
# Explicitly spells out reply-to-text and reply-to-image usage (§1-2): the
# whole point is that users stop manually forwarding images and just reply.
HELP_REPLY = (
    "JAWARA — Panduan Penggunaan\n\n"
    "JAWARA dapat membantu memeriksa informasi yang Anda temukan di WhatsApp. "
    "Pemeriksaan hanya berjalan jika Anda memakai command — mention saja tidak cukup.\n\n"
    "1. Periksa pesan\n"
    "Reply pesan yang ingin diperiksa, lalu:\n"
    "@JAWARA !cek\n\n"
    "2. Periksa gambar\n"
    "Reply gambar/screenshot, lalu:\n"
    "@JAWARA !cek\n"
    "JAWARA akan membaca informasi dalam gambar tersebut sebelum melakukan pemeriksaan.\n\n"
    "3. Periksa teks\n"
    "@JAWARA !cek <teks>\n\n"
    "Contoh:\n"
    "@JAWARA !cek Apakah benar pemerintah mengumumkan informasi ini?\n\n"
    "4. Periksa link\n"
    "@JAWARA !link <URL>\n\n"
    "Contoh:\n"
    "@JAWARA !link https://example.com\n\n"
    "5. Status layanan\n"
    "@JAWARA !status\n\n"
    "Command:\n"
    "!cek     Periksa pesan, klaim, atau gambar\n"
    "!link    Periksa link\n"
    "!bantu   Tampilkan panduan ini\n"
    "!status  Lihat status layanan\n\n"
    "Penting: mention seperti \"@JAWARA Halo\" tidak akan menjalankan pemeriksaan. "
    "Gunakan command di atas."
)

# `!cek` with no reply, no inline text, and no media to read.
CEK_USAGE_REPLY = (
    "Format:\n"
    "@JAWARA !cek\n\n"
    "Gunakan command ini dengan:\n"
    "• reply pesan yang ingin diperiksa\n"
    "• teks setelah !cek\n"
    "• gambar/media yang ingin diperiksa"
)

# `!link` with no URL in its argument or in the replied-to message.
LINK_USAGE_REPLY = (
    "Format:\n"
    "@JAWARA !link <URL>\n\n"
    "Contoh:\n"
    "@JAWARA !link https://example.com"
)

# ml-service's `/v1/generate` is a single, unretried call from here — its own
# service already falls back internally (template composer) when its *own*
# provider fails, so an `MlServiceError` reaching this pipeline means the
# request never got a response at all (timeout, connection refused, 5xx).
# Leaving `reply_text` empty in that case would end the pipeline with
# `status: processed` but nothing ever sent to WAHA — a silent failure the
# task-level retry net in `app.worker.tasks` cannot catch, because no
# exception propagates past the `except MlServiceError` below. This is the
# same "every explicit command ends in a response, never nothing" guarantee
# 4d2cc1d added at the task level, applied at the one stage that can hit this
# without the task itself raising.
GENERATION_UNAVAILABLE_REPLY = (
    "Maaf, JAWARA sedang mengalami kendala saat menyusun jawaban.\n\n"
    "Silakan coba lagi beberapa saat lagi."
)


async def _status_reply(settings: Settings) -> str:
    """`!status` (JAWARA Strict WhatsApp Command System §7).

    Public-safe by construction: it reuses the same WAHA reachability probe
    `GET /health` already runs, and reports only the three user-facing lines
    the spec asks for — never subsystem names like Redis, Celery or Qdrant.
    """
    online = await check_waha(settings)
    layanan = "Online" if online else "Gangguan"
    return (
        "JAWARA STATUS\n\n"
        f"● Layanan: {layanan}\n"
        "● Pemeriksaan informasi: Aktif\n"
        "● Pemeriksaan link: Aktif\n"
        "● Pemeriksaan gambar: Aktif"
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

# The ML classifier's own view of risk per predicted category. Additive only —
# folded into `risk_signals` alongside the rules engine's own signal, and
# `worst_risk()` takes the max, so this can only ever push risk up, never
# suppress a HIGH the rules engine already found. `NOT_A_THREAT` (a real
# negative class the DB-locked `Category` enum can't represent — see
# `app.services.datasets`) contributes no elevated risk.
#
# `PHISHING_LINK` is deliberately absent: unlike the other categories, a link's
# risk already has its own deterministic, evidence-based verdict from
# `scan_urls` (Safe Browsing + VirusTotal + Knowledge Base trust). A blanket
# "every message the classifier calls PHISHING_LINK is HIGH" signal here would
# outrank that verdict via `worst_risk()` and force a legitimate URL (e.g. a
# news article link the classifier mis-reads from a bare-URL `!link` body) to
# HIGH regardless of what the URL engine actually found — the same
# LLM-cannot-override-deterministic-risk bug this pipeline was fixed against,
# just from the classifier stage instead of the reply-generation stage.
CATEGORY_RISK: dict[str, RiskLevel] = {
    Category.HEALTH_HOAX.value: RiskLevel.MEDIUM,
    Category.FINANCIAL_FRAUD.value: RiskLevel.HIGH,
    Category.GENERAL_NEWS.value: RiskLevel.LOW,
    Category.FILE_APK.value: RiskLevel.HIGH,
    "NOT_A_THREAT": RiskLevel.LOW,
}

# In-process cache for "which model_version is PRODUCTION" — promotion is a
# rare, explicit human action (07_Model_Registry_and_Deployment §3-4), so a
# DB round-trip per message is pure waste. Short TTL, not a long one: a
# rollback/promotion should take effect for new messages within seconds, not
# ride out a full worker restart.
_PRODUCTION_MODEL_CACHE_TTL_SECONDS = 30.0
_production_model_cache: dict[str, Any] = {"value": None, "checked_at": 0.0}


async def _cached_production_model(settings: Settings) -> dict[str, str] | None:
    now = time.monotonic()
    if now - _production_model_cache["checked_at"] < _PRODUCTION_MODEL_CACHE_TTL_SECONDS:
        return _production_model_cache["value"]
    value = await get_production_model(settings)
    _production_model_cache["value"] = value
    _production_model_cache["checked_at"] = now
    return value


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
    # How the retrieval query was produced ("llm", "heuristic", "passthrough")
    # and whether ml-service re-ranked what came back. Both are diagnostics for
    # "why did retrieval match this" — logged, not stored on the audit row,
    # whose columns are fixed by 03_Database/01_PostgreSQL_Schema.md.
    claim_method: str | None = None
    reranked: bool = False
    ml_category: str | None = None
    ml_confidence: float | None = None
    # Diagnostics for "did this message start as a picture" — logged, not
    # persisted (17_Database: no new column unless one earns its keep;
    # `input_type=IMAGE_OCR` on the audit row already records the modality).
    ocr_used: bool = False
    ocr_confidence: float | None = None
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
            "claim_method": self.claim_method,
            "reranked": self.reranked,
            "ml_category": self.ml_category,
            "ml_confidence": self.ml_confidence,
            "ocr_used": self.ocr_used,
            "ocr_confidence": self.ocr_confidence,
            "response_dispatched": self.response_dispatched,
            "response_latency_ms": self.response_latency_ms,
            "logged": self.logged,
            "degradations": self.degradations,
        }


def _payload_of(message: MessageJob) -> dict[str, Any]:
    payload = message.event.get("payload")
    return payload if isinstance(payload, dict) else {}


def _input_type(urls_found: int, apk: bool, image_ocr: bool = False) -> InputType:
    if apk:
        return InputType.FILE_APK
    if image_ocr:
        return InputType.IMAGE_OCR
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
    attachments = attachment_names(payload)
    quoted_id = group_policy.quoted_message_id(payload, chat_id)
    image_attachment = image_attachment_of(payload)
    if not body.strip() and not attachments and not quoted_id and not image_attachment:
        outcome.status = "ignored_empty_body"
        return outcome.as_dict()

    ml = MlClient(settings)
    request_id = message.waha_message_id or f"{message.session}:{chat_id}"

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

    # --- strict command gate (JAWARA Strict WhatsApp Command System) ------
    # Mention = activation, command = intent: a group mention only ever
    # reaches OCR/RAG/URL-scanning/the LLM by way of one of the four
    # allowlisted `!name` commands. A bare mention, a greeting, an
    # unrecognised `!name`, or natural language that only sounds like a
    # request all get a fixed reply and return here — before a single
    # expensive call is made. `!bantu` and `!status` are answered outright;
    # `!cek` and `!link` fall through, with `body` replaced by the command's
    # own argument text, to the same pipeline a direct chat already uses.
    # A direct chat never goes through this gate (unchanged behaviour: the
    # user opened the chat, so there is no casual-mention problem to guard
    # against there).
    parsed_command: commands.ParsedCommand | None = None
    if decision.is_group:
        parsed_command = commands.parse_command(body)
        logger.info(
            "jawara.command.received",
            extra={
                **log_context,
                "has_reply": bool(decision.quoted_message_id),
                "has_media": bool(image_attachment),
                # Diagnostic only, no message content: which top-level and
                # `_data` keys this webhook actually carried. WAHA's payload
                # shape drifts across engines/versions and `quoted_message_id`
                # reads a fixed set of spellings (`replyTo`, `quotedStanzaID`,
                # `quotedMsgId`) — when a real WhatsApp reply still resolves
                # `has_reply: false`, this is what tells us which new spelling
                # to add, instead of guessing blind.
                "payload_keys": sorted(payload.keys()),
                "data_keys": group_policy.data_keys_of(payload),
                # `replyTo`/`quotedStanzaID` carry only ids, jids and a
                # boolean — never message content — so logging them verbatim
                # is safe and is what pins down WAHA's actual reply-quote
                # shape when `quoted_message_id()`'s composite-id
                # reconstruction still needs adjusting for this WAHA build.
                "reply_to_raw": payload.get("replyTo"),
                "resolved_quoted_id": decision.quoted_message_id,
            },
        )

        if parsed_command.command is None:
            logger.info("jawara.command.rejected", extra={**log_context, "command": "none"})
            send = await WahaClient(settings).send_text(
                chat_id, MENTION_GUIDANCE_REPLY, session=message.session, reply_to=message.waha_message_id
            )
            outcome.status = "mention_no_command"
            outcome.response_dispatched = send.delivered
            return outcome.as_dict()

        if not parsed_command.recognized:
            logger.info(
                "jawara.command.rejected", extra={**log_context, "command": parsed_command.command}
            )
            send = await WahaClient(settings).send_text(
                chat_id, UNKNOWN_COMMAND_REPLY, session=message.session, reply_to=message.waha_message_id
            )
            outcome.status = "command_unrecognized"
            outcome.response_dispatched = send.delivered
            return outcome.as_dict()

        logger.info("jawara.command.recognized", extra={**log_context, "command": parsed_command.command})

        if parsed_command.command == commands.BANTU:
            send = await WahaClient(settings).send_text(
                chat_id, HELP_REPLY, session=message.session, reply_to=message.waha_message_id
            )
            outcome.status = "command_bantu"
            outcome.response_dispatched = send.delivered
            logger.info("jawara.command.executed", extra={**log_context, "command": "bantu"})
            return outcome.as_dict()

        if parsed_command.command == commands.STATUS:
            send = await WahaClient(settings).send_text(
                chat_id, await _status_reply(settings), session=message.session, reply_to=message.waha_message_id
            )
            outcome.status = "command_status"
            outcome.response_dispatched = send.delivered
            logger.info("jawara.command.executed", extra={**log_context, "command": "status"})
            return outcome.as_dict()

        # !cek and !link: the command word itself is not content.
        body = parsed_command.args

    # A reply carries its own new text (often empty — "@JAWARA !cek" alone on
    # a reply) plus a pointer to the message being asked about. The pointer
    # is what must actually be checked, so it is fetched and folded in before
    # anything downstream reads `body` — a bare "!cek" on a reply is a
    # complete request, not an empty one.
    quoted_image: ImageAttachment | None = None
    if decision.quoted_message_id:
        reply_to_inline = payload.get("replyTo")
        resolved_quote = await input_resolver.resolve_quoted_message(
            WahaClient(settings),
            message.session,
            chat_id,
            decision.quoted_message_id,
            log_context,
            inline=reply_to_inline if isinstance(reply_to_inline, dict) else None,
        )
        outcome.degradations.extend(resolved_quote.degraded)
        if resolved_quote.text:
            body = f"{resolved_quote.text}\n\n{body}".strip() if body.strip() else resolved_quote.text
        quoted_image = resolved_quote.image

    # Input-resolution priority (reply-to-media fix §4): a replied-to image
    # is the primary content — ahead of the current message's own
    # attachment, since a reply is what the user actually pointed at.
    effective_image = quoted_image or image_attachment

    if decision.is_group and parsed_command is not None:
        if parsed_command.command == commands.CEK:
            if not body.strip() and not attachments and not effective_image:
                # "!cek" and nothing else — no reply, no attachment, no quoted
                # text or image recovered, no inline text: called, but given
                # nothing to check.
                send = await WahaClient(settings).send_text(
                    chat_id, CEK_USAGE_REPLY, session=message.session, reply_to=message.waha_message_id
                )
                outcome.status = "command_cek_usage_error"
                outcome.response_dispatched = send.delivered
                return outcome.as_dict()
        elif parsed_command.command == commands.LINK and not extract_urls(body):
            send = await WahaClient(settings).send_text(
                chat_id, LINK_USAGE_REPLY, session=message.session, reply_to=message.waha_message_id
            )
            outcome.status = "command_link_usage_error"
            outcome.response_dispatched = send.delivered
            return outcome.as_dict()

    # --- stage 3c: OCR (image input becomes text) -------------------------
    # Folding OCR text into `body` here — before normalize_text() runs — is
    # the entire feature: every stage after this line (normalisation, intent
    # routing, claim extraction with its injection guard, RAG, verification)
    # runs the exact path a typed message already takes. OCR only changes
    # which text that path receives; it never produces a verdict itself.
    # `effective_image` — never the raw `image_attachment` — so a replied-to
    # picture is read the same way a directly attached one already is.
    if effective_image and settings.ocr_enabled:
        max_bytes = int(settings.ocr_max_image_size_mb * 1024 * 1024)
        image_bytes = effective_image.data
        if image_bytes is None and effective_image.url:
            image_bytes = await WahaClient(settings).download_media(effective_image.url)

        if not image_bytes:
            outcome.degradations.append("ocr_media_unavailable")
        elif len(image_bytes) > max_bytes:
            # Cheap, dependency-free rejection at the gateway — no reason to
            # ship an obviously oversized file to ml-service just to have it
            # reject the same thing after paying the upload cost.
            outcome.degradations.append("ocr_image_too_large")
        else:
            try:
                ocr_response = await ml.ocr(
                    request_id, image_bytes, effective_image.filename, effective_image.mimetype
                )
            except MlServiceError as exc:
                outcome.degradations.append(f"ocr_unavailable:{exc.error_code}")
            else:
                ocr_result = ocr_response.result
                ocr_text = str(ocr_result.get("text") or "").strip()
                ocr_success = bool(ocr_result.get("success", True))
                if settings.ocr_debug_log:
                    logger.debug("ocr result", extra={**log_context, "ocr_text": ocr_text})
                if ocr_success and ocr_text:
                    body = f"{body}\n\n{ocr_text}".strip() if body.strip() else ocr_text
                    outcome.ocr_used = True
                    outcome.ocr_confidence = ocr_response.confidence
                    if ocr_response.confidence is not None and ocr_response.confidence < settings.ocr_min_confidence:
                        # Text still flows into the pipeline as real evidence —
                        # never discarded merely for scoring low — but the
                        # audit trail records that this reading was shaky
                        # (13_Low_Confidence_OCR).
                        outcome.degradations.append("ocr_low_confidence")
                else:
                    # No usable text: never fabricate a claim from a picture
                    # that had nothing readable in it. `body` is left exactly
                    # as it was (any caption text still goes through
                    # normally); if there was none either, the message falls
                    # through to the same "nothing to check" path plain text
                    # already takes, ending in UNKNOWN/insufficient-evidence,
                    # never HOAX (12_Empty_Poor_OCR_Handling).
                    outcome.degradations.append("ocr_empty_result")

    # --- stage 4: preprocessing ------------------------------------------
    normalized = normalize_text(body)
    urls = extract_urls(body)
    outcome.url_count = len(urls)
    has_apk = any(name.lower().endswith(".apk") for name in attachments)

    # --- stage 5a: deterministic detection rules --------------------------
    if decision.is_group and parsed_command is not None and parsed_command.command == commands.LINK:
        # !link is an explicit command, not a natural-language guess: go
        # straight to the URL-safety engine the command promised rather than
        # letting the keyword lexicon reclassify it.
        intent = intent_router.IntentResult(
            category=Category.PHISHING_LINK,
            confidence=1.0,
            engine=intent_router.ENGINE_URL_SAFETY,
            signals=("command:link",),
        )
    else:
        intent = intent_router.classify(
            normalized.text,
            urls=urls,
            attachment_names=attachments,
        )
    outcome.intent = intent.category.value if intent.category else "UNKNOWN"
    outcome.intent_confidence = intent.confidence
    outcome.engine = intent.engine

    redis = aioredis.from_url(settings.redis_url, socket_connect_timeout=2, decode_responses=True)

    matches: list[dict[str, Any]] = []
    url_scan: UrlScanResult | None = None
    risk_signals: list[RiskLevel] = []

    try:
        # --- stage 5c: ML classification (additive, independent of the
        # rules engine that fired above) -----------------------------------
        # Inert until an operator explicitly promotes a model
        # (07_Model_Registry_and_Deployment §3-4) — `production_model` is
        # `None` for every message until that happens, so this is a no-op by
        # default rather than a behaviour change on deploy.
        production_model = await _cached_production_model(settings)
        if production_model and normalized.text.strip():
            try:
                ml_classification = await ml.classify(
                    request_id,
                    normalized.text,
                    production_model["model_version"],
                    production_model["artifact_sha256"],
                )
                predicted_category = str(ml_classification.result.get("category") or "")
                outcome.ml_category = predicted_category or None
                outcome.ml_confidence = ml_classification.confidence
                if predicted_category in CATEGORY_RISK:
                    risk_signals.append(CATEGORY_RISK[predicted_category])
            except MlServiceError as exc:
                outcome.degradations.append(f"ml_classify_unavailable:{exc.error_code}")

        # --- stage 5b/6: verification ------------------------------------
        if intent.engine == intent_router.ENGINE_URL_SAFETY and urls:
            url_scan = await scan_urls(urls, redis=redis, settings=settings, request_id=request_id)
            risk_signals.append(url_scan.risk)
            if url_scan.degraded:
                outcome.degradations.append("url_intel_unavailable")

        elif intent.engine == intent_router.ENGINE_TEXT_VERIFICATION:
            # Retrieve on the claim, not on the forward. A chain letter's
            # greeting, emoji and "TOLONG SEBARKAN!!!" are embedded too, and
            # they pull the vector away from the curated claim the knowledge
            # base actually stores. Extraction degrades rather than fails —
            # ml-service falls back to a deterministic heuristic internally —
            # so a failure here costs match quality, never the answer.
            rag_query_text = normalized.text
            if settings.rag_claim_extraction_enabled and normalized.text.strip():
                try:
                    extraction = await ml.extract_claim(
                        request_id,
                        normalized.text,
                        category=intent.category.value if intent.category else None,
                    )
                    extracted = str(extraction.result.get("claim") or "").strip()
                    if extracted:
                        rag_query_text = extracted
                        outcome.claim_method = str(extraction.result.get("method") or "")
                except MlServiceError as exc:
                    outcome.degradations.append(f"claim_extraction_unavailable:{exc.error_code}")

            try:
                response = await ml.rag_query(
                    request_id,
                    query=rag_query_text,
                    category=intent.category.value if intent.category else None,
                )
                matches = list(response.result.get("matches") or [])
                outcome.reranked = bool(response.result.get("reranked"))
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
            url_scan = await scan_urls(urls, redis=redis, settings=settings, request_id=request_id)
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
            reply_text = GENERATION_UNAVAILABLE_REPLY

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

    if decision.is_group and parsed_command is not None:
        logger.info(
            "jawara.command.executed", extra={**log_context, "command": parsed_command.command}
        )

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
        input_type=_input_type(outcome.url_count, has_apk, outcome.ocr_used),
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
