from __future__ import annotations

import asyncio

import pytest

from src.core.stocktitan_news import StockTitanScraper
from src.core.agentic.news_momentum_catalyst_classifier import classify_headline
from src.core.agentic.news_momentum_models import CatalystCategory, CatalystSubType


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


def test_stocktitan_extracts_bgms_plain_parentheses_and_preserves_description(monkeypatch):
    rss = f"""
    <rss><channel>
    {_rss_item(
        "Bio Green Med (BGMS) to acquire Future NRG in share exchange; control shifts",
        "https://www.stocktitan.net/news/latest-market-report.html",
        "Bio Green Med agreed on June 4, 2026 to acquire Future NRG via a share-for-share exchange; sellers would own ~99% pro forma.",
    )}
    </channel></rss>
    """

    async def fake_fetch(url: str, max_retries: int = 3):
        return _Response(rss)

    monkeypatch.setattr(StockTitanScraper, "_fetch_with_retry", staticmethod(fake_fetch))

    items = asyncio.run(StockTitanScraper()._parse_rss())

    assert len(items) == 1
    assert items[0].tickers == ["BGMS"]
    assert "share-for-share exchange" in items[0].description

    category, sub_type, is_negative, is_vague = classify_headline(
        f"{items[0].headline} {items[0].description}"
    )
    assert category == CatalystCategory.CORPORATE
    assert sub_type in {CatalystSubType.ACQUISITION, CatalystSubType.MERGER}
    assert is_negative is False
    assert is_vague is False


def test_stocktitan_resolves_company_name_when_no_explicit_ticker(monkeypatch):
    rss = f"""
    <rss><channel>
    {_rss_item(
        "Inotiv enters Chapter 11 to cut $326M debt, secure $65M financing",
        "https://www.stocktitan.net/news/inotiv-enters-chapter-11.html",
        "Plan backed by most lenders will trim $326M in debt while DIP and bridge funds keep operations running.",
    )}
    </channel></rss>
    """

    async def fake_fetch(url: str, max_retries: int = 3):
        return _Response(rss)

    monkeypatch.setattr(StockTitanScraper, "_fetch_with_retry", staticmethod(fake_fetch))
    monkeypatch.setattr(
        "src.core.stocktitan_news.resolve_company_ticker",
        lambda name: "NOTV" if name == "Inotiv" else None,
    )

    items = asyncio.run(StockTitanScraper()._parse_rss())

    assert len(items) == 1
    assert items[0].tickers == ["NOTV"]
    assert items[0].headline.startswith("Inotiv enters Chapter 11")
