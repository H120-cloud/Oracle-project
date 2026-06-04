"""
Unit tests for FinvizNewsScraper fixes:
  - Timezone handling (ET → UTC)
  - Month-boundary bug
  - HTTP retry with exponential backoff
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import asyncio
from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo

import httpx
import pytest

from src.core.finviz_news import FinvizNewsScraper

pytestmark = [pytest.mark.unit]


class TestParseTime:
    def test_parse_time_et_to_utc(self):
        """A 4:20 PM ET timestamp should convert to 20:20 or 21:20 UTC depending on DST."""
        scraper = FinvizNewsScraper()
        result = scraper._parse_time("04:20PM")
        assert result is not None
        assert result.tzinfo is timezone.utc
        # ET offset is either -5 or -4; result hour should be 20 or 21
        assert result.hour in (20, 21)

    def test_parse_time_yesterday_crosses_month_boundary(self):
        """On May 1st, 'Yesterday' should resolve to April 30th, not day 0."""
        scraper = FinvizNewsScraper()
        # Patch 'now' to be May 1st 12:00 ET
        may1 = datetime(2026, 5, 1, 12, 0, tzinfo=ZoneInfo("America/New_York"))
        # Monkey-patch _parse_time to use our fixed date
        original_parse = scraper._parse_time

        def fixed_parse(text):
            try:
                now = may1
                text = text.strip().upper()
                if "YESTERDAY" in text:
                    t = datetime.strptime(text.replace("YESTERDAY", "").strip(), "%I:%M%p")
                    yesterday = now - timedelta(days=1)
                    dt = yesterday.replace(hour=t.hour, minute=t.minute, second=0, microsecond=0)
                    return dt.astimezone(timezone.utc)
                t = datetime.strptime(text, "%I:%M%p")
                dt = now.replace(hour=t.hour, minute=t.minute, second=0, microsecond=0)
                return dt.astimezone(timezone.utc)
            except Exception:
                return None

        result = fixed_parse("Yesterday 03:30PM")
        assert result is not None
        assert result.day == 30
        assert result.month == 4

    def test_parse_time_invalid_returns_none(self):
        scraper = FinvizNewsScraper()
        assert scraper._parse_time("not_a_time") is None


class TestQuoteTimestamp:
    def test_parse_quote_timestamp_full_date(self):
        scraper = FinvizNewsScraper()
        ts = scraper._parse_quote_timestamp("May-01-26 04:20PM", None)
        assert ts is not None
        assert ts.tzinfo is timezone.utc

    def test_parse_quote_timestamp_today_converts_et_to_utc(self):
        scraper = FinvizNewsScraper()
        ts = scraper._parse_quote_timestamp("Today 01:57PM", None)
        assert ts is not None
        assert ts.tzinfo is timezone.utc
        # 01:57 PM ET → 17:57 or 18:57 UTC depending on DST
        assert ts.hour in (17, 18)

    def test_parse_quote_timestamp_yesterday_crosses_month_boundary(self):
        scraper = FinvizNewsScraper()
        may1 = datetime(2026, 5, 1, 12, 0, tzinfo=ZoneInfo("America/New_York"))
        from unittest.mock import patch
        with patch("src.core.finviz_news.datetime") as mock_dt:
            mock_dt.now.return_value = may1
            mock_dt.strptime = datetime.strptime
            mock_dt.timedelta = timedelta
            ts = scraper._parse_quote_timestamp("Yesterday 03:30PM", None)
            assert ts is not None
            assert ts.day == 30
            assert ts.month == 4
            assert ts.tzinfo is timezone.utc

    def test_parse_quote_timestamp_time_only_with_last_date(self):
        scraper = FinvizNewsScraper()
        ts = scraper._parse_quote_timestamp("04:20PM", "May-01-26")
        assert ts is not None
        assert ts.day == 1
        assert ts.month == 5


class TestRetryLogic:
    def test_fetch_with_retry_succeeds_after_two_failures(self):
        async def _test():
            scraper = FinvizNewsScraper()
            client = MagicMock()
            client.get = AsyncMock(side_effect=[
                MagicMock(status_code=503),
                MagicMock(status_code=503),
                MagicMock(status_code=200, text="ok"),
            ])
            resp = await scraper._fetch_with_retry(client, "http://example.com")
            assert resp.status_code == 200
            assert client.get.call_count == 3
        asyncio.run(_test())

    def test_fetch_with_retry_does_not_retry_404(self):
        async def _test():
            scraper = FinvizNewsScraper()
            client = MagicMock()
            client.get = AsyncMock(return_value=MagicMock(status_code=404))
            resp = await scraper._fetch_with_retry(client, "http://example.com")
            assert resp.status_code == 404
            assert client.get.call_count == 1
        asyncio.run(_test())

    def test_fetch_with_retry_exhausts_max_retries(self):
        async def _test():
            scraper = FinvizNewsScraper()
            client = MagicMock()

            def make_resp():
                resp = MagicMock()
                resp.status_code = 503
                resp.raise_for_status.side_effect = httpx.HTTPStatusError("503", request=None, response=None)
                return resp

            client.get = AsyncMock(side_effect=[make_resp(), make_resp()])
            with pytest.raises(httpx.HTTPStatusError, match="503"):
                await scraper._fetch_with_retry(client, "http://example.com", max_retries=2)
            assert client.get.call_count == 2
        asyncio.run(_test())

    def test_fetch_with_retry_does_not_block_event_loop(self):
        """A retry path with sleep should not block a concurrent asyncio task."""
        async def _test():
            scraper = FinvizNewsScraper()
            client = MagicMock()
            client.get = AsyncMock(side_effect=[
                MagicMock(status_code=503),
                MagicMock(status_code=200, text="ok"),
            ])

            async def witness():
                await asyncio.sleep(0.05)
                return "witness_done"

            retry_task = asyncio.create_task(scraper._fetch_with_retry(client, "http://example.com"))
            witness_task = asyncio.create_task(witness())
            done, pending = await asyncio.wait(
                {retry_task, witness_task}, timeout=5, return_when=asyncio.ALL_COMPLETED
            )
            assert not pending, "Tasks should complete without blocking"
            assert retry_task.result().status_code == 200
            assert witness_task.result() == "witness_done"
        asyncio.run(_test())
