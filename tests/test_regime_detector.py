"""Tests for RegimeDetector."""

import pytest
import numpy as np
from datetime import datetime, timedelta

from src.core.regime_detector import RegimeDetector
from src.models.schemas import OHLCVBar, MarketRegime


def _trending_bars(n=60, start=100.0):
    """Steadily rising bars with realistic volatility → trending regime."""
    np.random.seed(99)
    bars = []
    price = start
    for i in range(n):
        price += 0.5 + np.random.randn() * 0.3  # trend + noise
        swing = abs(np.random.randn()) * 1.2
        bars.append(OHLCVBar(
            timestamp=datetime(2024, 1, 1, 9, 30) + timedelta(minutes=i),
            open=price - 0.5, high=price + swing, low=price - swing, close=price,
            volume=100000,
        ))
    return bars


def _choppy_bars(n=60, center=100.0):
    """Random oscillation → choppy regime."""
    np.random.seed(42)
    bars = []
    for i in range(n):
        noise = np.random.randn() * 0.3
        price = center + noise
        bars.append(OHLCVBar(
            timestamp=datetime(2024, 1, 1, 9, 30) + timedelta(minutes=i),
            open=price - 0.1, high=price + 0.2, low=price - 0.2, close=price,
            volume=100000,
        ))
    return bars


def _volatile_bars(n=60, start=100.0):
    """Large swings → high volatility."""
    np.random.seed(7)
    bars = []
    price = start
    for i in range(n):
        swing = np.random.randn() * 5  # big moves
        price = max(price + swing, 10)
        bars.append(OHLCVBar(
            timestamp=datetime(2024, 1, 1, 9, 30) + timedelta(minutes=i),
            open=price - 2, high=price + 3, low=price - 3, close=price,
            volume=100000,
        ))
    return bars


@pytest.fixture
def detector():
    return RegimeDetector()


def test_trending(detector):
    result = detector.detect(_trending_bars())
    assert result is not None
    assert result.regime == MarketRegime.TRENDING
    assert result.sensitivity_multiplier == 1.0
    assert result.adx is not None and result.adx > 20


def test_choppy(detector):
    result = detector.detect(_choppy_bars())
    assert result is not None
    # Choppy or low-vol since oscillations are tiny
    assert result.regime in (MarketRegime.CHOPPY, MarketRegime.LOW_VOLATILITY)
    assert result.sensitivity_multiplier < 1.0


def test_high_volatility(detector):
    result = detector.detect(_volatile_bars())
    assert result is not None
    assert result.regime == MarketRegime.HIGH_VOLATILITY
    assert result.sensitivity_multiplier > 1.0


def test_not_enough_bars(detector):
    bars = _trending_bars(10)
    result = detector.detect(bars)
    assert result is None


def test_regime_has_indicators(detector):
    result = detector.detect(_trending_bars())
    assert result is not None
    assert result.adx is not None
    assert result.atr_pct is not None
    assert result.bb_width is not None
