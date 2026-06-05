"""Durable audit log for Pre-News Telegram alert decisions."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional


DATA_DIR = Path(os.environ.get("AGENTIC_DATA_DIR", "data/agentic"))
DEFAULT_AUDIT_PATH = DATA_DIR / "pre_news_alert_decisions.jsonl"


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "value"):
        return value.value
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    return str(value)


def _nested_value(obj: Any, attr: str, default: Any = None) -> Any:
    current = obj
    for part in attr.split("."):
        current = getattr(current, part, default)
        if current is default:
            return default
    return current


def build_pre_news_alert_audit_record(
    anomaly: Any,
    decision: Mapping[str, Any],
    *,
    telegram_attempted: bool = False,
    telegram_sent: Optional[bool] = None,
    telegram_error: Optional[str] = None,
    created_at: Optional[datetime] = None,
) -> dict[str, Any]:
    created_at = created_at or datetime.now(timezone.utc)
    reasons = list(decision.get("reasons") or [])
    return {
        "created_at": created_at.isoformat(),
        "ticker": getattr(anomaly, "ticker", ""),
        "detected_at": _json_safe(getattr(anomaly, "detected_at", None)),
        "should_alert": bool(decision.get("should_alert", False)),
        "decision_reasons": reasons,
        "telegram_attempted": bool(telegram_attempted),
        "telegram_sent": telegram_sent,
        "telegram_error": telegram_error,
        "score": _json_safe(getattr(anomaly, "pre_news_suspicion_score", None)),
        "smart_money_score": _json_safe(getattr(anomaly, "smart_money_score", None)),
        "alert_quality": _json_safe(getattr(anomaly, "alert_quality", None)),
        "late_detection_flag": _json_safe(getattr(anomaly, "late_detection_flag", None)),
        "alert_sent_before": _json_safe(getattr(anomaly, "alert_sent", None)),
        "last_alert_score": _json_safe(getattr(anomaly, "last_alert_score", None)),
        "offering_risk_score": _json_safe(getattr(anomaly, "offering_risk_score", None)),
        "data_quality_state": _json_safe(getattr(anomaly, "data_quality_state", None)),
        "news_status": _json_safe(getattr(anomaly, "news_status", None)),
        "anomaly_type": _json_safe(getattr(anomaly, "anomaly_type", None)),
        "price": _json_safe(getattr(anomaly, "price", None)),
        "price_behaviour": _json_safe(_nested_value(anomaly, "price_behaviour.behaviour")),
        "price_change_pct": _json_safe(_nested_value(anomaly, "price_behaviour.price_change_pct")),
        "rvol_current": _json_safe(_nested_value(anomaly, "volume_metrics.rvol_current")),
        "volume_acceleration": _json_safe(_nested_value(anomaly, "volume_metrics.volume_acceleration")),
        "volume_accel_trend": _json_safe(_nested_value(anomaly, "volume_metrics.accel_trend")),
        "suppression_reasons": _json_safe(getattr(anomaly, "alert_suppression_reasons", [])),
    }


def record_pre_news_alert_decision(
    anomaly: Any,
    decision: Mapping[str, Any],
    *,
    telegram_attempted: bool = False,
    telegram_sent: Optional[bool] = None,
    telegram_error: Optional[str] = None,
    audit_path: Path = DEFAULT_AUDIT_PATH,
) -> dict[str, Any]:
    record = build_pre_news_alert_audit_record(
        anomaly,
        decision,
        telegram_attempted=telegram_attempted,
        telegram_sent=telegram_sent,
        telegram_error=telegram_error,
    )
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    with audit_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")
    return record


__all__ = [
    "DEFAULT_AUDIT_PATH",
    "build_pre_news_alert_audit_record",
    "record_pre_news_alert_decision",
]
