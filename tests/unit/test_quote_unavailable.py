"""Failed quote fetches must signal unavailability (None), never a fake $0 quote.

Regression coverage for the zero-price sentinel bug: providers used to return
``{"price": 0, ...}`` on failure, which downstream code could mistake for a real
quote. Failed fetches now return ``None``.
"""

import asyncio

import pytest

import src.services.market_data as md


class _AlwaysRateLimited:
    """Stand-in provider whose inner fetch always raises a 429-style error."""

    def _get_live_quote_inner(self, ticker: str) -> dict:
        raise Exception("429 too many requests")


@pytest.fixture(autouse=True)
def _no_sleep_no_backoff(monkeypatch):
    """Keep retry tests fast and deterministic."""
    monkeypatch.setattr(md.time, "sleep", lambda *a, **k: None)
    md._rate_limit_backoff_until = 0.0
    yield
    md._rate_limit_backoff_until = 0.0


@pytest.mark.unit
def test_retry_returns_none_after_rate_limit_exhaustion():
    result = md._get_live_quote_with_retry(_AlwaysRateLimited(), "AAA", max_retries=2)
    assert result is None


@pytest.mark.unit
def test_retry_never_returns_fake_zero_price():
    result = md._get_live_quote_with_retry(_AlwaysRateLimited(), "AAA", max_retries=2)
    # The old bug returned {"price": 0, ...}; guard against it explicitly.
    assert not (isinstance(result, dict) and result.get("price") == 0)


@pytest.mark.unit
def test_yfinance_get_live_quote_returns_none_on_failure(monkeypatch):
    class _NoCache:
        def get(self, key):
            return None

        def set(self, *a, **k):
            return None

    monkeypatch.setattr(md, "get_cache", lambda: _NoCache())
    prov = md.YFinanceProvider()

    def _boom(ticker):
        raise Exception("429 too many requests")

    monkeypatch.setattr(prov, "_get_live_quote_inner", _boom)
    assert prov.get_live_quote("AAA") is None


@pytest.mark.unit
def test_finnhub_get_live_quote_returns_none_on_failure(monkeypatch):
    class _NoCache:
        def get(self, key):
            return None

        def set(self, *a, **k):
            return None

    class _RaisingClient:
        def quote(self, *a, **k):
            raise Exception("connection refused")

    monkeypatch.setattr(md, "get_cache", lambda: _NoCache())
    prov = object.__new__(md.FinnhubProvider)  # bypass __init__ (needs API key)
    prov.client = _RaisingClient()
    assert prov.get_live_quote("AAA") is None


@pytest.mark.unit
def test_alphavantage_get_live_quote_returns_none_on_empty(monkeypatch):
    import pandas as pd
    from src.services import alphavantage_provider as av

    class _Client:
        def intraday(self, *a, **k):
            return pd.DataFrame()  # no bars

    prov = object.__new__(av.AlphaVantageProvider)
    prov.client = _Client()
    assert prov.get_live_quote("AAA") is None


@pytest.mark.unit
def test_polygon_get_live_quote_returns_none_without_bars(monkeypatch):
    from src.services import polygon_provider as pg

    prov = object.__new__(pg.PolygonProvider)
    prov._quote_cache = {}
    prov._ttl_seconds = 0
    monkeypatch.setattr(prov, "get_ohlcv", lambda *a, **k: [], raising=False)
    assert prov.get_live_quote("AAA") is None


@pytest.mark.unit
def test_alpaca_get_live_quote_returns_none_on_failure(monkeypatch):
    from src.services import alpaca_provider as ap

    class _DataClient:
        def get_stock_snapshot(self, *a, **k):
            raise Exception("boom")

    prov = object.__new__(ap.AlpacaProvider)
    prov.data_feed = "iex"
    prov.data_client = _DataClient()
    assert prov.get_live_quote("AAA") is None


@pytest.mark.unit
def test_news_quote_route_returns_503_when_unavailable(monkeypatch):
    import src.api.routes.news as news_mod

    class _UnavailableProvider:
        def get_live_quote(self, ticker):
            return None

    monkeypatch.setattr(news_mod, "_market_data_provider", _UnavailableProvider())

    from fastapi import HTTPException

    with pytest.raises(HTTPException) as excinfo:
        asyncio.run(news_mod.get_news_quote("AAA"))
    assert excinfo.value.status_code == 503
