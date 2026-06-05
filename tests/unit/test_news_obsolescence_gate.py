"""Upstream-feed obsolescence gate (Objective 2).

When an aggregator serves a headline hours after its publication time, Oracle
detects it `now` and could treat it as a brand-new BREAKING catalyst. These
tests prove that such stale-on-arrival items are stripped of breaking/first-mover
treatment (and logged), while still flowing through the normal delayed-reaction
path — i.e. they are NOT dropped, preserving the 12h thesis.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import pytest

from src.core.agentic.news_momentum_models import (
    CatalystCategory,
    CatalystSubType,
    NewsMomentumCandidate,
    NewsMomentumConfig,
    NewsSource,
    SessionType,
)
from src.core.agentic.news_momentum_orchestrator import NewsMomentumOrchestrator

pytestmark = pytest.mark.unit


def _orch() -> NewsMomentumOrchestrator:
    """Minimal gate-only orchestrator (no disk/network), matching the existing
    alert-flow test harness."""
    orch = object.__new__(NewsMomentumOrchestrator)
    orch.config = NewsMomentumConfig(learning_enabled=False)
    orch._alert_cooldown = {}
    orch._headline_alert_cooldown = {}
    orch._unknown_learner = None
    return orch


def _fresh_fda_candidate(ticker: str = "ROCKET", published_age_s: int = 60,
                         detected_age_s: int = 30) -> NewsMomentumCandidate:
    now = datetime.now(timezone.utc)
    return NewsMomentumCandidate(
        ticker=ticker,
        headline=f"{ticker} announces FDA approval for breakthrough therapy",
        source=NewsSource.STOCKTITAN,
        published_at=now - timedelta(seconds=published_age_s),
        detected_at=now - timedelta(seconds=detected_age_s),
        timestamp_confidence="HIGH",
        session=SessionType.REGULAR,
        catalyst_category=CatalystCategory.BIOTECH,
        catalyst_sub_type=CatalystSubType.FDA_APPROVAL,
        current_price=5.0,
        news_impact_score=10.0,
        expected_return_score=10.0,
        continuation_probability=10.0,
        trap_risk=0.0,
        dilution_risk=0.0,
    )


# ── Marking + warning ──────────────────────────────────────────────────────

def test_six_hour_old_feed_item_is_flagged_and_warns(caplog):
    orch = _orch()
    c = _fresh_fda_candidate()
    c.published_at = datetime.now(timezone.utc) - timedelta(hours=6)

    with caplog.at_level(logging.WARNING):
        stale = orch._mark_if_obsolete_on_arrival(c)

    assert stale is True
    assert getattr(c, "_stale_on_arrival", False) is True
    assert any("obsolete feed item" in r.getMessage() for r in caplog.records)


def test_fresh_feed_item_not_flagged():
    orch = _orch()
    c = _fresh_fda_candidate()
    assert orch._mark_if_obsolete_on_arrival(c) is False
    assert getattr(c, "_stale_on_arrival", False) is False


def test_obsolescence_window_is_strict_300s():
    orch = _orch()  # breaking_obsolescence_window_seconds == 300
    now = datetime.now(timezone.utc)

    at_window = _fresh_fda_candidate()
    at_window.published_at = now - timedelta(seconds=300)
    assert orch._mark_if_obsolete_on_arrival(at_window, now=now) is False

    just_over = _fresh_fda_candidate()
    just_over.published_at = now - timedelta(seconds=301)
    assert orch._mark_if_obsolete_on_arrival(just_over, now=now) is True


# ── Breaking-treatment suppression (the flag flips eligibility) ─────────────

def test_stale_on_arrival_blocks_fast_path_watch():
    orch = _orch()
    eligible = _fresh_fda_candidate("CTRL")
    assert orch._is_fast_path_watch_eligible(eligible) is True  # control

    stale = _fresh_fda_candidate("STALE")
    stale._stale_on_arrival = True
    assert orch._is_fast_path_watch_eligible(stale) is False


def test_stale_on_arrival_blocks_first_mover_boost():
    orch = _orch()
    control = _fresh_fda_candidate("CTRL")
    orch._should_send_telegram_impl(control, adaptive={})
    assert getattr(control, "_first_mover", False) is True  # fresh -> first mover

    stale = _fresh_fda_candidate("STALE")
    stale._stale_on_arrival = True
    orch._should_send_telegram_impl(stale, adaptive={})
    assert getattr(stale, "_first_mover", False) is False


# ── Not dropped: the 12h delayed-reaction path is preserved ────────────────

def test_obsolete_item_is_marked_not_dropped():
    orch = _orch()
    c = _fresh_fda_candidate()
    c.published_at = datetime.now(timezone.utc) - timedelta(hours=6)
    orch._mark_if_obsolete_on_arrival(c)
    # Still a live candidate carrying its data — only the speed tier is stripped.
    assert c.is_active is True
    assert c.ticker == "ROCKET"
    assert c.current_price == 5.0
