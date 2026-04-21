"""Tests for VolumeProfileEngine."""

import pytest
from datetime import datetime, timedelta

from src.core.volume_profile import VolumeProfileEngine
from src.models.schemas import OHLCVBar


def _make_bars(n=100, base_price=100.0, base_volume=10000):
    """Generate synthetic OHLCV bars with a price distribution."""
    bars = []
    for i in range(n):
        # Create a normal distribution around base_price
        import random
        random.seed(i)
        mid = base_price + random.gauss(0, 2)
        h = mid + abs(random.gauss(0, 0.5))
        l = mid - abs(random.gauss(0, 0.5))
        o = mid + random.gauss(0, 0.3)
        c = mid + random.gauss(0, 0.3)
        v = base_volume * (1 + abs(random.gauss(0, 0.3)))
        bars.append(OHLCVBar(
            timestamp=datetime(2024, 1, 1, 9, 30) + timedelta(minutes=i),
            open=o, high=h, low=l, close=c, volume=v,
        ))
    return bars


@pytest.fixture
def engine():
    return VolumeProfileEngine(num_bins=20)


def test_basic_profile(engine):
    bars = _make_bars(100)
    result = engine.compute(bars)
    assert result is not None
    assert result.poc_price > 0
    assert result.value_area_high >= result.value_area_low
    assert len(result.high_volume_nodes) > 0


def test_too_few_bars(engine):
    bars = _make_bars(5)
    result = engine.compute(bars)
    assert result is None


def test_support_resistance(engine):
    bars = _make_bars(100, base_price=50.0)
    result = engine.compute(bars)
    assert result is not None
    # At least POC and value area are populated
    assert result.poc_price > 0
    assert isinstance(result.support_levels, list)
    assert isinstance(result.resistance_levels, list)


def test_poc_in_value_area(engine):
    bars = _make_bars(100)
    result = engine.compute(bars)
    assert result is not None
    assert result.value_area_low <= result.poc_price <= result.value_area_high
