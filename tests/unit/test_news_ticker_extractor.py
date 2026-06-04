from __future__ import annotations

from src.core.news_ticker_extractor import extract_tickers, extract_tickers_from_url


def test_extracts_veru_stocktitan_exchange_format():
    headline = "Veru (NASDAQ: VERU) secures Novo Nordisk Wegovy supply for Phase 2b obesity trial"

    assert extract_tickers(headline) == ["VERU"]


def test_extracts_stocktitan_sec_filings_url_format():
    url = "https://www.stocktitan.net/sec-filings/VERU/8-k-veru-inc-reports-material-event.html"

    assert extract_tickers_from_url(url) == ["VERU"]


def test_extracts_stocktitan_news_url_format():
    url = "https://www.stocktitan.net/news/STI/solidion-technology-announces-contract.html"

    assert extract_tickers_from_url(url) == ["STI"]


def test_extracts_prnewswire_exchange_format():
    text = "08:45 ET Company Announces Strategic Partnership (NASDAQ: PRFX)"

    assert extract_tickers(text) == ["PRFX"]


def test_extracts_cashtag_and_suffix_without_noise_words():
    text = "$OLOX announces acquisition update | NEWS Stock News"

    assert extract_tickers(text) == ["OLOX"]


def test_plain_parentheses_only_when_requested():
    text = "Sharecast item references Olenox Industries (OLOX)"

    assert extract_tickers(text) == []
    assert extract_tickers(text, include_plain_parens=True) == ["OLOX"]
