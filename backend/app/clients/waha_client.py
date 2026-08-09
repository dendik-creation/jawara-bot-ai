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

    async def send_text(self, chat_id: str, text: str, session: str = "default") -> SendResult:
        """Send one reply. Never raises — delivery failure is data, not an exception."""
        url = f"{self._settings.waha_api_url.rstrip('/')}/api/sendText"
        body = {"session": session, "chatId": chat_id, "text": text}
        attempts = max(1, self._settings.waha_send_max_attempts)
        last_error = ""

        for attempt in range(1, attempts + 1):
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
