"""
End-to-end alert-gate regression suite.

The classifier suite proves headlines reach the right catalyst label. This
suite proves the next step works too: that a correctly-classified high-
conviction catalyst ACTUALLY produces a Telegram alert decision under the
edge conditions that historically caused misses.

Test scenarios encode the failure modes we've actually hit:
  • PRFX-style: drug_launch, no spike yet, sub-3% move → must alert
  • OLOX-style: M&A barely below score floor (0.1 short) → must alert via
    high-conviction step-down
  • No-price + fresh strong-positive headline → must alert via no-price bypass
  • No-price + neutral/weak headline → must STILL block (bypass is bounded)
  • Negative news (offering, lawsuit) → must always block, even high-impact
  • Cooldown-protected re-alert → blocked once recently alerted

Run: pytest tests/regression/test_alert_gate_end_to_end.py -v
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.core.agentic.news_momentum_models import (
    CatalystCategory,
    CatalystSubType,
    FloatCategory,
    MarketCapCategory,
    NewsMomentumCandidate,
    NewsMomentumConfig,
    NewsSource,
    SessionType,
)
from src.core.agentic.news_momentum_orchestrator import NewsMomentumOrchestrator

pytestmark = [pytest.mark.regression, pytest.mark.alert_gate]


def _make_candidate(
    *,
    ticker: str = "TEST",
    headline: str = "BioCorp wins $200M government contract",
    catalyst_sub_type: CatalystSubType = CatalystSubType.GOVERNMENT_CONTRACT,
    catalyst_category: CatalystCategory = CatalystCategory.CORPORATE,
    news_impact_score: float = 60.0,
    expected_return_score: float = 55.0,
    continuation_probability: float = 60.0,
    multi_day_continuation_score: float = 40.0,
    current_price: float | None = 3.50,
    move_pct: float = 5.0,
    rvol: float = 3.0,
    volume: int = 500_000,
    trap_risk: float = 20.0,
    dilution_risk: float = 10.0,
    is_negative: bool = False,
    is_vague: bool = False,
    float_category: FloatCategory = FloatCategory.LOW,
    market_cap_category: MarketCapCategory = MarketCapCategory.SMALL,
    session: SessionType = SessionType.REGULAR,
    detected_age_seconds: float = 30.0,
) -> NewsMomentumCandidate:
    """Build a minimally-realistic candidate. Defaults are an unambiguous winner
    (gov contract, low float, fresh, modest pre-spike move). Each test overrides
    only the dimensions it's stressing."""
    now = datetime.now(timezone.utc)
    return NewsMomentumCandidate(
        ticker=ticker,
        headline=headline,
        source=NewsSource.STOCKTITAN,
        published_at=now - timedelta(seconds=detected_age_seconds),
        detected_at=now - timedelta(seconds=detected_age_seconds),
        session=session,
        catalyst_category=catalyst_category,
        catalyst_sub_type=catalyst_sub_type,
        news_impact_score=news_impact_score,
        expected_return_score=expected_return_score,
        continuation_probability=continuation_probability,
        multi_day_continuation_score=multi_day_continuation_score,
        current_price=current_price,
        move_pct=move_pct,
        rvol=rvol,
        volume=volume,
        trap_risk=trap_risk,
        dilution_risk=dilution_risk,
        is_negative=is_negative,
        is_vague=is_vague,
        float_category=float_category,
        market_cap_category=market_cap_category,
    )


@pytest.fixture(scope="module")
def orch():
    """Single orchestrator shared across tests. We only call the pure gate
    function _should_send_telegram, so no real I/O is performed."""
    from src.core.agentic.news_momentum_winners import _ML_PERCENTILE_BANDS

    original_bands = dict(_ML_PERCENTILE_BANDS)
    yield NewsMomentumOrchestrator()
    _ML_PERCENTILE_BANDS.clear()
    _ML_PERCENTILE_BANDS.update(original_bands)


def _block_reason(c: NewsMomentumCandidate) -> str | None:
    return getattr(c, "_block_reason", None)


# ── PRFX-style: high-conviction catalyst, no spike yet ─────────────────────

def test_prfx_drug_launch_with_small_move_must_alert(orch):
    """PRFX hit the small_move gate at +2.95% on a drug_launch catalyst. The
    whole point of the alert system is firing BEFORE the spike — a high-
    conviction catalyst with no move yet is the canonical "front-run me"
    setup. Must pass."""
    c = _make_candidate(
        ticker="PRFX",
        headline="PainReform announces commercial launch of lead drug",
        catalyst_sub_type=CatalystSubType.DRUG_LAUNCH,
        catalyst_category=CatalystCategory.BIOTECH,
        news_impact_score=61.0,
        expected_return_score=48.0,
        continuation_probability=55.0,
        multi_day_continuation_score=35.0,
        current_price=1.35,
        move_pct=2.95,  # pre-spike — the move we want to front-run
        rvol=0.5,
        float_category=FloatCategory.ULTRA_LOW,
        market_cap_category=MarketCapCategory.NANO,
    )
    allowed = orch._should_send_telegram(c, adaptive={})
    assert allowed, f"PRFX-style drug_launch must alert pre-spike. Blocked by: {_block_reason(c)!r}"


# ── OLOX-style: M&A barely below score floor ───────────────────────────────

def test_olox_acquisition_barely_below_floor_must_alert(orch):
    """OLOX was blocked by score_gate at ret=49.9 (floor 50.0). M&A is now in
    the high-conviction set, which gives a 10-point step-down on both
    impact and return floors. Must pass."""
    c = _make_candidate(
        ticker="OLOX",
        headline="Olenox to be acquired in all-cash transaction at premium",
        catalyst_sub_type=CatalystSubType.ACQUISITION,
        catalyst_category=CatalystCategory.CORPORATE,
        news_impact_score=57.3,
        expected_return_score=49.9,  # the exact value that historically blocked it
        continuation_probability=55.0,
        multi_day_continuation_score=35.0,
        current_price=5.08,
        move_pct=4.5,
        rvol=2.0,
    )
    allowed = orch._should_send_telegram(c, adaptive={})
    assert allowed, f"OLOX-style M&A must alert via high-conviction step-down. Blocked by: {_block_reason(c)!r}"


# ── No-price bypass: strong catalyst, quote not yet available ──────────────

def test_no_price_with_fresh_strong_catalyst_must_alert(orch):
    """Pre-spike news often arrives faster than a live quote (yfinance lag,
    rate limits, after-hours). A strongly-positive fresh catalyst must not
    be blocked just because we don't have a price tick yet."""
    c = _make_candidate(
        headline="BioCorp receives FDA approval for breakthrough cancer therapy",
        catalyst_sub_type=CatalystSubType.FDA_APPROVAL,
        catalyst_category=CatalystCategory.BIOTECH,
        news_impact_score=75.0,
        expected_return_score=70.0,
        current_price=None,  # the failure mode — no live quote
        move_pct=0.0,
        rvol=0.0,
        volume=0,
        detected_age_seconds=15.0,
    )
    allowed = orch._should_send_telegram(c, adaptive={})
    assert allowed, f"Fresh FDA approval with no price must alert via no-price bypass. Blocked by: {_block_reason(c)!r}"


def test_no_price_with_weak_or_neutral_headline_must_block(orch):
    """The no-price bypass is bounded — it only fires on strong-positive
    language. A neutral/vague headline without a price must still be blocked
    so we don't fire on garbage."""
    c = _make_candidate(
        headline="Company schedules conference call to discuss results",
        catalyst_sub_type=CatalystSubType.OTHER,
        catalyst_category=CatalystCategory.UNKNOWN,
        news_impact_score=30.0,
        expected_return_score=25.0,
        current_price=None,
        move_pct=0.0,
    )
    allowed = orch._should_send_telegram(c, adaptive={})
    assert not allowed, "Neutral headline with no price should not bypass — too noisy"
    assert _block_reason(c) is not None


# ── Negative news must always block, even at high impact ────────────────────

@pytest.mark.parametrize("sub_type,headline", [
    (CatalystSubType.OFFERING, "Pricing of $50M registered direct offering"),
    (CatalystSubType.REVERSE_SPLIT, "Board approves 1-for-25 reverse stock split"),
    (CatalystSubType.OTHER, "Class action lawsuit filed alleging securities fraud"),
])
def test_negative_news_always_blocks(orch, sub_type, headline):
    """No matter how high-impact a negative catalyst scores, we must never
    alert on it — these patterns are universally bearish for retail entries."""
    c = _make_candidate(
        headline=headline,
        catalyst_sub_type=sub_type,
        catalyst_category=CatalystCategory.NEGATIVE,
        is_negative=True,
        news_impact_score=80.0,  # deliberately high — must still block
        expected_return_score=70.0,
        move_pct=8.0,
    )
    allowed = orch._should_send_telegram(c, adaptive={})
    assert not allowed, f"Negative {sub_type.value} ({headline!r}) must block even at impact 80"
    assert _block_reason(c) is not None


# ── Already-alerted cooldown ────────────────────────────────────────────────

def test_already_alerted_candidate_does_not_re_alert(orch):
    """A candidate whose telegram_sent flag is True must not re-alert.
    Guards against the cooldown logic regressing into duplicate spam."""
    c = _make_candidate()
    c.telegram_sent = True
    allowed = orch._should_send_telegram(c, adaptive={})
    assert not allowed, "telegram_sent=True must short-circuit the gate"


# ── High-impact known catalyst with high risk should still block ───────────

def test_high_trap_risk_blocks_even_with_strong_catalyst(orch):
    """A genuinely strong catalyst with simultaneously catastrophic trap/dilution
    risk must NOT alert — the no-price bypass and high-conviction step-down
    both keep the risk gates."""
    c = _make_candidate(
        headline="BioCorp receives FDA approval for new therapy",
        catalyst_sub_type=CatalystSubType.FDA_APPROVAL,
        catalyst_category=CatalystCategory.BIOTECH,
        news_impact_score=72.0,
        expected_return_score=68.0,
        trap_risk=85.0,
        dilution_risk=80.0,
    )
    allowed = orch._should_send_telegram(c, adaptive={})
    assert not allowed, "High trap+dilution risk must block even on FDA approval"


# ── No-repeat contract: a catalyst alerts ONCE ─────────────────────────────

def test_same_ticker_reworded_headline_blocked_within_cooldown(orch):
    """User contract: alert a ticker ONCE per catalyst. The same news arriving
    reworded from a different source (Finviz vs StockTitan) must NOT re-alert —
    the ticker cooldown (now > freshness window) catches it even when the
    headline-hash differs. This is the exact 4-6h re-ping spam we observed."""
    from datetime import datetime, timezone
    orch._alert_cooldown["RPT"] = datetime.now(timezone.utc)  # simulate just-alerted
    c = _make_candidate(
        ticker="RPT",
        headline="RPT Holdings to be acquired by BigCo in all-cash deal",  # reworded
        catalyst_sub_type=CatalystSubType.ACQUISITION,
        news_impact_score=70.0,
        expected_return_score=65.0,
    )
    allowed = orch._should_send_telegram(c, adaptive={})
    assert not allowed, "Reworded repeat within cooldown must be blocked"
    assert _block_reason(c) == "ticker_cooldown"


def test_cooldown_exceeds_freshness_window(orch):
    """The ticker cooldown MUST exceed news_max_age_hours, otherwise a single
    catalyst can re-alert while it's still inside its own freshness window."""
    cooldown_h = orch.config.telegram_cooldown_minutes / 60.0
    assert cooldown_h > orch.config.news_max_age_hours, (
        f"cooldown ({cooldown_h}h) must exceed freshness window "
        f"({orch.config.news_max_age_hours}h) or the same catalyst re-alerts"
    )


def test_blocked_candidate_latency_traced_once_per_reason(orch, monkeypatch):
    """A blocked-but-active candidate is re-gated on every refresh (~45s, up to
    24h). The latency trace must record it once per block reason, not once per
    pass — otherwise the trace floods with duplicate rows whose published->gate
    'latency' just tracks the headline ageing and reads as ever-growing alert
    latency in the diagnostics view."""
    import src.core.agentic.news_momentum_orchestrator as orch_mod

    traced: list = []
    monkeypatch.setattr(
        orch_mod, "trace_candidate",
        lambda *a, **k: traced.append(k.get("blocked_reason")),
    )

    # Negative news is an unconditional block with a stable reason.
    c = _make_candidate(
        ticker="NEGN",
        headline="Company prices dilutive offering amid shareholder lawsuit",
        is_negative=True,
    )

    for _ in range(4):  # simulate four refresh re-gates
        assert orch._should_send_telegram(c, adaptive={}) is False
    assert len(traced) == 1, f"blocked candidate traced {len(traced)}x; expected 1"


def test_rocket_shadow_scorer_never_affects_telegram_gate(orch, monkeypatch):
    """Rocket shadow is telemetry only — the Telegram gate must never consult it.
    Make any call to the shadow scorer blow up; the gate decision must be
    unaffected (still a clean pass for an unambiguous winner)."""
    from unittest.mock import MagicMock

    boom = MagicMock(side_effect=AssertionError("gate must not touch the shadow scorer"))
    monkeypatch.setattr(
        orch, "_rocket_shadow_scorer",
        MagicMock(predict_candidate=boom, predict_and_log_candidate=boom),
    )
    c = _make_candidate()  # default = unambiguous winner
    assert orch._should_send_telegram(c, adaptive={}) is True


def test_bad_ticker_candidate_is_deactivated_to_stop_refresh(orch, monkeypatch):
    """bad_ticker is a terminal block (persistent bad-list), so the candidate
    must be deactivated — the ~45s refresh loop skips inactive candidates, so it
    stops being re-enriched/re-evaluated for the next 24h."""
    monkeypatch.setattr(orch, "_is_bad_ticker", lambda ticker: True)
    c = _make_candidate(ticker="DEADCO")
    assert c.is_active is True

    allowed = orch._should_send_telegram(c, adaptive={})
    assert allowed is False
    assert _block_reason(c) == "bad_ticker"
    assert c.is_active is False
