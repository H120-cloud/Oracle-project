from datetime import datetime, timedelta, timezone

from src.core.agentic.news_alert_latency_trace import build_latency_record


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
