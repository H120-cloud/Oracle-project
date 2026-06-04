"""
Telegram Alert Service.

Sends alert messages to a Telegram chat via the Bot API. Failed sends are
persisted to a durable JSONL outbox so transient Telegram/network failures do
not permanently lose alerts.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
from dataclasses import dataclass
from typing import Any, Optional

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

import httpx

from src.services.telegram_outbox import OutboxSendResult, drain_pending, enqueue_alert

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org"
TIMEOUT = 10.0
OUTBOX_DRAIN_INTERVAL_SECONDS = float(
    os.environ.get("TELEGRAM_OUTBOX_DRAIN_INTERVAL_SECONDS", "5") or 5
)

# Telegram-allowed HTML tags. Any other `<...>` we encounter must be escaped
# or Telegram returns 400 "can't parse entities".
_TELEGRAM_TAG_RE = re.compile(
    r"</?(?:b|strong|i|em|u|ins|s|strike|del|span|tg-spoiler|code|pre|a)"
    r"(?:\s[^<>]*)?>",
    re.IGNORECASE,
)


def _sanitize_html(text: str) -> str:
    """
    Sanitize a Telegram HTML message while preserving supported tags.
    """
    if not text:
        return text
    parts = []
    last_end = 0
    for m in _TELEGRAM_TAG_RE.finditer(text):
        chunk = text[last_end : m.start()]
        chunk = chunk.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        parts.append(chunk)
        parts.append(m.group(0))
        last_end = m.end()
    tail = text[last_end:].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    parts.append(tail)
    return "".join(parts)


def _get_config() -> tuple[Optional[str], Optional[str]]:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    return (token or None, chat_id or None)


def _default_alert_id(text: str, alert_type: str = "generic") -> str:
    digest = hashlib.sha256(f"{alert_type}:{text}".encode("utf-8")).hexdigest()
    return digest[:32]


def _extract_retry_after(payload: Any) -> Optional[float]:
    if not isinstance(payload, dict):
        return None
    params = payload.get("parameters")
    if not isinstance(params, dict):
        return None
    retry_after = params.get("retry_after")
    try:
        return float(retry_after)
    except (TypeError, ValueError):
        return None


@dataclass
class TelegramSendResult:
    success: bool
    error: str = ""
    response: Optional[dict[str, Any]] = None
    retry_after: Optional[float] = None


async def _send_telegram_raw(text: str, parse_mode: str = "HTML") -> TelegramSendResult:
    token, chat_id = _get_config()
    if not token or not chat_id:
        logger.debug("Telegram not configured - skipping alert")
        return TelegramSendResult(False, error="telegram_not_configured")

    if parse_mode == "HTML":
        text = _sanitize_html(text)

    url = f"{TELEGRAM_API}/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True,
    }

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.post(url, json=payload)
            try:
                body = resp.json()
            except Exception:
                body = {"raw": resp.text[:500]}

            if resp.status_code == 200:
                logger.debug("Telegram alert sent successfully")
                return TelegramSendResult(True, response=body)

            retry_after = _extract_retry_after(body)
            logger.warning("Telegram API returned %s: %s", resp.status_code, resp.text[:200])
            return TelegramSendResult(
                False,
                error=f"telegram_api_{resp.status_code}",
                response=body,
                retry_after=retry_after,
            )
    except httpx.TimeoutException:
        logger.warning("Telegram send timed out")
        return TelegramSendResult(False, error="timeout")
    except Exception as exc:
        logger.warning("Telegram send failed: %s", exc)
        return TelegramSendResult(False, error=str(exc))


async def send_telegram_alert(
    text: str,
    parse_mode: str = "HTML",
    *,
    alert_id: Optional[str] = None,
    ticker: str = "UNKNOWN",
    alert_type: str = "generic",
    priority: int = 5,
    enqueue_on_failure: bool = True,
) -> bool:
    """
    Send a message to the configured Telegram chat.

    Returns True if sent successfully. On transient failure, the message is
    stored in the durable outbox for background retry.
    """
    result = await _send_telegram_raw(text, parse_mode=parse_mode)
    if result.success:
        return True

    if enqueue_on_failure:
        enqueue_alert(
            alert_id=alert_id or _default_alert_id(text, alert_type),
            ticker=ticker,
            alert_type=alert_type,
            message=text,
            priority=priority,
            last_error=result.error,
            telegram_response=result.response,
            retry_after=result.retry_after,
        )
    return False


def send_telegram_alert_sync(
    text: str,
    parse_mode: str = "HTML",
    *,
    alert_id: Optional[str] = None,
    ticker: str = "UNKNOWN",
    alert_type: str = "generic",
    priority: int = 5,
    enqueue_on_failure: bool = True,
) -> bool:
    """
    Synchronous version for use outside async contexts.
    """
    token, chat_id = _get_config()
    if not token or not chat_id:
        logger.debug("Telegram not configured - skipping alert")
        if enqueue_on_failure:
            enqueue_alert(
                alert_id=alert_id or _default_alert_id(text, alert_type),
                ticker=ticker,
                alert_type=alert_type,
                message=text,
                priority=priority,
                last_error="telegram_not_configured",
            )
        return False

    send_text = _sanitize_html(text) if parse_mode == "HTML" else text
    url = f"{TELEGRAM_API}/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": send_text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True,
    }

    try:
        with httpx.Client(timeout=TIMEOUT) as client:
            resp = client.post(url, json=payload)
            try:
                body = resp.json()
            except Exception:
                body = {"raw": resp.text[:500]}

            if resp.status_code == 200:
                logger.debug("Telegram alert sent successfully")
                return True

            retry_after = _extract_retry_after(body)
            logger.warning("Telegram API returned %s: %s", resp.status_code, resp.text[:200])
            if enqueue_on_failure:
                enqueue_alert(
                    alert_id=alert_id or _default_alert_id(text, alert_type),
                    ticker=ticker,
                    alert_type=alert_type,
                    message=text,
                    priority=priority,
                    last_error=f"telegram_api_{resp.status_code}",
                    telegram_response=body,
                    retry_after=retry_after,
                )
            return False
    except Exception as exc:
        logger.warning("Telegram send failed: %s", exc)
        if enqueue_on_failure:
            enqueue_alert(
                alert_id=alert_id or _default_alert_id(text, alert_type),
                ticker=ticker,
                alert_type=alert_type,
                message=text,
                priority=priority,
                last_error=str(exc),
            )
        return False


async def drain_telegram_outbox_once(limit: int = 25) -> dict[str, int]:
    async def _send(message: str) -> OutboxSendResult:
        result = await _send_telegram_raw(message, parse_mode="HTML")
        return OutboxSendResult(
            success=result.success,
            error=result.error,
            response=result.response,
            retry_after=result.retry_after,
        )

    return await drain_pending(_send, limit=limit)


async def telegram_outbox_sender_loop() -> None:
    logger.info("Telegram outbox sender started")
    while True:
        try:
            stats = await drain_telegram_outbox_once()
            if stats.get("sent") or stats.get("dead_letter"):
                logger.info("Telegram outbox drain stats: %s", stats)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Telegram outbox sender error: %s", exc)
        await asyncio.sleep(OUTBOX_DRAIN_INTERVAL_SECONDS)
