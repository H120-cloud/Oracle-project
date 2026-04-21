"""Tests for OrderFlowAnalyzer."""

import pytest
import numpy as np
from datetime import datetime, timedelta

from src.core.order_flow import OrderFlowAnalyzer
from src.models.schemas import OHLCVBar


def _make_bars(n=30, direction="bullish"):
    """Create bars with a given directional bias."""
    bars = []
    price = 100.0
    for i in range(n):
        if direction == "bullish":
            # Close near highs → estimated buy volume dominates
            o = price
            c = price + 0.5
            h = c + 0.1
            l = o - 0.1
            price = c
        elif direction == "bearish":
            # Close near lows → estimated sell volume dominates
            o = price
            c = price - 0.5
            h = o + 0.1
            l = c - 0.1
            price = c
        else:
            # Neutral: close in middle
            o = price
            c = price + 0.01
            h = price + 0.3
            l = price - 0.3
        bars.append(OHLCVBar(
            timestamp=datetime(2024, 1, 1, 9, 30) + timedelta(minutes=i),
            open=o, high=h, low=l, close=c, volume=100000,
        ))
    return bars


@pytest.fixture
def analyzer():
    return OrderFlowAnalyzer(lookback=20)


def test_bullish_flow(analyzer):
    bars = _make_bars(30, "bullish")
    result = analyzer.analyze(bars)
    assert result is not None
    assert result.bid_ask_imbalance > 1.0
    assert result.aggressive_buy_ratio > 0.5
    assert result.signal == "bullish"
    assert result.net_flow > 0


def test_bearish_flow(analyzer):
    bars = _make_bars(30, "bearish")
    result = analyzer.analyze(bars)
    assert result is not None
    assert result.bid_ask_imbalance < 1.0
    assert result.aggressive_sell_ratio > 0.5
    assert result.signal == "bearish"
    assert result.net_flow < 0


def test_neutral_flow(analyzer):
    bars = _make_bars(30, "neutral")
    result = analyzer.analyze(bars)
    assert result is not None
    assert result.signal == "neutral"


def test_not_enough_bars(analyzer):
    bars = _make_bars(5)
    result = analyzer.analyze(bars)
    assert result is None


def test_tape_speed(analyzer):
    bars = _make_bars(30, "bullish")
    result = analyzer.analyze(bars)
    assert result is not None
    assert result.tape_speed > 0
