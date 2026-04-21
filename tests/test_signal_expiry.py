"""Tests for SignalExpiryChecker."""

import pytest
from datetime import datetime, timedelta

from src.core.signal_expiry import SignalExpiryChecker
from src.models.schemas import (
    TradingSignal, SignalAction, StockClassification, ExpiryReason, OHLCVBar,
)


@pytest.fixture
def checker():
    return SignalExpiryChecker(default_expiry_minutes=30)


def _signal(
    action=SignalAction.BUY,
    entry=100.0,
    stop=98.0,
    expiry_dt=None,
    created_at=None,
):
    return TradingSignal(
        ticker="TEST",
        action=action,
        classification=StockClassification.BOUNCE_FORMING,
        entry_price=entry,
        stop_price=stop,
        signal_expiry=expiry_dt,
        created_at=created_at or datetime.utcnow(),
    )


def test_time_expired(checker):
    sig = _signal(expiry_dt=datetime(2024, 1, 1, 10, 0))
    reason = checker.check(sig, current_price=100.0, now=datetime(2024, 1, 1, 10, 1))
    assert reason == ExpiryReason.TIME_EXPIRED


def test_not_expired_within_window(checker):
    sig = _signal(expiry_dt=datetime(2024, 1, 1, 10, 30))
    reason = checker.check(sig, current_price=100.0, now=datetime(2024, 1, 1, 10, 0))
    assert reason is None


def test_reclaim_failed(checker):
    sig = _signal(stop=98.0)
    reason = checker.check(sig, current_price=97.5)
    assert reason == ExpiryReason.RECLAIM_FAILED


def test_no_bounce_watch(checker):
    created = datetime(2024, 1, 1, 9, 0)
    sig = _signal(
        action=SignalAction.WATCH,
        entry=100.0,
        created_at=created,
    )
    # 20 min later, price still at entry → no bounce
    now = created + timedelta(minutes=20)
    reason = checker.check(sig, current_price=99.5, now=now)
    assert reason == ExpiryReason.NO_BOUNCE


def test_momentum_faded(checker):
    sig = _signal(action=SignalAction.BUY)
    bars = [
        OHLCVBar(
            timestamp=datetime(2024, 1, 1, 10, i),
            open=100 - i * 0.1, high=100 - i * 0.05,
            low=100 - i * 0.15, close=100 - i * 0.1,
            volume=10000,
        )
        for i in range(5)
    ]
    reason = checker.check(sig, current_price=99.5, recent_bars=bars)
    assert reason == ExpiryReason.MOMENTUM_FADED


def test_avoid_signals_not_checked(checker):
    sig = _signal(action=SignalAction.AVOID, stop=98.0)
    reason = checker.check(sig, current_price=97.0)
    assert reason is None  # AVOID signals aren't checked for reclaim
