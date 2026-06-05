"""Per-alert latency trace logging for News Momentum.

This module is deliberately small and dependency-light so it can be called from
scanner, gate, and Telegram code without pulling in the rest of the pipeline.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional


from src.utils.data_paths import AGENTIC_DATA_DIR as DATA_DIR
TRACE_FILE = DATA_DIR / "news_alert_latency_trace.jsonl"
_LOCK = threading.Lock()


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def aware_utc(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
    try:
        text = str(value).replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
        return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)
    except Exception:
        return None


def iso(value: Any) -> Optional[str]:
    dt = aware_utc(value)
    return dt.isoformat() if dt else None


def seconds_between(start: Any, end: Any) -> Optional[float]:
    start_dt = aware_utc(start)
    end_dt = aware_utc(end)
    if not start_dt or not end_dt:
        return None
    return round((end_dt - start_dt).total_seconds(), 3)


def _enum_value(value: Any) -> Any:
    return getattr(value, "value", value)


def build_latency_record(
    *,
    ticker: str,
    headline: str,
    source: Any,
    published_at: Any = None,
    fetched_at: Any = None,
    parsed_at: Any = None,
    candidate_created_at: Any = None,
    classified_at: Any = None,
    scored_at: Any = None,
    gate_decision_at: Any = None,
    telegram_enqueue_at: Any = None,
    telegram_sent_at: Any = None,
    blocked_reason: Optional[str] = None,
    alert_sent: bool = False,
    **extra: Any,
) -> dict[str, Any]:
    gate_or_score_at = gate_decision_at or scored_at
    terminal_at = telegram_sent_at or telegram_enqueue_at or gate_decision_at or scored_at
    record: dict[str, Any] = {
        "ticker": ticker,
        "headline": headline,
        "source": _enum_value(source),
        "published_at": iso(published_at),
        "fetched_at": iso(fetched_at),
        "parsed_at": iso(parsed_at),
        "candidate_created_at": iso(candidate_created_at),
        "classified_at": iso(classified_at),
        "scored_at": iso(scored_at),
        "gate_decision_at": iso(gate_decision_at),
        "telegram_enqueue_at": iso(telegram_enqueue_at),
        "telegram_sent_at": iso(telegram_sent_at),
        "blocked_reason": blocked_reason,
        "latency_seconds_from_published_to_fetch": seconds_between(published_at, fetched_at),
        "latency_seconds_from_fetch_to_gate": seconds_between(fetched_at, gate_or_score_at),
        "latency_seconds_from_gate_to_telegram": seconds_between(gate_decision_at, telegram_sent_at or telegram_enqueue_at),
        "total_latency_seconds": seconds_between(published_at, terminal_at),
        "alert_sent": bool(alert_sent),
    }
    record.update(extra)
    return record


def build_candidate_latency_record(candidate: Any, *, alert_sent: bool, blocked_reason: Optional[str] = None, **extra: Any) -> dict[str, Any]:
    return build_latency_record(
        ticker=str(getattr(candidate, "ticker", "") or ""),
        headline=str(getattr(candidate, "headline", "") or ""),
        source=getattr(candidate, "source", ""),
        published_at=getattr(candidate, "published_at", None),
        fetched_at=getattr(candidate, "fetched_at", None),
        parsed_at=getattr(candidate, "parsed_at", None),
        candidate_created_at=getattr(candidate, "candidate_created_at", None),
        classified_at=getattr(candidate, "classified_at", None),
        scored_at=getattr(candidate, "scored_at", None),
        gate_decision_at=getattr(candidate, "gate_decision_at", None),
        telegram_enqueue_at=getattr(candidate, "telegram_enqueue_at", None),
        telegram_sent_at=getattr(candidate, "telegram_sent_at", None),
        blocked_reason=blocked_reason or getattr(candidate, "_block_reason", None),
        alert_sent=alert_sent,
        **extra,
    )


def append_latency_trace(record: Mapping[str, Any], path: Path = TRACE_FILE) -> None:
    if os.environ.get("PYTEST_CURRENT_TEST") and os.environ.get("NEWS_ALERT_LATENCY_TRACE_IN_TESTS") != "1":
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with _LOCK:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(dict(record), ensure_ascii=False, sort_keys=True, default=str) + "\n")


def trace_candidate(candidate: Any, *, alert_sent: bool, blocked_reason: Optional[str] = None, **extra: Any) -> None:
    append_latency_trace(
        build_candidate_latency_record(
            candidate,
            alert_sent=alert_sent,
            blocked_reason=blocked_reason,
            **extra,
        )
    )
