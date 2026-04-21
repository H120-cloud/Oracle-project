"""Tests for StageDetector."""

import pytest
import numpy as np
from datetime import datetime, timedelta

from src.core.stage_detector import StageDetector
from src.models.schemas import OHLCVBar, MoveStage


def _make_bars(closes, base_volume=100000):
    """Build bars from a list of close prices."""
    bars = []
    for i, c in enumerate(closes):
        bars.append(OHLCVBar(
            timestamp=datetime(2024, 1, 1, 9, 30) + timedelta(minutes=i),
            open=c - 0.1, high=c + 0.3, low=c - 0.3, close=c,
            volume=base_volume,
        ))
    return bars


@pytest.fixture
def detector():
    return StageDetector()


def test_strong_trend(detector):
    # 3-up / 2-down cycle with similar magnitudes → RSI ~60, clear uptrend
    pattern = [0.4, 0.4, 0.4, -0.3, -0.3]  # net +0.6 per 5 bars
    closes = []
    price = 100.0
    for i in range(50):
        price += pattern[i % len(pattern)]
        closes.append(price)
    result = detector.detect("TEST", _make_bars(closes))
    assert result is not None
    assert result.entry_allowed


def test_breakdown(detector):
    # Steady decline
    closes = [100 - i * 0.5 for i in range(50)]
    result = detector.detect("TEST", _make_bars(closes))
    assert result is not None
    assert result.stage == MoveStage.BREAKDOWN
    assert not result.entry_allowed


def test_not_enough_bars(detector):
    closes = [100 + i for i in range(10)]
    result = detector.detect("TEST", _make_bars(closes))
    assert result is None


def test_entry_allowed_stages(detector):
    # Only stages 1-2 should allow entry
    closes = [100 + i * 0.3 for i in range(50)]
    result = detector.detect("TEST", _make_bars(closes))
    assert result is not None
    if result.stage in (MoveStage.BREAKOUT, MoveStage.STRONG_TREND):
        assert result.entry_allowed
    else:
        assert not result.entry_allowed
