"""
Smoke test for the test infrastructure itself.

If these fail, the rest of the suite is meaningless — fixtures are broken.
"""

from __future__ import annotations

import pytest

from src.core.agentic.news_momentum_models import (
    NewsMomentumCandidate,
    TelegramAlertRecord,
    CatalystSubType,
)


pytestmark = [pytest.mark.unit]


def test_make_candidate_returns_valid_model(make_candidate):
    c = make_candidate()
    assert isinstance(c, NewsMomentumCandidate)
    assert c.ticker == "TEST"
    assert c.catalyst_sub_type == CatalystSubType.EARNINGS_BEAT


def test_make_candidate_overrides_apply(make_candidate):
    c = make_candidate(ticker="LNKS", current_price=8.50, move_pct=32.0)
    assert c.ticker == "LNKS"
    assert c.current_price == 8.50
    assert c.move_pct == 32.0


def test_make_telegram_record_returns_valid_model(make_telegram_record):
    r = make_telegram_record()
    assert isinstance(r, TelegramAlertRecord)
    assert r.was_blocked is False  # default — model field default


def test_make_shadow_record_marks_blocked(make_shadow_record):
    r = make_shadow_record(block_reason="ml_veto(win=0.10)")
    assert r.was_blocked is True
    assert r.block_reason == "ml_veto(win=0.10)"
    assert r.alert_id.startswith("shadow_")


def test_random_seed_is_pinned():
    """The autouse _fixed_random_seed fixture must run before any test."""
    import random
    # Pinned seed 42 → first random() call is deterministic.
    assert round(random.random(), 6) == round(0.6394267984578837, 6)
