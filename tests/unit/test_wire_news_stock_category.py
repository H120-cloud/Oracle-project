"""GlobeNewswire RSS carries tickers in <category domain="...rss/stock"> tags,
not in the headline text. The parser must read them or every item is dropped."""

import pytest

from src.core.wire_news import parse_wire_feed_html

GNW_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:dc="http://purl.org/dc/elements/1.1/"><channel>
<item>
  <guid isPermaLink="true">https://www.globenewswire.com/news-release/2026/06/10/x.html</guid>
  <link>https://www.globenewswire.com/news-release/2026/06/10/x.html</link>
  <category domain="https://www.globenewswire.com/rss/stock">Nasdaq:GENK</category>
  <category domain="https://www.globenewswire.com/rss/ISIN">US36870C1045</category>
  <title>GEN Restaurant Group Signs Distribution Agreement with United Natural Foods, Inc.</title>
  <description><![CDATA[GEN Restaurant Group Signs Distribution Agreement with United Natural Foods, Inc.]]></description>
  <pubDate>Wed, 10 Jun 2026 09:45 GMT</pubDate>
</item>
<item>
  <link>https://www.globenewswire.com/news-release/2026/06/10/y.html</link>
  <title>Some Private Company Announces a Thing</title>
  <description><![CDATA[No ticker anywhere]]></description>
  <pubDate>Wed, 10 Jun 2026 09:50 GMT</pubDate>
</item>
</channel></rss>"""


@pytest.mark.unit
def test_ticker_extracted_from_stock_category_tag():
    items = parse_wire_feed_html(GNW_RSS, source="GlobeNewswire", base_url="https://www.globenewswire.com")
    assert len(items) == 1, "tickered item kept, untickered dropped"
    item = items[0]
    assert item.tickers == ["GENK"]
    # headline should be the title, not title+description concatenated twice
    assert item.headline == "GEN Restaurant Group Signs Distribution Agreement with United Natural Foods, Inc."
    assert item.timestamp is not None


@pytest.mark.unit
def test_isin_category_not_mistaken_for_ticker():
    items = parse_wire_feed_html(GNW_RSS, source="GlobeNewswire", base_url="https://www.globenewswire.com")
    assert "US36870C1045" not in items[0].tickers
