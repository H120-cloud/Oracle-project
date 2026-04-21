"""Tests for DipDetector."""

import pytest

from src.core.dip_detector import DipDetector, DipThresholds
from src.models.schemas import DipFeatures, DipPhase


@pytest.fixture
def detector():
    return DipDetector()


def _make_features(**overrides) -> DipFeatures:
    defaults = dict(
        vwap_distance_pct=0.0,
        ema9_distance_pct=0.0,
        ema20_distance_pct=0.0,
        drop_from_high_pct=0.0,
        consecutive_red_candles=0,
        red_candle_volume_ratio=1.0,
        lower_highs_count=0,
        momentum_decay=0.0,
    )
    defaults.update(overrides)
    return DipFeatures(**defaults)


def test_no_dip_neutral_stock(detector):
    features = _make_features()
    result = detector.detect("TEST", features)
    assert result.probability < 40
    assert not result.is_valid_dip


def test_strong_dip(detector):
    features = _make_features(
        vwap_distance_pct=-2.0,
        ema9_distance_pct=-1.5,
        ema20_distance_pct=-1.0,
        drop_from_high_pct=5.0,
        consecutive_red_candles=4,
        red_candle_volume_ratio=1.8,
        lower_highs_count=3,
    )
    result = detector.detect("TEST", features)
    assert result.probability >= 60
    assert result.is_valid_dip
    assert result.phase in (DipPhase.MID, DipPhase.LATE)


def test_early_dip(detector):
    features = _make_features(
        vwap_distance_pct=-0.5,
        drop_from_high_pct=2.5,
        consecutive_red_candles=2,
    )
    result = detector.detect("TEST", features)
    assert result.phase == DipPhase.EARLY


def test_extreme_dip_clamped(detector):
    features = _make_features(
        vwap_distance_pct=-10.0,
        ema9_distance_pct=-8.0,
        ema20_distance_pct=-5.0,
        drop_from_high_pct=20.0,
        consecutive_red_candles=10,
        red_candle_volume_ratio=3.0,
        lower_highs_count=8,
    )
    result = detector.detect("TEST", features)
    assert result.probability <= 100
