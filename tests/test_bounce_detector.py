"""Tests for BounceDetector."""

import pytest

from src.core.bounce_detector import BounceDetector
from src.models.schemas import BounceFeatures


@pytest.fixture
def detector():
    return BounceDetector()


def _make_features(**overrides) -> BounceFeatures:
    defaults = dict(
        support_distance_pct=5.0,
        selling_pressure_change=0.0,
        buying_pressure_ratio=1.0,
        higher_low_formed=False,
        key_level_reclaimed=False,
        rsi=50.0,
        macd_histogram_slope=0.0,
    )
    defaults.update(overrides)
    return BounceFeatures(**defaults)


def test_no_bounce_neutral(detector):
    features = _make_features()
    result = detector.detect("TEST", features, current_price=100.0)
    assert result.probability < 40
    assert not result.is_valid_bounce
    assert not result.entry_ready


def test_strong_bounce(detector):
    features = _make_features(
        support_distance_pct=0.3,
        selling_pressure_change=-0.5,
        buying_pressure_ratio=1.8,
        higher_low_formed=True,
        key_level_reclaimed=True,
        rsi=28.0,
        macd_histogram_slope=0.3,
    )
    result = detector.detect("TEST", features, current_price=100.0)
    assert result.probability >= 60
    assert result.is_valid_bounce
    assert result.entry_ready
    assert result.trigger_price is not None


def test_moderate_bounce_watch(detector):
    features = _make_features(
        support_distance_pct=0.5,
        selling_pressure_change=-0.3,
        buying_pressure_ratio=1.3,
        higher_low_formed=True,
        key_level_reclaimed=True,
        rsi=33.0,
    )
    result = detector.detect("TEST", features, current_price=50.0)
    assert result.is_valid_bounce
    # May or may not be entry ready depending on exact score


def test_trigger_price_set_on_entry_ready(detector):
    features = _make_features(
        support_distance_pct=0.2,
        selling_pressure_change=-0.6,
        buying_pressure_ratio=2.0,
        higher_low_formed=True,
        key_level_reclaimed=True,
        rsi=25.0,
        macd_histogram_slope=0.5,
    )
    result = detector.detect("TEST", features, current_price=100.0)
    if result.entry_ready:
        assert result.trigger_price is not None
        assert result.trigger_price > 100.0
