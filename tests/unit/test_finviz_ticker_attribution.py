"""Ticker attribution should not pin a headline to Finviz's wrong tag when the
headline names the subject ticker explicitly (e.g. 'SIRI Stock Surges ...')."""

import pytest

from src.core.finviz_news import FinvizNewsScraper


@pytest.mark.unit
def test_prefers_explicit_headline_ticker_over_wrong_finviz_tag():
    result = FinvizNewsScraper._attribute_primary_tickers(
        ["MASI"], "SIRI Stock Surges 5% After-Hours On S&P MidCap 400 Inclusion"
    )
    assert result == ["SIRI"]


@pytest.mark.unit
def test_keeps_confirmed_finviz_tag_in_headline():
    result = FinvizNewsScraper._attribute_primary_tickers(
        ["AAPL", "NVDA"], "AAPL announces product; NVDA also mentioned"
    )
    assert "AAPL" in result


@pytest.mark.unit
def test_falls_back_to_first_tag_for_name_only_headline():
    # company name only, no explicit symbol → keep Finviz's best guess
    result = FinvizNewsScraper._attribute_primary_tickers(["TSLA"], "Tesla unveils new model")
    assert result == ["TSLA"]
