"""Tests for RiskScorer."""

import pytest

from src.core.risk_scorer import RiskScorer
from src.models.schemas import (
    ScannedStock,
    StockClassification,
    DipResult,
    DipPhase,
    DipFeatures,
    BounceResult,
    BounceFeatures,
)


@pytest.fixture
def scorer():
    return RiskScorer()


def _stock(price=100.0, volume=2_000_000, rvol=2.0, change_pct=5.0):
    return ScannedStock(
        ticker="TEST", price=price, volume=volume,
        rvol=rvol, change_percent=change_pct, scan_type="test",
    )


def _dip(prob=60.0, phase=DipPhase.MID):
    return DipResult(
        ticker="TEST", probability=prob, phase=phase, is_valid_dip=prob >= 40,
        features=DipFeatures(
            vwap_distance_pct=-1.0, ema9_distance_pct=-0.8, ema20_distance_pct=-0.5,
            drop_from_high_pct=3.0, consecutive_red_candles=3,
            red_candle_volume_ratio=1.5, lower_highs_count=2, momentum_decay=-0.01,
        ),
    )


def _bounce(prob=70.0, entry_ready=True):
    return BounceResult(
        ticker="TEST", probability=prob, entry_ready=entry_ready,
        trigger_price=100.20, is_valid_bounce=prob >= 40,
        features=BounceFeatures(
            support_distance_pct=0.5, selling_pressure_change=-0.3,
            buying_pressure_ratio=1.5, higher_low_formed=True,
            key_level_reclaimed=True, rsi=32.0, macd_histogram_slope=0.2,
        ),
    )


def test_low_risk_high_quality(scorer):
    assessment = scorer.assess(
        stock=_stock(volume=3_000_000, rvol=3.0, change_pct=5.0),
        classification=StockClassification.BOUNCE_FORMING,
        dip=_dip(prob=60.0, phase=DipPhase.MID),
        bounce=_bounce(prob=75.0, entry_ready=True),
    )
    assert assessment.risk_score <= 3
    assert assessment.setup_grade in ("A", "B")
    assert assessment.confidence >= 50


def test_high_risk_breakdown(scorer):
    assessment = scorer.assess(
        stock=_stock(volume=300_000, rvol=0.5, change_pct=18.0),
        classification=StockClassification.BREAKDOWN_RISK,
        dip=_dip(prob=80.0, phase=DipPhase.LATE),
        bounce=_bounce(prob=30.0, entry_ready=False),
    )
    assert assessment.risk_score >= 5
    assert assessment.setup_grade in ("D", "F")
    assert len(assessment.risk_factors) >= 2


def test_risk_score_range(scorer):
    assessment = scorer.assess(
        stock=_stock(),
        classification=StockClassification.DIP_FORMING,
        dip=_dip(),
        bounce=None,
    )
    assert 1 <= assessment.risk_score <= 10
    assert assessment.setup_grade in ("A", "B", "C", "D", "F")
    assert 0 <= assessment.confidence <= 100
