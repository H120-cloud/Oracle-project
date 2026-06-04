from __future__ import annotations

import pytest

from src.core.wire_news import WireNewsScraper


class _Response:
    def __init__(self, text: str = ""):
        self.text = text

    def raise_for_status(self):
        return None


class _Client:
    def __init__(self, responses):
        self.responses = responses

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def get(self, url):
        value = self.responses[url]
        if isinstance(value, Exception):
            raise value
        return _Response(value)


@pytest.mark.asyncio
async def test_wire_scraper_reports_failed_source_even_when_other_source_succeeds(monkeypatch):
    businesswire_url = "https://businesswire.test/rss"
    globe_url = "https://globe.test/rss"
    monkeypatch.setattr(
        "src.core.wire_news.DEFAULT_WIRE_FEEDS",
        {
            "BusinessWire": [businesswire_url],
            "GlobeNewswire": [globe_url],
        },
    )
    monkeypatch.setattr(
        "src.core.wire_news.httpx.AsyncClient",
        lambda **kwargs: _Client(
            {
                businesswire_url: TimeoutError("businesswire timeout"),
                globe_url: (
                    "<rss><channel><item>"
                    "<title>TestCo Announces Contract (NASDAQ: TCO)</title>"
                    "<pubDate>Thu, 04 Jun 2026 12:00:00 GMT</pubDate>"
                    "<link>https://example.test/news/TCO</link>"
                    "</item></channel></rss>"
                ),
            }
        ),
    )

    summary = await WireNewsScraper(sources=["BusinessWire", "GlobeNewswire"]).fetch_all(force_refresh=True)

    assert len(summary.news_items) == 1
    assert getattr(summary, "failed_sources") == {"BusinessWire": 1}
