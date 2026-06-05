"""Durable Telegram alert outbox.

The outbox is intentionally independent from alert scoring and gating. It only
persists delivery attempts so a transient Telegram/network failure does not
drop an already-approved alert.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Literal, Optional

logger = logging.getLogger(__name__)

from src.utils.data_paths import AGENTIC_DATA_DIR as DATA_DIR
OUTBOX_FILE = DATA_DIR / "telegram_outbox.jsonl"
MAX_ATTEMPTS = int(os.environ.get("TELEGRAM_OUTBOX_MAX_ATTEMPTS", "6") or 6)

OutboxStatus = Literal["pending", "sent", "failed", "dead_letter"]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def _parse_dt(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not value:
        return None
    try:
        text = str(value).replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _backoff_seconds(attempts: int) -> int:
    return min(900, 15 * (2 ** max(0, attempts - 1)))


@dataclass
class TelegramOutboxRecord:
    alert_id: str
    ticker: str = "UNKNOWN"
    alert_type: str = "generic"
    message: str = ""
    created_at: datetime = field(default_factory=_now)
    status: OutboxStatus = "pending"
    attempts: int = 0
    last_error: str = ""
    next_retry_at: datetime = field(default_factory=_now)
    telegram_response: Any = None
    priority: int = 5

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "TelegramOutboxRecord":
        return cls(
            alert_id=str(raw.get("alert_id") or ""),
            ticker=str(raw.get("ticker") or "UNKNOWN"),
            alert_type=str(raw.get("alert_type") or "generic"),
            message=str(raw.get("message") or ""),
            created_at=_parse_dt(raw.get("created_at")) or _now(),
            status=raw.get("status") if raw.get("status") in {"pending", "sent", "failed", "dead_letter"} else "pending",
            attempts=int(raw.get("attempts") or 0),
            last_error=str(raw.get("last_error") or ""),
            next_retry_at=_parse_dt(raw.get("next_retry_at")) or _now(),
            telegram_response=raw.get("telegram_response"),
            priority=int(raw.get("priority") or 5),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "alert_id": self.alert_id,
            "ticker": self.ticker,
            "alert_type": self.alert_type,
            "message": self.message,
            "created_at": _iso(self.created_at),
            "status": self.status,
            "attempts": self.attempts,
            "last_error": self.last_error,
            "next_retry_at": _iso(self.next_retry_at),
            "telegram_response": self.telegram_response,
            "priority": self.priority,
        }


def load_outbox(path: Path = OUTBOX_FILE) -> list[TelegramOutboxRecord]:
    if not path.exists():
        return []
    records: list[TelegramOutboxRecord] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            record = TelegramOutboxRecord.from_dict(json.loads(line))
            if record.alert_id:
                records.append(record)
        except Exception as exc:
            logger.debug("Telegram outbox skipped corrupt record: %s", exc)
    return records


def save_outbox(records: Iterable[TelegramOutboxRecord], path: Path = OUTBOX_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = "".join(
        json.dumps(record.to_dict(), ensure_ascii=False, sort_keys=True) + "\n"
        for record in records
    )
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            try:
                os.remove(tmp_name)
            except OSError:
                pass


def enqueue_alert(
    *,
    alert_id: str,
    message: str,
    ticker: str = "UNKNOWN",
    alert_type: str = "generic",
    last_error: str = "",
    telegram_response: Any = None,
    retry_after: int | float | None = None,
    priority: int = 5,
    path: Path = OUTBOX_FILE,
) -> TelegramOutboxRecord:
    records = load_outbox(path)
    existing = next((r for r in records if r.alert_id == alert_id), None)
    next_retry = _now() + timedelta(seconds=float(retry_after or _backoff_seconds((existing.attempts + 1) if existing else 1)))
    if existing is not None:
        if existing.status == "sent":
            return existing
        existing.message = message
        existing.ticker = ticker or existing.ticker
        existing.alert_type = alert_type or existing.alert_type
        existing.status = "pending"
        existing.last_error = last_error
        existing.telegram_response = telegram_response
        existing.next_retry_at = next_retry
        existing.priority = min(existing.priority, priority)
        save_outbox(records, path)
        return existing

    record = TelegramOutboxRecord(
        alert_id=alert_id,
        ticker=ticker or "UNKNOWN",
        alert_type=alert_type or "generic",
        message=message,
        status="pending",
        attempts=0,
        last_error=last_error,
        next_retry_at=next_retry,
        telegram_response=telegram_response,
        priority=priority,
    )
    records.append(record)
    save_outbox(records, path)
    return record


@dataclass
class OutboxSendResult:
    success: bool
    error: str = ""
    response: Any = None
    retry_after: int | float | None = None


async def drain_pending(
    send_func: Callable[[str], Any],
    *,
    now: datetime | None = None,
    limit: int = 25,
    path: Path = OUTBOX_FILE,
) -> dict[str, int]:
    now = now or _now()
    records = load_outbox(path)
    eligible = [
        r for r in records
        if r.status in {"pending", "failed"} and (_parse_dt(r.next_retry_at) or now) <= now
    ]
    eligible.sort(key=lambda r: (r.priority, r.created_at))
    stats = {"attempted": 0, "sent": 0, "failed": 0, "dead_letter": 0}

    by_id = {r.alert_id: r for r in records}
    for record in eligible[:limit]:
        stats["attempted"] += 1
        record.attempts += 1
        try:
            result = await send_func(record.message)
        except Exception as exc:
            result = OutboxSendResult(success=False, error=str(exc))

        if bool(getattr(result, "success", False)):
            record.status = "sent"
            record.last_error = ""
            record.telegram_response = getattr(result, "response", None)
            stats["sent"] += 1
        else:
            record.last_error = str(getattr(result, "error", "") or "send_failed")
            record.telegram_response = getattr(result, "response", None)
            if record.attempts >= MAX_ATTEMPTS:
                record.status = "dead_letter"
                stats["dead_letter"] += 1
            else:
                record.status = "failed"
                retry_after = getattr(result, "retry_after", None)
                delay = float(retry_after or _backoff_seconds(record.attempts))
                record.next_retry_at = now + timedelta(seconds=delay)
                stats["failed"] += 1
        by_id[record.alert_id] = record

    save_outbox(by_id.values(), path)
    return stats
