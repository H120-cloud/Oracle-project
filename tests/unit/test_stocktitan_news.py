from __future__ import annotations

import asyncio

import pytest

from src.core.stocktitan_news import StockTitanScraper


pytestmark = [pytest.mark.unit]


class _Response:
    status_code = 200

    def __init__(self, text: str):
        self.text = text

    def raise_for_status(self):
        return None


def _rss_item(title: str, link: str, description: str = "") -> str:
    return f"""
    <item>
      <title>{title}</title>
      <link>{link}</link>
      <description>{description}</description>
      <pubDate>Thu, 04 Jun 2026 12:00:00 GMT</pubDate>
    </item>
    """


def test_stocktitan_extracts_veru_exchange_title(monkeypatch):
    rss = f"""
    <rss><channel>
    {_rss_item(
        "Veru (NASDAQ: VERU) secures Novo Nordisk Wegovy supply for Phase 2b obesity trial",
        "https://www.stocktitan.net/sec-filings/VERU/8-k-veru-inc-reports-material-event.html",
        "Veru Inc. entered a clinical supply agreement with Novo Nordisk A/S.",
    )}
    </channel></rss>
    """

    async def fake_fetch(url: str, max_retries: int = 3):
        return _Response(rss)

    monkeypatch.setattr(StockTitanScraper, "_fetch_with_retry", staticmethod(fake_fetch))

    items = asyncio.run(StockTitanScraper()._parse_rss())

    assert len(items) == 1
    assert items[0].tickers == ["VERU"]
    assert "Novo Nordisk" in items[0].headline


def test_stocktitan_extracts_ticker_from_sec_filings_url_when_title_has_no_suffix(monkeypatch):
    rss = f"""
    <rss><channel>
    {_rss_item(
        "Company files material event report",
        "https://www.stocktitan.net/sec-filings/STI/8-k-solidion-technology-material-event.html",
    )}
    </channel></rss>
    """

    async def fake_fetch(url: str, max_retries: int = 3):
        return _Response(rss)

    monkeypatch.setattr(StockTitanScraper, "_fetch_with_retry", staticmethod(fake_fetch))

    items = asyncio.run(StockTitanScraper()._parse_rss())

    assert len(items) == 1
    assert items[0].tickers == ["STI"]
