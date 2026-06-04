from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.core.agentic.source_health import SourceHealthTracker


def test_missing_timestamp_spike_triggers_warning():
    tracker = SourceHealthTracker(missing_timestamp_rate_threshold=0.30)
    tracker.record_fetch("Finviz", 10)
    tracker.record_missing_timestamp("Finviz", 4)

    warnings = tracker.evaluate()

    assert len(warnings) == 1
    assert "missing timestamp rate" in warnings[0]


def test_normal_parser_activity_does_not_spam_alerts():
    now = datetime(2026, 6, 4, tzinfo=timezone.utc)
    tracker = SourceHealthTracker(
        missing_timestamp_rate_threshold=0.30,
        warning_cooldown_seconds=900,
    )
    tracker.record_fetch("StockTitan", 100, now=now)
    tracker.record_missing_timestamp("StockTitan", 35)

    first = tracker.evaluate(now=now)
    second = tracker.evaluate(now=now + timedelta(seconds=60))

    assert len(first) == 1
    assert second == []


def test_stale_source_triggers_warning():
    now = datetime(2026, 6, 4, tzinfo=timezone.utc)
    tracker = SourceHealthTracker(stale_after_seconds=300)
    tracker.record_fetch("Finviz", 50, now=now)

    warnings = tracker.evaluate(now=now + timedelta(seconds=301))

    assert len(warnings) == 1
    assert "source stale" in warnings[0]


def test_repeated_parse_errors_surface_in_health_evaluation():
    now = datetime(2026, 6, 4, tzinfo=timezone.utc)
    tracker = SourceHealthTracker(parse_error_threshold=2)

    tracker.record_parse_error("BusinessWire", now=now)
    tracker.record_parse_error("BusinessWire", now=now + timedelta(seconds=10))

    warnings = tracker.evaluate(now=now + timedelta(seconds=20))

    assert len(warnings) == 1
    assert "BusinessWire parser errors" in warnings[0]
