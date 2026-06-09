import json
from datetime import datetime, timedelta, timezone

from src.core.agentic.news_alert_latency_trace import (
    build_latency_record,
    compact_latency_trace,
)


def _write_trace(path, rows):
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return path


def test_latency_trace_computes_stage_durations():
    published = datetime(2026, 6, 5, 12, 0, tzinfo=timezone.utc)
    fetched = published + timedelta(seconds=5)
    gate = fetched + timedelta(seconds=3)
    sent = gate + timedelta(seconds=2)

    record = build_latency_record(
        ticker="FAST",
        headline="FAST wins FDA approval",
        source="stocktitan",
        published_at=published,
        fetched_at=fetched,
        gate_decision_at=gate,
        telegram_sent_at=sent,
        alert_sent=True,
    )

    assert record["latency_seconds_from_published_to_fetch"] == 5.0
    assert record["latency_seconds_from_fetch_to_gate"] == 3.0
    assert record["latency_seconds_from_gate_to_telegram"] == 2.0
    assert record["total_latency_seconds"] == 10.0
    assert record["alert_sent"] is True


def test_compact_collapses_duplicate_blocked_keeps_earliest(tmp_path):
    pub = "2026-06-08T08:00:00+00:00"
    rows = [
        # Same blocked event re-logged 3x with growing latency (the bug pattern).
        {"ticker": "MDLN", "published_at": pub, "blocked_reason": "impact_floor",
         "alert_sent": False, "total_latency_seconds": 120.0},
        {"ticker": "MDLN", "published_at": pub, "blocked_reason": "impact_floor",
         "alert_sent": False, "total_latency_seconds": 5000.0},
        {"ticker": "MDLN", "published_at": pub, "blocked_reason": "impact_floor",
         "alert_sent": False, "total_latency_seconds": 8000.0},
        # A delivered alert — always kept.
        {"ticker": "NVDA", "published_at": pub, "blocked_reason": None,
         "alert_sent": True, "total_latency_seconds": 4.0},
    ]
    path = _write_trace(tmp_path / "trace.jsonl", rows)

    stats = compact_latency_trace(path, retention_days=0)  # no retention drop
    assert stats == {"before": 4, "after": 2, "removed": 2}

    kept = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    blocked = [r for r in kept if not r["alert_sent"]]
    alerted = [r for r in kept if r["alert_sent"]]
    assert len(blocked) == 1
    assert blocked[0]["total_latency_seconds"] == 120.0  # earliest/real first block
    assert len(alerted) == 1


def test_compact_drops_events_outside_retention_window(tmp_path):
    now = datetime(2026, 6, 9, 12, 0, tzinfo=timezone.utc)
    fresh = (now - timedelta(days=2)).isoformat()
    old = (now - timedelta(days=40)).isoformat()
    rows = [
        {"ticker": "AAA", "published_at": fresh, "blocked_reason": "bad_ticker",
         "alert_sent": False, "total_latency_seconds": 10.0},
        {"ticker": "OLD", "published_at": old, "blocked_reason": "bad_ticker",
         "alert_sent": False, "total_latency_seconds": 10.0},
    ]
    path = _write_trace(tmp_path / "trace.jsonl", rows)

    stats = compact_latency_trace(path, retention_days=30, now=now)
    assert stats["after"] == 1
    kept = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    assert {r["ticker"] for r in kept} == {"AAA"}


def test_compact_missing_file_is_noop(tmp_path):
    assert compact_latency_trace(tmp_path / "nope.jsonl") == {"before": 0, "after": 0, "removed": 0}
