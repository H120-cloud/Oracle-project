from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.core.agentic.bullish_catalyst_flash import assess_bullish_flash
from src.core.agentic.news_momentum_models import (
    CatalystCategory,
    CatalystSubType,
    NewsMomentumConfig,
    NewsMomentumCandidate,
    NewsSource,
    SessionType,
)


pytestmark = [pytest.mark.unit, pytest.mark.gate]


def _candidate(**overrides) -> NewsMomentumCandidate:
    now = datetime.now(timezone.utc)
    data = {
        "ticker": "ASTC",
        "headline": (
            "Astrotech Corporation Board of Directors Approves Strategic "
            "Lunar Resource and Infrastructure Initiative to Advance Future "
            "Moon-Based Quantum Computing Manufacturing"
        ),
        "source": NewsSource.FINVIZ,
        "published_at": now,
        "detected_at": now,
        "session": SessionType.REGULAR,
        "catalyst_category": CatalystCategory.UNKNOWN,
        "catalyst_sub_type": CatalystSubType.OTHER,
        "is_negative": False,
        "is_vague": False,
        "current_price": 2.31,
        "prior_price": 2.25,
        "move_pct": 2.67,
        "rvol": 1.2,
        "news_impact_score": 20.0,
        "expected_return_score": 25.0,
        "continuation_probability": 20.0,
        "multi_day_continuation_score": 20.0,
        "trap_risk": 10.0,
        "dilution_risk": 0.0,
    }
    data.update(overrides)
    return NewsMomentumCandidate(**data)


def test_astc_lunar_quantum_headline_is_bullish_flash_candidate():
    c = _candidate()

    assessment = assess_bullish_flash(c, NewsMomentumConfig())

    assert assessment.should_flash is True
    assert assessment.score >= 55.0
    assert "lunar" in assessment.reasons
    assert "quantum" in assessment.reasons


def test_bearish_financing_blocks_flash_even_with_bullish_theme_words():
    c = _candidate(
        headline=(
            "Company Announces Strategic AI Initiative and $25 Million "
            "Registered Direct Offering Priced At-The-Market"
        ),
        catalyst_category=CatalystCategory.NEGATIVE,
        catalyst_sub_type=CatalystSubType.OFFERING,
        is_negative=True,
    )

    assessment = assess_bullish_flash(c, NewsMomentumConfig())

    assert assessment.should_flash is False
    assert assessment.block_reason == "bearish_keyword:offering"


def test_stale_bullish_headline_does_not_flash():
    c = _candidate(detected_at=datetime.now(timezone.utc) - timedelta(minutes=10))

    assessment = assess_bullish_flash(c, NewsMomentumConfig())

    assert assessment.should_flash is False
    assert assessment.block_reason == "stale_flash_candidate"


def test_orchestrator_allows_flash_past_slow_score_and_small_move_gates(monkeypatch):
    from src.core.agentic.news_momentum_orchestrator import NewsMomentumOrchestrator

    orch = NewsMomentumOrchestrator.__new__(NewsMomentumOrchestrator)
    orch.config = NewsMomentumConfig()
    orch._alert_cooldown = {}
    orch._headline_alert_cooldown = {}
    orch._unknown_learner = None
    monkeypatch.setattr(orch, "_is_bad_ticker", lambda _ticker: False)

    c = _candidate(
        news_impact_score=0.0,
        expected_return_score=0.0,
        move_pct=0.8,
        rvol=1.0,
    )

    assert orch._should_send_telegram_impl(c, adaptive={}) is True
    assert getattr(c, "_bullish_flash").should_flash is True
