"""Tests for MarketScanner."""

import pandas as pd
import pytest

from src.core.scanner import MarketScanner
from src.models.schemas import ScanFilter


@pytest.fixture
def sample_data():
    return pd.DataFrame([
        {"ticker": "AAPL", "price": 175.0, "volume": 2_000_000, "rvol": 2.5, "change_percent": 3.5, "market_cap": 2.8e12, "float_shares": 1.5e10},
        {"ticker": "TSLA", "price": 250.0, "volume": 5_000_000, "rvol": 3.1, "change_percent": 7.0, "market_cap": 8e11, "float_shares": 3e9},
        {"ticker": "PENNY", "price": 0.50, "volume": 10_000_000, "rvol": 5.0, "change_percent": 50.0, "market_cap": 1e7, "float_shares": 5e6},
        {"ticker": "LOW_VOL", "price": 50.0, "volume": 100_000, "rvol": 0.5, "change_percent": 1.0, "market_cap": 5e9, "float_shares": 1e8},
        {"ticker": "AMD", "price": 120.0, "volume": 3_000_000, "rvol": 1.8, "change_percent": -2.0, "market_cap": 2e11, "float_shares": 1.6e9},
    ])


def test_scan_top_volume(sample_data):
    scanner = MarketScanner(ScanFilter(min_price=1.0, max_price=500.0, min_volume=500_000, max_results=3))
    results = scanner.scan_top_volume(sample_data)
    assert len(results) <= 3
    assert results[0].ticker == "TSLA"
    assert all(r.scan_type == "volume" for r in results)


def test_scan_filters_out_penny(sample_data):
    scanner = MarketScanner(ScanFilter(min_price=1.0, max_price=500.0, min_volume=500_000))
    results = scanner.scan_top_volume(sample_data)
    tickers = [r.ticker for r in results]
    assert "PENNY" not in tickers


def test_scan_filters_out_low_volume(sample_data):
    scanner = MarketScanner(ScanFilter(min_price=1.0, max_price=500.0, min_volume=500_000))
    results = scanner.scan_top_volume(sample_data)
    tickers = [r.ticker for r in results]
    assert "LOW_VOL" not in tickers


def test_scan_top_rvol(sample_data):
    scanner = MarketScanner(ScanFilter(min_price=1.0, max_price=500.0, min_volume=500_000, max_results=2))
    results = scanner.scan_top_rvol(sample_data)
    assert len(results) <= 2
    assert results[0].ticker == "TSLA"  # highest rvol among qualifying


def test_scan_top_gainers(sample_data):
    scanner = MarketScanner(ScanFilter(min_price=1.0, max_price=500.0, min_volume=500_000, max_results=2))
    results = scanner.scan_top_gainers(sample_data)
    assert results[0].ticker == "TSLA"  # 7% > 3.5%


def test_scan_watchlist(sample_data):
    scanner = MarketScanner(ScanFilter(min_price=1.0, max_price=500.0, min_volume=500_000))
    results = scanner.scan_watchlist(sample_data, ["aapl", "AMD"])
    tickers = [r.ticker for r in results]
    assert "AAPL" in tickers
    assert "AMD" in tickers
    assert len(results) == 2
