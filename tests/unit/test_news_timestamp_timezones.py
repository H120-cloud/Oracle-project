"""Timestamp normalization regression tests (Amsterdam-server context).

All news timestamps must be normalized to UTC using the SOURCE's true timezone
(Finviz=US/Eastern, RSS=their stated zone, naive RSS=UTC) — never the server's
local timezone. The production server runs in Europe/Amsterdam; nothing here
may depend on that.
"""

import re
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

import src.core.finviz_news as fn

UTC = timezone.utc
FIXED_NOW_UTC = datetime(2026, 6, 10, 14, 30, tzinfo=UTC)  # 10:30 EDT


class FakeDateTime(datetime):
    """datetime with a pinned aware 'now' — host timezone cannot leak in."""

    @classmethod
    def now(cls, tz=None):
        return FIXED_NOW_UTC.astimezone(tz) if tz else FIXED_NOW_UTC.replace(tzinfo=None)


@pytest.fixture
def scraper(monkeypatch):
    monkeypatch.setattr(fn, "datetime", FakeDateTime)
    return fn.FinvizNewsScraper()


# ── Finviz US/Eastern normalization + DST edges ──────────────────────────────

@pytest.mark.unit
def test_finviz_absolute_time_is_eastern_summer(scraper):
    # 2026-03-15 is EDT (UTC-4): 4:20PM ET == 20:20 UTC
    parsed = scraper._parse_time("MAR-15-26 04:20PM")
    assert parsed == datetime(2026, 3, 15, 20, 20, tzinfo=UTC)


@pytest.mark.unit
def test_finviz_absolute_time_is_eastern_winter_dst_edge(scraper):
    # 2026-01-15 is EST (UTC-5): 4:20PM ET == 21:20 UTC — DST pair with above
    parsed = scraper._parse_time("JAN-15-26 04:20PM")
    assert parsed == datetime(2026, 1, 15, 21, 20, tzinfo=UTC)


@pytest.mark.unit
def test_finviz_date_only_is_midnight_eastern(scraper):
    parsed = scraper._parse_time("MAR-15-26")
    assert parsed == datetime(2026, 3, 15, 4, 0, tzinfo=UTC)  # 00:00 EDT


@pytest.mark.unit
def test_finviz_relative_minutes(scraper):
    parsed = scraper._parse_time("12 MIN")
    assert parsed == FIXED_NOW_UTC.replace(minute=18)


@pytest.mark.unit
def test_finviz_time_only_rolls_back_when_future(scraper):
    # now = 10:30 ET; '04:20PM' today would be the future → prior day
    parsed = scraper._parse_time("04:20PM")
    assert parsed == datetime(2026, 6, 9, 20, 20, tzinfo=UTC)


@pytest.mark.unit
def test_all_finviz_outputs_are_aware_utc(scraper):
    for text in ("2 HOURS AGO", "MAR-15-26 04:20PM", "MAR-15-26", "TODAY 09:00AM"):
        parsed = scraper._parse_time(text)
        assert parsed is not None and parsed.tzinfo is not None
        assert parsed.utcoffset().total_seconds() == 0


# ── server-timezone independence ─────────────────────────────────────────────

@pytest.mark.unit
def test_server_timezone_cannot_affect_parsing(scraper):
    """With 'now' pinned to an aware instant, parsing is deterministic — and a
    policy sweep proves no parser consults the host timezone at all."""
    assert scraper._parse_time("2 HOURS AGO") == FIXED_NOW_UTC.replace(hour=12)

    naive_now = re.compile(
        r"datetime\.now\(\)|datetime\.utcnow\(\)|\.astimezone\(\)|time\.localtime|fromtimestamp\((?!.*tz)"
    )
    for module in ("finviz_news", "stocktitan_news", "prnewswire_news",
                   "investing_news", "wire_news", "sharecast_news"):
        text = Path(f"src/core/{module}.py").read_text(encoding="utf-8")
        assert not naive_now.search(text), f"{module} uses host-local time"


# ── UTC headlines (RSS sources) ──────────────────────────────────────────────

@pytest.mark.unit
def test_wire_rss_gmt_timestamp_normalizes_to_utc():
    from src.core.wire_news import _parse_timestamp
    parsed = _parse_timestamp("Wed, 10 Jun 2026 09:45 GMT")
    assert parsed == datetime(2026, 6, 10, 9, 45, tzinfo=UTC)


@pytest.mark.unit
def test_investing_naive_pubdate_assumed_utc_not_server_local():
    from src.core.investing_news import _parse_pubdate
    parsed = _parse_pubdate("2026-06-08 19:33:10")
    assert parsed == datetime(2026, 6, 8, 19, 33, 10, tzinfo=UTC)


# ── whole-hour relative times: sanitized via confidence, not trusted ─────────

@pytest.mark.unit
def test_hour_granular_relative_times_get_low_confidence(scraper):
    # 'N hours ago' is ±30min data — must not carry second-precision confidence.
    parsed, conf = scraper._parse_time_with_confidence("4 HOURS AGO")
    assert parsed == FIXED_NOW_UTC.replace(hour=10)
    assert conf == "LOW"
    _, conf_day = scraper._parse_time_with_confidence("2 DAYS AGO")
    assert conf_day == "LOW"


@pytest.mark.unit
def test_minute_and_absolute_times_keep_high_confidence(scraper):
    _, conf_min = scraper._parse_time_with_confidence("12 MIN")
    assert conf_min == "HIGH"
    _, conf_abs = scraper._parse_time_with_confidence("MAR-15-26 04:20PM")
    assert conf_abs == "HIGH"


@pytest.mark.unit
def test_date_only_gets_low_confidence(scraper):
    _, conf = scraper._parse_time_with_confidence("MAR-15-26")
    assert conf == "LOW"


# ── stale/fresh classification anchored to normalized UTC ────────────────────

@pytest.mark.unit
def test_naive_timestamps_are_interpreted_as_utc_downstream():
    from src.core.agentic.news_alert_latency_trace import aware_utc
    naive = datetime(2026, 6, 10, 14, 0)
    assert aware_utc(naive) == datetime(2026, 6, 10, 14, 0, tzinfo=UTC)
    # aware non-UTC input converts, never re-labels
    ams = datetime(2026, 6, 10, 16, 0, tzinfo=ZoneInfo("Europe/Amsterdam"))
    assert aware_utc(ams) == datetime(2026, 6, 10, 14, 0, tzinfo=UTC)
