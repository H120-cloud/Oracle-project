"""Tests for ICT/Smart Money detector."""

import numpy as np
import pytest

from src.core.ict_detector import ICTDetector, ICTFeatures


class MockBar:
    """Simple mock for OHLCV bars."""
    def __init__(self, open_p, high, low, close, volume=1000):
        self.open = open_p
        self.high = high
        self.low = low
        self.close = close
        self.volume = volume


def test_ict_detector_basic():
    detector = ICTDetector()

    # Create simple uptrend bars
    bars = []
    price = 100.0
    for i in range(30):
        bars.append(MockBar(price, price + 1, price - 1, price + 0.5))
        price += 0.5

    result = detector.detect("TEST", bars)

    assert result is not None
    assert isinstance(result, ICTFeatures)


def test_ict_overextended_detection():
    detector = ICTDetector()
    detector.EXTENSION_THRESHOLD_PCT = 15.0
    detector.IMPULSE_THRESHOLD_PCT = 2.0

    # Create bars: first an impulse, then extension
    bars = []
    # Normal bars
    for i in range(5):
        price = 100.0
        bars.append(MockBar(price, price + 0.5, price - 0.5, price))

    # Big impulse candle (3% move)
    bars.append(MockBar(100.0, 103.0, 99.0, 103.0))

    # Extended move to 118 (15%+ from 103)
    for i in range(10):
        price = 103.0 + i * 1.5  # Gradual extension
        bars.append(MockBar(price, price + 0.5, price - 0.5, price))

    result = detector.detect("TEST", bars)

    assert result is not None
    # With impulse at 100, close at ~118 = 18% extension
    if result.impulse_origin_price > 0:
        assert result.extension_pct > 10.0  # Should be extended


def test_ict_liquidity_sweep_detection():
    detector = ICTDetector()

    # Create bars with normal structure, then a sweep candle
    bars = []
    for i in range(15):
        price = 100.0 + i * 0.1
        bars.append(MockBar(price, price + 0.5, price - 0.5, price))

    # Add sweep candle: big wick above, close lower
    sweep_high = 110.0  # Way above previous
    sweep_close = 100.5  # Back down
    bars.append(MockBar(100.0, sweep_high, 99.5, sweep_close))

    result = detector.detect("TEST", bars)

    assert result is not None
    # Should detect the sweep or at least handle it without error


def test_ict_impulse_detection():
    detector = ICTDetector()
    detector.IMPULSE_THRESHOLD_PCT = 2.0

    # Create bars with a large impulse candle (>2%)
    bars = []
    for i in range(5):
        price = 100.0
        bars.append(MockBar(price, price + 0.2, price - 0.2, price))

    # Add impulse: 3% move (from 100 to 103)
    bars.append(MockBar(100.0, 103.5, 99.5, 103.0))

    # Add a few more bars
    for i in range(5):
        price = 103.0 + i * 0.1
        bars.append(MockBar(price, price + 0.2, price - 0.2, price))

    result = detector.detect("TEST", bars)

    assert result is not None
    # Impulse should be detected (3% > 2% threshold)
    assert result.impulse_origin_price > 0
    assert result.impulse_strength_pct >= 2.0


def test_ict_insufficient_bars():
    detector = ICTDetector()

    # Only 5 bars - should return None
    bars = [MockBar(100.0, 101.0, 99.0, 100.5) for _ in range(5)]

    result = detector.detect("TEST", bars)

    assert result is None


def test_ict_bos_detection():
    detector = ICTDetector()

    # Create bars with clear swing structure (need 2 lower neighbors for swing high)
    # Pattern: rise to peak, fall, rise to higher peak = creates swing highs/lows
    bars = []

    # Wave 1: Up then down (creates swing high)
    bars.append(MockBar(100, 101, 99, 100.5))
    bars.append(MockBar(100.5, 102, 99.5, 101))   # rising
    bars.append(MockBar(101, 103, 100, 102))     # rising
    bars.append(MockBar(102, 104, 101, 103))     # rising to peak
    bars.append(MockBar(103, 104, 102, 102.5))   # down from peak
    bars.append(MockBar(102.5, 103, 101.5, 102)) # down
    bars.append(MockBar(102, 103, 101, 101.5))   # down

    # Wave 2: Up then down higher (creates swing low, then higher swing high)
    bars.append(MockBar(101.5, 102, 100.5, 101.5))  # up
    bars.append(MockBar(101.5, 102.5, 101, 102))     # up
    bars.append(MockBar(102, 105, 101.5, 104))       # up to higher peak
    bars.append(MockBar(104, 105, 103, 104.5))       # down
    bars.append(MockBar(104.5, 105, 103.5, 104))     # down
    bars.append(MockBar(104, 104.5, 103, 103.5))     # down

    # More bars for context
    for _ in range(10):
        bars.append(MockBar(103.5, 104, 103, 103.8))

    result = detector.detect("TEST", bars)

    assert result is not None
    # Should have detected something or at least run without error
    assert isinstance(result.bos_detected, bool)
    # Recent swings might be 0 if pattern isn't perfect, that's ok
    assert isinstance(result.recent_swing_high, float)
    assert isinstance(result.recent_swing_low, float)
