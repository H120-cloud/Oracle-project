from datetime import datetime, timezone

from src.core.agentic.news_momentum_models import NewsEvent, NewsSource
from src.core.agentic.news_momentum_utils import deduplicate_news_items
from src.core.finviz_news import FinvizNewsItem


def test_news_event_normalizes_naive_datetimes_to_utc():
    event = NewsEvent(
        ticker="TST",
        headline="Test Company Wins Contract",
        source=NewsSource.FINVIZ,
        published_at=datetime(2026, 5, 28, 12, 0, 0),
        detected_at=datetime(2026, 5, 28, 12, 0, 1),
    )

    assert event.published_at.tzinfo is timezone.utc
    assert event.detected_at.tzinfo is timezone.utc


def test_deduplicate_handles_missing_and_aware_timestamps():
    items = [
        FinvizNewsItem(
            headline="Test Company Wins Contract",
            source="Finviz",
            url="https://example.test/a",
            timestamp=None,
        ),
        FinvizNewsItem(
            headline="Test Company Wins Contract",
            source="StockTitan",
            url="https://example.test/b",
            timestamp=datetime(2026, 5, 28, 12, 0, tzinfo=timezone.utc),
        ),
    ]

    deduped = deduplicate_news_items(items)

    # Same headline + same (empty) ticker key = same event. Per the documented
    # dedup contract, the TIMESTAMPED copy (StockTitan) must survive over the
    # None-timestamp Finviz row — otherwise the survivor would be dropped by the
    # downstream freshness filter, causing a missed alert. So: 1 item, and it's
    # the one carrying a real timestamp.
    assert len(deduped) == 1
    assert deduped[0].source == "StockTitan"
    assert deduped[0].timestamp is not None


def test_deduplicate_handles_naive_and_aware_timestamps():
    items = [
        FinvizNewsItem(
            headline="Test Company Wins Contract",
            source="Finviz",
            url="https://example.test/a",
            timestamp=datetime(2026, 5, 28, 12, 0),
        ),
        FinvizNewsItem(
            headline="Test Company Wins Contract",
            source="StockTitan",
            url="https://example.test/b",
            timestamp=datetime(2026, 5, 28, 12, 0, tzinfo=timezone.utc),
        ),
    ]

    deduped = deduplicate_news_items(items)

    assert len(deduped) == 1
