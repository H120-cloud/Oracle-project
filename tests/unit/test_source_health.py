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


def test_health_snapshot_report_includes_status_and_dashboard_metrics():
    now = datetime(2026, 6, 4, tzinfo=timezone.utc)
    tracker = SourceHealthTracker(
        missing_timestamp_rate_threshold=0.30,
        parse_error_threshold=2,
        stale_after_seconds=300,
    )
    tracker.record_fetch("StockTitan", 10, now=now)
    tracker.record_tickered_headline("StockTitan", 6)
    tracker.record_untickered_headline("StockTitan", 2)
    tracker.record_missing_timestamp("StockTitan", 4)
    tracker.record_dropped_headline("StockTitan", 1)
    tracker.record_latency(
        "StockTitan",
        now - timedelta(seconds=120),
        detected_at=now,
    )
    tracker.evaluate(now=now + timedelta(seconds=10))

    report = tracker.to_dict(now=now + timedelta(seconds=10))
    stocktitan = report["stocktitan"]

    assert stocktitan["source"] == "StockTitan"
    assert stocktitan["status"] == "warning"
    assert stocktitan["headlines_fetched"] == 10
    assert stocktitan["tickered_headline_count"] == 6
    assert stocktitan["untickered_headline_count"] == 2
    assert stocktitan["dropped_headline_count"] == 3
    assert stocktitan["dropped_headline_rate"] == 0.3
    assert stocktitan["missing_timestamp_rate"] == 0.4
    assert stocktitan["avg_latency_seconds"] == 120
    assert stocktitan["last_successful_parse_age_seconds"] == 10
    assert stocktitan["warnings"]


def test_errored_source_with_no_success_is_error_not_ok():
    """A source that has errored at least once and never succeeded must report
    'error', not 'ok' — otherwise a silently-failing scraper (e.g. Sharecast
    403/empty) shows green until it hits the error threshold, defeating the
    dashboard. Regression guard for the 2026-06 Sharecast fix."""
    tracker = SourceHealthTracker(parse_error_threshold=3)
    now = datetime(2026, 6, 5, tzinfo=timezone.utc)
    tracker.record_parse_error("Sharecast", now=now)  # 1 error, 0 successes
    data = tracker.to_dict(now=now)
    assert data["sharecast"]["status"] == "error"
    assert data["sharecast"]["parse_error_count"] == 1


def test_source_recovers_to_ok_after_successful_fetch():
    """Once a previously-errored source fetches successfully, it should no
    longer be flagged 'error' purely on the historical error."""
    tracker = SourceHealthTracker(parse_error_threshold=3)
    now = datetime(2026, 6, 5, tzinfo=timezone.utc)
    tracker.record_parse_error("Sharecast", now=now)
    tracker.record_fetch("Sharecast", 12, now=now + timedelta(seconds=30))
    data = tracker.to_dict(now=now + timedelta(seconds=30))
    assert data["sharecast"]["status"] == "ok"
