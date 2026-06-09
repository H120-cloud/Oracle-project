"""Finviz v=6 (blogs) must parse the 2026 'market-pulse' layout.

Finviz changed v=6 so the real headline lives in <span class="market-pulse-headline">
and the anchors are ticker/performance badges. The old parser grabbed the first
<a> and so used "ABTS-39.20%" as the headline (useless to the catalyst classifier).
"""

import asyncio

import pytest

from src.core.finviz_news import FinvizNewsScraper

MARKET_PULSE_HTML = """
<table class="table-fixed">
  <tr>
    <td><span>icon</span></td>
    <td class="news_date-cell">44 min</td>
    <td class="news_link-cell">
      <div class="market-pulse-row-content">
        <span class="market-pulse-headline" title="ABTS surges after FDA approval of lead drug">ABTS surges after FDA approval of lead drug</span>
        <div class="market-pulse-badges">
          <a href="/quote.ashx?t=ABTS&amp;p=d">ABTS+39.20%</a>
        </div>
      </div>
    </td>
  </tr>
</table>
"""


@pytest.mark.unit
def test_finviz_v6_parses_market_pulse_headline(monkeypatch):
    scraper = FinvizNewsScraper()

    async def _fake_get(_url):
        return MARKET_PULSE_HTML

    monkeypatch.setattr(scraper, "_get", _fake_get)
    items = asyncio.run(scraper._fetch_blogs())

    assert len(items) == 1
    item = items[0]
    assert "FDA approval" in item.headline
    assert item.headline != "ABTS+39.20%"  # not the badge text
    assert "ABTS" in item.tickers
