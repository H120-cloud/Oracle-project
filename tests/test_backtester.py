"""Tests for Backtester."""

import pytest
from datetime import datetime, timedelta
from unittest.mock import MagicMock

from src.core.backtester import Backtester
from src.models.schemas import OHLCVBar, BacktestConfig


def _trending_bars(n=80, start=100.0):
    """Uptrend with dip-and-bounce patterns for entry signals."""
    bars = []
    price = start
    pattern = [0.4, 0.4, 0.4, -0.2, -0.2]  # 3 up, 2 down
    for i in range(n):
        delta = pattern[i % len(pattern)]
        price += delta
        is_green = delta > 0
        vol = 120000 if is_green and i % 5 == 0 else 80000
        bars.append(OHLCVBar(
            timestamp=datetime(2024, 1, 1, 9, 30) + timedelta(minutes=i),
            open=price - delta,
            high=price + 0.2 if is_green else price - delta + 0.2,
            low=price - 0.2 if is_green else price - 0.2,
            close=price,
            volume=vol,
        ))
    return bars


class MockMarketData:
    """Mock market data provider that returns pre-built bars."""

    def __init__(self, bars):
        self._bars = bars

    def get_ohlcv(self, ticker, period=None, interval="1m", start=None, end=None):
        # Return all bars (mock doesn't filter by date)
        return self._bars


@pytest.fixture
def config():
    return BacktestConfig(
        ticker="TEST",
        start_date="2024-01-01",
        end_date="2024-01-31",
        initial_capital=10000.0,
    )


def test_backtest_returns_result(config):
    bars = _trending_bars(80)
    mock_data = MockMarketData(bars)
    bt = Backtester(market_data=mock_data, stop_pct=2.0, target_pct=4.0)
    result = bt.run(config)
    assert result is not None
    assert result.config.ticker == "TEST"
    assert result.total_return_pct is not None


def test_backtest_no_data(config):
    mock_data = MockMarketData([])
    bt = Backtester(market_data=mock_data)
    result = bt.run(config)
    assert result.total_trades == 0


def test_backtest_few_bars(config):
    bars = _trending_bars(10)
    mock_data = MockMarketData(bars)
    bt = Backtester(market_data=mock_data)
    result = bt.run(config)
    assert result.total_trades == 0


def test_backtest_stats_computed(config):
    bars = _trending_bars(80)
    mock_data = MockMarketData(bars)
    bt = Backtester(market_data=mock_data, stop_pct=1.5, target_pct=3.0)
    result = bt.run(config)
    # Stats should be populated if trades occurred
    if result.total_trades > 0:
        assert result.win_rate >= 0
        assert result.max_drawdown_pct >= 0
        assert result.profit_factor >= 0
