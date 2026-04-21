"""Tests for DecisionEngine and NoTradeFilter."""

import pytest

from src.core.decision_engine import DecisionEngine
from src.core.classifier import StockClassifier
from src.core.ict_detector import ICTFeatures
from src.models.schemas import (
    ScannedStock,
    DipFeatures,
    DipResult,
    DipPhase,
    BounceFeatures,
    BounceResult,
    SignalAction,
    StockClassification,
)


@pytest.fixture
def engine():
    return DecisionEngine(signal_expiry_minutes=30)


@pytest.fixture
def classifier():
    return StockClassifier()


def _stock(ticker="TEST", price=100.0, volume=1_000_000, change_pct=5.0):
    return ScannedStock(
        ticker=ticker, price=price, volume=volume,
        change_percent=change_pct, scan_type="test",
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


def _ict_confirmed():
    """Helper to create valid ICT features meeting strict criteria."""
    return ICTFeatures(
        liquidity_sweep=True,
        sweep_direction="down",
        sweep_level=99.0,
        structure_reclaimed=True,
        structure_break_confirmed=True,
        micro_high_level=100.5,
        micro_low_level=98.5,
        is_overextended=False,
        extension_pct=5.0,
        trap_detected=False,
        ict_score=75,
        recent_swing_high=102.0,
    )


def _ict_incomplete():
    """Helper for ICT features that don't meet strict criteria."""
    return ICTFeatures(
        liquidity_sweep=False,
        structure_reclaimed=False,
        structure_break_confirmed=False,
        is_overextended=False,
        trap_detected=False,
        ict_score=30,
    )


def test_buy_signal_v3_strict(engine):
    """V3: BUY requires strict ICT alignment + structure break."""
    stock = _stock()
    signal = engine.decide(
        stock=stock,
        classification=StockClassification.BOUNCE_FORMING,
        dip=_dip(),
        bounce=_bounce(prob=70.0, entry_ready=True),
        ict=_ict_confirmed(),
    )
    assert signal.action == SignalAction.BUY
    assert signal.entry_price is not None
    assert signal.stop_price is not None
    assert signal.target_prices is not None
    assert len(signal.target_prices) >= 2


def test_no_valid_setup_without_ict_alignment(engine):
    """V3: Without ICT alignment (sweep/reclaim), returns NO_VALID_SETUP."""
    stock = _stock()
    signal = engine.decide(
        stock=stock,
        classification=StockClassification.BOUNCE_FORMING,
        dip=_dip(),
        bounce=_bounce(prob=70.0, entry_ready=True),
        ict=_ict_incomplete(),  # No sweep, no reclaim
    )
    assert signal.action == SignalAction.NO_VALID_SETUP


def test_no_valid_setup_no_structure_break(engine):
    """V3: Without micro structure break, returns NO_VALID_SETUP."""
    stock = _stock()
    ict = _ict_confirmed()
    ict.structure_break_confirmed = False
    signal = engine.decide(
        stock=stock,
        classification=StockClassification.BOUNCE_FORMING,
        dip=_dip(),
        bounce=_bounce(prob=70.0, entry_ready=True),
        ict=ict,
    )
    assert signal.action == SignalAction.NO_VALID_SETUP


def test_no_valid_setup_trap_detected(engine):
    """V3: If trap detected, returns NO_VALID_SETUP."""
    stock = _stock()
    ict = _ict_confirmed()
    ict.trap_detected = True
    ict.trap_reason = "exhaustion_trap: near highs with small candles"
    signal = engine.decide(
        stock=stock,
        classification=StockClassification.BOUNCE_FORMING,
        dip=_dip(),
        bounce=_bounce(prob=70.0, entry_ready=True),
        ict=ict,
    )
    assert signal.action == SignalAction.NO_VALID_SETUP


def test_no_valid_setup_low_volume(engine):
    """Low volume should still result in NO_VALID_SETUP."""
    stock = _stock(volume=100_000)
    signal = engine.decide(
        stock=stock,
        classification=StockClassification.BOUNCE_FORMING,
        dip=_dip(),
        bounce=_bounce(),
        ict=_ict_confirmed(),
    )
    assert signal.action == SignalAction.NO_VALID_SETUP


def test_no_valid_setup_overextended(engine):
    """V3: Overextended should result in NO_VALID_SETUP."""
    stock = _stock(change_pct=20.0)
    ict = _ict_confirmed()
    ict.is_overextended = True
    ict.extension_pct = 18.0
    signal = engine.decide(
        stock=stock,
        classification=StockClassification.BOUNCE_FORMING,
        dip=None,
        bounce=None,
        ict=ict,
    )
    assert signal.action == SignalAction.NO_VALID_SETUP


def test_classifier_bounce_forming(classifier):
    result = classifier.classify(
        dip=_dip(prob=60.0), bounce=_bounce(prob=70.0, entry_ready=True), change_percent=5.0
    )
    assert result == StockClassification.BOUNCE_FORMING


def test_classifier_sideways(classifier):
    result = classifier.classify(dip=None, bounce=None, change_percent=0.5)
    assert result == StockClassification.SIDEWAYS
