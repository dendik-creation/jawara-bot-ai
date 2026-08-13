"""WAHA REST client — outbound WhatsApp dispatch ([[Implement WhatsApp Response Sender]]).

Closes the loop: `POST /api/sendText` with `{session, chatId, text}`. This is the
last hop of the pipeline and the point where the <3.0s end-to-end KPI from
03_Pitching_Narrative can still be measured, so the caller passes the webhook
receipt time and this module logs the total.

Retry policy: transient failures (timeout, connection error, 5xx) are retried
`WAHA_SEND_MAX_ATTEMPTS` times with a short backoff. 4xx is not retried — a bad
`chatId` or a stopped session will fail identically on the second attempt, and
retrying only delays the log line that tells an operator what is wrong.
"""

import asyncio
import logging
from dataclasses import dataclass

import httpx

from app.core.config import Settings, get_settings

logger = logging.getLogger("app.clients.waha")

# session name → JIDs that session answers to. Populated on first use per worker
# process; cleared by restarting the worker, which is also what re-pairing a
# session requires.
_IDENTITY_CACHE: dict[str, frozenset[str]] = {}


@dataclass(frozen=True)
class SendResult:
    delivered: bool
    chat_id: str
    message_id: str | None = None
    attempts: int = 0
    error: str = ""


class WahaClient:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    @property
    def _headers(self) -> dict[str, str]:
        return {"X-Api-Key": self._settings.waha_api_key, "Content-Type": "application/json"}

    async def send_text(
        self,
        chat_id: str,
        text: str,
        session: str = "default",
        reply_to: str | None = None,
    ) -> SendResult:
        """Send one reply. Never raises — delivery failure is data, not an exception.

        `reply_to` quotes the message being answered. In a busy group a bare
        reply is unattributable — it is not clear which of the last twenty
        messages the bot is talking about. If WAHA rejects the field (older
        build, unsupported engine), the send is retried once without it: a
        delivered answer without the quote beats no answer.
        """
        url = f"{self._settings.waha_api_url.rstrip('/')}/api/sendText"
        body: dict[str, object] = {"session": session, "chatId": chat_id, "text": text}
        if reply_to:
            body["reply_to"] = reply_to
        attempts = max(1, self._settings.waha_send_max_attempts)
        last_error = ""

        attempt = 0
        while attempt < attempts:
            attempt += 1
            try:
                async with httpx.AsyncClient(timeout=self._settings.waha_send_timeout_seconds) as client:
                    response = await client.post(url, json=body, headers=self._headers)
            except httpx.TimeoutException:
                last_error = "timeout"
            except httpx.HTTPError as exc:
                last_error = type(exc).__name__
            else:
                if response.status_code < 400:
                    return SendResult(
                        delivered=True,
                        chat_id=chat_id,
                        message_id=_message_id(response),
                        attempts=attempt,
                    )
                last_error = f"http_{response.status_code}"
                if response.status_code < 500:
                    if "reply_to" in body:
                        # The quote is the only optional part of this request, so
                        # it is the first suspect for a 4xx. Drop it and try
                        # again rather than losing the answer — and do not spend
                        # a retry on it, or a single-attempt budget would turn a
                        # rejected quote into an undelivered reply.
                        logger.warning(
                            "waha rejected send with reply_to, retrying unquoted",
                            extra={"chat_id": chat_id, "status": response.status_code},
                        )
                        body.pop("reply_to")
                        attempt -= 1
                        continue
                    logger.error(
                        "waha rejected send, not retrying",
                        extra={"chat_id": chat_id, "status": response.status_code, "attempt": attempt},
                    )
                    return SendResult(delivered=False, chat_id=chat_id, attempts=attempt, error=last_error)

            logger.warning(
                "waha send failed",
                extra={"chat_id": chat_id, "attempt": attempt, "error": last_error},
            )
            if attempt < attempts:
                await asyncio.sleep(self._settings.waha_send_retry_backoff_seconds * attempt)

        logger.error(
            "waha send failed after retries, response not delivered",
            extra={"chat_id": chat_id, "attempts": attempts, "error": last_error},
        )
        return SendResult(delivered=False, chat_id=chat_id, attempts=attempts, error=last_error)

    async def get_message_text(self, session: str, chat_id: str, message_id: str) -> str | None:
        """Body text of one historical message — the content a reply is asking about.

        WAHA's webhook payload for a reply carries the *replied-to* message's id
        (`app/pipeline/group_policy.py:quoted_message_id`), not its text — the
        quote is a pointer, not an inline copy. This resolves that pointer.
        Returns `None` on any failure (message deleted, id from before the
        session paired, WAHA unreachable); the caller treats that as "no quoted
        text available", not an error.
        """
        url = f"{self._settings.waha_api_url.rstrip('/')}/api/{session}/chats/{chat_id}/messages/{message_id}"
        try:
            async with httpx.AsyncClient(timeout=self._settings.waha_send_timeout_seconds) as client:
                response = await client.get(url, headers=self._headers)
            if response.status_code >= 400:
                return None
            data = response.json()
        except Exception:  # noqa: BLE001 — a missing quote must degrade, not raise
            logger.warning(
                "waha quoted message fetch failed",
                extra={"chat_id": chat_id, "message_id": message_id},
                exc_info=True,
            )
            return None

        if not isinstance(data, dict):
            return None
        text = data.get("body") or data.get("caption")
        return text.strip() if isinstance(text, str) and text.strip() else None

    async def list_sessions(self) -> list[dict[str, object]]:
        """Normalised session list for the Control Panel.

        The frontend never talks to WAHA directly (02_Architecture/05_Integrations
        §1) — it asks the gateway, and the gateway hides WAHA's payload shape.
        """
        url = f"{self._settings.waha_api_url.rstrip('/')}/api/sessions"
        try:
            async with httpx.AsyncClient(timeout=self._settings.waha_send_timeout_seconds) as client:
                response = await client.get(url, headers=self._headers)
            if response.status_code >= 400:
                return []
            payload = response.json()
        except Exception:  # noqa: BLE001 — dashboard probe, never propagates
            logger.warning("waha session list unavailable", exc_info=True)
            return []

        sessions = payload if isinstance(payload, list) else payload.get("sessions", [])
        return [
            {
                "name": session.get("name", "default"),
                "status": session.get("status", "UNKNOWN"),
                "engine": (session.get("engine") or {}).get("engine")
                if isinstance(session.get("engine"), dict)
                else session.get("engine"),
            }
            for session in sessions
            if isinstance(session, dict)
        ]

    async def session_identity(self, session: str) -> frozenset[str]:
        """The JIDs this session answers to.

        A WhatsApp account now has two: the phone-number JID (`62…@c.us`) and
        its LID twin (`249…@lid`). A mention can carry either, so both are
        needed to recognise "the bot was addressed" — see
        `app/pipeline/group_policy.py`.

        Cached per process: it changes only when the session is re-paired, and
        it is consulted for every group message. Configured IDs
        (`BOT_WHATSAPP_IDS`) are merged in, which is also the escape hatch when
        WAHA cannot be asked.
        """
        configured = frozenset(self._settings.bot_whatsapp_id_list)
        cached = _IDENTITY_CACHE.get(session)
        if cached is not None:
            return cached | configured

        url = f"{self._settings.waha_api_url.rstrip('/')}/api/sessions/{session}"
        try:
            async with httpx.AsyncClient(timeout=self._settings.waha_send_timeout_seconds) as client:
                response = await client.get(url, headers=self._headers)
            if response.status_code >= 400:
                raise ValueError(f"http_{response.status_code}")
            me = (response.json() or {}).get("me") or {}
        except Exception:  # noqa: BLE001
            # Not cached: a transient failure must not pin the bot as nameless
            # for the life of the worker.
            logger.warning("waha session identity unavailable", extra={"session": session}, exc_info=True)
            return configured

        identity = frozenset(
            value for value in (me.get("id"), me.get("lid")) if isinstance(value, str) and value
        )
        _IDENTITY_CACHE[session] = identity
        logger.info("waha session identity resolved", extra={"session": session, "ids": sorted(identity)})
        return identity | configured

    async def is_reachable(self) -> bool:
        """`/ping` is the only unauthenticated WAHA route (see the compose healthcheck)."""
        url = f"{self._settings.waha_api_url.rstrip('/')}/ping"
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                response = await client.get(url)
            return response.status_code < 400
        except Exception:  # noqa: BLE001
            return False


def _message_id(response: httpx.Response) -> str | None:
    try:
        body = response.json()
    except ValueError:
        return None
    if not isinstance(body, dict):
        return None
    identifier = body.get("id")
    if isinstance(identifier, dict):
        return identifier.get("_serialized") or identifier.get("id")
    return identifier if isinstance(identifier, str) else None
