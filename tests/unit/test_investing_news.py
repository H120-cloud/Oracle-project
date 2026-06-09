"""Investing.com RSS scraper: ticker extraction + macro-headline filtering."""

import pytest

SAMPLE_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
<item>
  <title>Why is Zevra Therapeutics stock surging today?</title>
  <link>https://www.investing.com/news/stock-market-news/zevra-1</link>
  <pubDate>2026-06-08 19:33:10</pubDate>
</item>
<item>
  <title>Tesla (NASDAQ:TSLA) ramps production at new plant</title>
  <link>https://www.investing.com/news/stock-market-news/tsla-2</link>
  <pubDate>2026-06-08 19:30:00</pubDate>
</item>
<item>
  <title>FTSE 100 falls as oil prices slide</title>
  <link>https://www.investing.com/news/stock-market-news/ftse-3</link>
  <pubDate>2026-06-08 19:00:00</pubDate>
</item>
</channel></rss>"""


def _fake_resolve(name):
    return {"Zevra Therapeutics": "ZVRA"}.get(name)


@pytest.mark.unit
def test_extract_company_name():
    from src.core.investing_news import _extract_company_name

    assert _extract_company_name("Why is Zevra Therapeutics stock surging today?") == "Zevra Therapeutics"
    assert _extract_company_name("Aclara Resources stock ticks up on funding") == "Aclara Resources"
    # "shareholders" must NOT trigger the "shares" anchor
    assert _extract_company_name("ISS urges Warner Bros shareholders to reject pay") is None
    assert _extract_company_name("Vale CEO sees strong metals demand") is None


@pytest.mark.unit
def test_parse_investing_rss_extracts_tickers_and_drops_macro():
    from src.core.investing_news import parse_investing_rss

    items = parse_investing_rss(SAMPLE_RSS, resolve=_fake_resolve)
    tickers = {t for it in items for t in it.tickers}

    assert "ZVRA" in tickers, "company-name resolution failed"
    assert "TSLA" in tickers, "explicit (NASDAQ:TSLA) extraction failed"
    assert all("FTSE" not in it.headline for it in items), "macro headline should be dropped (no US ticker)"

    z = next(it for it in items if "ZVRA" in it.tickers)
    assert z.source == "Investing"
    assert z.timestamp is not None


@pytest.mark.unit
def test_parse_handles_empty_or_garbage_without_raising():
    from src.core.investing_news import parse_investing_rss

    assert parse_investing_rss("", resolve=_fake_resolve) == []
    assert parse_investing_rss("<not-xml", resolve=_fake_resolve) == []
