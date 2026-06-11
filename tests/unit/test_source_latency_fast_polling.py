"""Source-latency warning + fast-source-first polling order."""

from datetime import datetime, timedelta, timezone

import pytest

from src.core.agentic.source_health import (
    SOURCE_LATENCY_WARN_SECONDS,
    maybe_warn_source_latency,
    _reset_latency_warn_throttle,
)


@pytest.fixture(autouse=True)
def _clean_throttle():
    _reset_latency_warn_throttle()
    yield
    _reset_latency_warn_throttle()


@pytest.mark.unit
def test_warns_when_latency_exceeds_threshold(caplog):
    now = datetime(2026, 6, 10, 18, 32, tzinfo=timezone.utc)
    with caplog.at_level("WARNING"):
        fired = maybe_warn_source_latency("finviz", 1800.0, now=now)
    assert fired is True
    assert "SOURCE LATENCY WARNING" in caplog.text
    assert "finviz" in caplog.text
    assert "30m" in caplog.text


@pytest.mark.unit
def test_no_warning_below_threshold():
    assert SOURCE_LATENCY_WARN_SECONDS == 120.0
    assert maybe_warn_source_latency("finviz", 90.0) is False


@pytest.mark.unit
def test_warning_throttled_per_source():
    now = datetime(2026, 6, 10, 18, 0, tzinfo=timezone.utc)
    assert maybe_warn_source_latency("finviz", 1800.0, now=now) is True
    # immediate repeat for the same source is suppressed
    assert maybe_warn_source_latency("finviz", 1900.0, now=now + timedelta(seconds=30)) is False
    # other sources warn independently
    assert maybe_warn_source_latency("stocktitan", 1800.0, now=now) is True
    # after the throttle window the source may warn again
    assert maybe_warn_source_latency("finviz", 1800.0, now=now + timedelta(seconds=301)) is True


@pytest.mark.unit
def test_fast_sources_exclude_finviz():
    """Finviz is secondary confirmation — fast wires must be scanned first."""
    import src.main as m

    assert "Finviz" not in m.FAST_NEWS_SOURCES
    for fast in ("StockTitan", "PRNewswire", "WireNews"):
        assert fast in m.FAST_NEWS_SOURCES
