"""Tests for SignalRanker."""

import pytest
from datetime import datetime

from src.core.signal_ranker import SignalRanker
from src.models.schemas import (
    TradingSignal,
    SignalAction,
    StockClassification,
)


@pytest.fixture
def ranker():
    return SignalRanker(top_n=3)


def _signal(
    ticker="TEST",
    action=SignalAction.BUY,
    bounce_prob=70.0,
    dip_prob=60.0,
    risk_score=3,
    setup_grade="B",
    confidence=65.0,
    entry=100.0,
    stop=98.5,
    targets=None,
):
    return TradingSignal(
        ticker=ticker,
        action=action,
        classification=StockClassification.BOUNCE_FORMING,
        dip_probability=dip_prob,
        bounce_probability=bounce_prob,
        entry_price=entry,
        stop_price=stop,
        target_prices=targets or [101.5, 103.0, 104.5],
        risk_score=risk_score,
        setup_grade=setup_grade,
        confidence=confidence,
        created_at=datetime.utcnow(),
    )


def test_top_n_respected(ranker):
    signals = [
        _signal(ticker="A", bounce_prob=80, risk_score=2, setup_grade="A", confidence=80),
        _signal(ticker="B", bounce_prob=70, risk_score=3, setup_grade="B", confidence=65),
        _signal(ticker="C", bounce_prob=60, risk_score=4, setup_grade="C", confidence=55),
        _signal(ticker="D", bounce_prob=50, risk_score=5, setup_grade="D", confidence=45),
    ]
    ranked = ranker.rank(signals)
    buy_signals = [s for s in ranked if s.action == SignalAction.BUY]
    assert len(buy_signals) == 3  # top_n = 3


def test_best_signal_first(ranker):
    signals = [
        _signal(ticker="WEAK", bounce_prob=40, risk_score=7, setup_grade="D", confidence=30),
        _signal(ticker="STRONG", bounce_prob=85, risk_score=1, setup_grade="A", confidence=90),
    ]
    ranked = ranker.rank(signals)
    assert ranked[0].ticker == "STRONG"


def test_buy_ranks_above_watch(ranker):
    signals = [
        _signal(ticker="WATCH", action=SignalAction.WATCH, bounce_prob=70, risk_score=3),
        _signal(ticker="BUY", action=SignalAction.BUY, bounce_prob=70, risk_score=3),
    ]
    ranked = ranker.rank(signals)
    # Same quality → BUY gets +10 bonus → ranks first
    assert ranked[0].ticker == "BUY"


def test_non_rankable_appended(ranker):
    signals = [
        _signal(ticker="BUY1", action=SignalAction.BUY),
        _signal(ticker="AVOID", action=SignalAction.AVOID),
        _signal(ticker="NONE", action=SignalAction.NO_VALID_SETUP),
    ]
    ranked = ranker.rank(signals)
    # BUY1 should be first, AVOID/NONE at end
    assert ranked[0].ticker == "BUY1"
    avoid_none = [s for s in ranked if s.action in (SignalAction.AVOID, SignalAction.NO_VALID_SETUP)]
    assert len(avoid_none) == 2
