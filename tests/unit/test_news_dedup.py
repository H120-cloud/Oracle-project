"""
Unit tests for news cross-source deduplication utility.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.core.agentic.news_momentum_utils import _normalize_headline, deduplicate_news_items
from src.core.finviz_news import FinvizNewsItem

pytestmark = [pytest.mark.unit]


class TestNormalizeHeadline:
    def test_strip_ticker_suffix(self):
        h = "Apple reports record earnings | AAPL Stock News"
        assert _normalize_headline(h) == "apple reports record earnings"

    def test_lowercase_and_strip(self):
        h = "  Tesla Announces NEW Battery Tech  "
        assert _normalize_headline(h) == "tesla announces new battery tech"

    def test_collapse_multiple_spaces(self):
        h = "NVDA    partners    with   Microsoft"
        assert _normalize_headline(h) == "nvda partners with microsoft"


class TestDeduplicateNewsItems:
    def test_keeps_earliest_timestamp(self):
        base = datetime(2026, 5, 27, 12, 0, tzinfo=timezone.utc)
        items = [
            FinvizNewsItem(
                headline="Tesla reports earnings",
                source="Finviz",
                url="http://f.com/1",
                timestamp=base + timedelta(hours=1),
                tickers=["TSLA"],
            ),
            FinvizNewsItem(
                headline="Tesla reports earnings",
                source="StockTitan",
                url="http://st.com/1",
                timestamp=base,
                tickers=["TSLA"],
            ),
        ]
        result = deduplicate_news_items(items)
        assert len(result) == 1
        assert result[0].source == "StockTitan"  # earliest
        assert result[0].timestamp == base

    def test_prefers_faster_source_on_tie(self):
        """On timestamp ties, prefer historically-faster source (StockTitan)."""
        base = datetime(2026, 5, 27, 12, 0, tzinfo=timezone.utc)
        items = [
            FinvizNewsItem(
                headline="Apple buys startup",
                source="Finviz",
                url="http://f.com/1",
                timestamp=base,
                tickers=["AAPL"],
            ),
            FinvizNewsItem(
                headline="Apple buys startup",
                source="StockTitan",
                url="http://st.com/1",
                timestamp=base,
                tickers=["AAPL"],
            ),
        ]
        result = deduplicate_news_items(items)
        assert len(result) == 1
        assert result[0].source == "StockTitan"

    def test_normalizes_headlines_before_comparison(self):
        base = datetime(2026, 5, 27, 12, 0, tzinfo=timezone.utc)
        items = [
            FinvizNewsItem(
                headline="NVDA Stock Surges | NVDA Stock News",
                source="StockTitan",
                url="http://st.com/1",
                timestamp=base,
                tickers=["NVDA"],
            ),
            FinvizNewsItem(
                headline="nvda stock surges",
                source="Finviz",
                url="http://f.com/1",
                timestamp=base + timedelta(hours=1),
                tickers=["NVDA"],
            ),
        ]
        result = deduplicate_news_items(items)
        assert len(result) == 1
        # Earliest wins despite different raw headline strings
        assert result[0].source == "StockTitan"

    def test_dedupes_within_1h_window(self):
        """Identical headlines 1 hour apart should be deduped (default 24h window)."""
        base = datetime(2026, 5, 27, 12, 0, tzinfo=timezone.utc)
        items = [
            FinvizNewsItem(
                headline="Partnership announced",
                source="StockTitan",
                url="http://st.com/1",
                timestamp=base,
                tickers=["XYZ"],
            ),
            FinvizNewsItem(
                headline="Partnership announced",
                source="Finviz",
                url="http://f.com/1",
                timestamp=base + timedelta(hours=1),
                tickers=["XYZ"],
            ),
        ]
        result = deduplicate_news_items(items)
        assert len(result) == 1
        assert result[0].timestamp == base  # earliest kept

    def test_no_dedup_beyond_24h_window(self):
        """Identical headlines 48 hours apart should NOT be deduped with default window."""
        base = datetime(2026, 5, 27, 12, 0, tzinfo=timezone.utc)
        items = [
            FinvizNewsItem(
                headline="Company X announces partnership",
                source="StockTitan",
                url="http://st.com/1",
                timestamp=base,
                tickers=["XYZ"],
            ),
            FinvizNewsItem(
                headline="Company X announces partnership",
                source="Finviz",
                url="http://f.com/1",
                timestamp=base + timedelta(hours=48),
                tickers=["XYZ"],
            ),
        ]
        result = deduplicate_news_items(items)
        assert len(result) == 2

    def test_window_override_works(self):
        """A 48-hour window should dedupe items 30h apart."""
        base = datetime(2026, 5, 27, 12, 0, tzinfo=timezone.utc)
        items = [
            FinvizNewsItem(
                headline="Contract awarded",
                source="StockTitan",
                url="http://st.com/1",
                timestamp=base,
                tickers=["ABC"],
            ),
            FinvizNewsItem(
                headline="Contract awarded",
                source="Finviz",
                url="http://f.com/1",
                timestamp=base + timedelta(hours=30),
                tickers=["ABC"],
            ),
        ]
        result = deduplicate_news_items(items, window_hours=48)
        assert len(result) == 1
        result_narrow = deduplicate_news_items(items, window_hours=24)
        assert len(result_narrow) == 2

    def test_empty_list(self):
        assert deduplicate_news_items([]) == []

    def test_no_duplicates(self):
        base = datetime(2026, 5, 27, 12, 0, tzinfo=timezone.utc)
        items = [
            FinvizNewsItem(
                headline="Tesla reports earnings",
                source="Finviz",
                url="http://f.com/1",
                timestamp=base,
                tickers=["TSLA"],
            ),
            FinvizNewsItem(
                headline="Apple buys startup",
                source="Finviz",
                url="http://f.com/2",
                timestamp=base,
                tickers=["AAPL"],
            ),
        ]
        result = deduplicate_news_items(items)
        assert len(result) == 2
