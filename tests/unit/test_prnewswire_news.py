from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.core.prnewswire_news import parse_prnewswire_public_company_html


pytestmark = [pytest.mark.unit]


def test_prnewswire_extracts_plain_parentheses_ticker_from_finance_listing():
    html = """
    <html><body>
      <a href="/news-releases/company-announces-merger-302000000.html">
        08:45 ET ExampleCo (BGMS) announces merger with Future NRG
      </a>
    </body></html>
    """

    items = parse_prnewswire_public_company_html(
        html,
        now=datetime(2026, 6, 5, 13, 0, tzinfo=timezone.utc),
    )

    assert len(items) == 1
    assert items[0].tickers == ["BGMS"]
    assert "merger" in items[0].headline.lower()
