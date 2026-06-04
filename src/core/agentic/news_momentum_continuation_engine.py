"""
News Momentum Continuation Probability Engine (V22)

Predicts same-day, next-day, and multi-session continuation probability.
"""

from __future__ import annotations

import logging
from typing import Optional

from src.core.agentic.news_momentum_models import (
    NewsMomentumCandidate,
    ContinuationProbability,
    MultiDayContinuation,
    MultiDayClass,
    OracleAction,
)

logger = logging.getLogger(__name__)


CATALYST_CONTINUATION_MULTIPLIERS = {
    "fda_approval": 1.45,
    "fda_clearance": 1.35,
    "breakthrough_therapy": 1.35,
    "buyout": 1.50,
    "acquisition": 1.40,
    "merger": 1.35,
    "ai_partnership": 1.30,
    "nvidia_partnership": 1.35,
    "openai_partnership": 1.30,
    "earnings_beat": 1.20,
    "guidance_raise": 1.18,
    "profitability_inflection": 1.25,
    "topline_data": 1.30,
    "phase_3": 1.30,
    "phase_2": 1.20,
    "hyperscaler_contract": 1.25,
    "bitcoin_treasury": 1.25,
    "offering": 0.20,
    "atm_filing": 0.15,
    "vague_pr": 0.25,
    "reverse_split": 0.10,
}


def compute_continuation_probability(
    candidate: NewsMomentumCandidate,
    historical_stats: Optional[dict] = None,
) -> ContinuationProbability:
    """
    Predict continuation probabilities based on catalyst type,
    price action, volume, and VWAP behavior.
    """
    cp = ContinuationProbability()

    # Base probabilities from catalyst type
    cat = candidate.catalyst_sub_type.value
    mult = CATALYST_CONTINUATION_MULTIPLIERS.get(cat, 1.0)

    # Same-day continuation
    base_same = 55.0
    if candidate.news_impact_score > 65:
        base_same += 20.0
    if candidate.news_impact_score > 80:
        base_same += 10.0
    if candidate.news_reaction_score > 50:
        base_same += 12.0
    if candidate.rvol and candidate.rvol > 2:
        base_same += 10.0
    if candidate.move_pct > 10 and candidate.move_pct < 80:
        base_same += 12.0
    if candidate.move_pct > 80:
        base_same -= 10.0
    if candidate.trap_risk > 65:
        base_same -= 20.0
    if candidate.dilution_risk > 50:
        base_same -= 25.0
    cp.same_day_continuation = round(max(0.0, min(100.0, base_same * mult)), 1)

    # Second leg probability
    base_second = cp.same_day_continuation * 0.6
    if candidate.move_pct > 40 and candidate.move_pct < 100:
        base_second += 15.0
    if candidate.rvol and candidate.rvol > 5:
        base_second += 10.0
    cp.second_leg_probability = round(max(0.0, min(100.0, base_second)), 1)

    # Next day continuation
    base_next = 35.0
    if candidate.session.value == "after_hours":
        base_next += 15.0
    if candidate.news_impact_score > 75:
        base_next += 15.0
    if candidate.move_pct > 30 and candidate.move_pct < 80:
        base_next += 10.0
    if candidate.dilution_risk < 20:
        base_next += 10.0
    if candidate.trap_risk > 50:
        base_next -= 20.0
    cp.continuation_tomorrow = round(max(0.0, min(100.0, base_next * mult)), 1)

    # Gap up probability
    cp.gap_up_next_session = round(cp.continuation_tomorrow * 0.7, 1)

    # Fade probability
    cp.fade_probability = round(100.0 - cp.same_day_continuation, 1)

    # Apply historical stats
    if historical_stats and cat in historical_stats:
        stats = historical_stats[cat]
        hist_cont = stats.get("continuation_rate", 50.0)
        hist_fade = stats.get("fade_rate", 30.0)
        # Blend with historical
        cp.same_day_continuation = round((cp.same_day_continuation * 0.6 + hist_cont * 0.4), 1)
        cp.fade_probability = round((cp.fade_probability * 0.6 + hist_fade * 0.4), 1)

    return cp


def compute_multi_day_continuation(
    candidate: NewsMomentumCandidate,
    continuation: ContinuationProbability,
    historical_stats: Optional[dict] = None,
) -> MultiDayContinuation:
    """
    Predict multi-day continuation potential.
    """
    md = MultiDayContinuation()
    cat = candidate.catalyst_sub_type.value
    mult = CATALYST_CONTINUATION_MULTIPLIERS.get(cat, 1.0)

    # Base multi-day score
    base = continuation.continuation_tomorrow * 0.5
    if candidate.news_impact_score > 75:
        base += 20.0
    if candidate.move_pct > 30 and candidate.move_pct < 100:
        base += 10.0
    if candidate.dilution_risk < 20:
        base += 10.0
    if candidate.trap_risk > 50:
        base -= 20.0
    if candidate.session.value == "after_hours" and candidate.move_pct > 30:
        base += 10.0

    md.multi_day_score = round(max(0.0, min(100.0, base * mult)), 1)

    # Probability breakdowns
    md.next_day_continuation_probability = continuation.continuation_tomorrow
    md.two_day_continuation_probability = round(md.multi_day_score * 0.7, 1)
    md.five_day_continuation_probability = round(md.multi_day_score * 0.4, 1)
    md.next_day_gap_up_probability = continuation.gap_up_next_session
    md.multi_day_fade_probability = round(100.0 - md.multi_day_score, 1)
    md.exhaustion_probability = candidate.trap_risk
    md.swing_trade_quality_score = round(
        (md.multi_day_score * 0.4 +
         continuation.continuation_tomorrow * 0.3 +
         (100 - candidate.trap_risk) * 0.15 +
         (100 - candidate.dilution_risk) * 0.15), 1
    )

    # Classification
    if md.multi_day_score >= 80:
        md.classification = MultiDayClass.SWING_RUNNER
    elif md.multi_day_score >= 65:
        md.classification = MultiDayClass.STRONG_MULTI_DAY_CANDIDATE
    elif md.multi_day_score >= 50:
        md.classification = MultiDayClass.POSSIBLE_CONTINUATION
    elif md.exhaustion_probability > 70:
        md.classification = MultiDayClass.EXHAUSTED
    elif md.multi_day_fade_probability > 70:
        md.classification = MultiDayClass.LIKELY_FADE
    else:
        md.classification = MultiDayClass.ONE_DAY_SPIKE_ONLY

    # Apply historical stats
    if historical_stats and cat in historical_stats:
        stats = historical_stats[cat]
        hist_multi = stats.get("multi_day_rate", 30.0)
        md.multi_day_score = round((md.multi_day_score * 0.6 + hist_multi * 0.4), 1)

    return md


def determine_oracle_action(
    candidate: NewsMomentumCandidate,
    continuation: ContinuationProbability,
    multi_day: MultiDayContinuation,
) -> OracleAction:
    """Determine the recommended action for a candidate."""
    if candidate.dilution_risk > 60 or candidate.trap_risk > 80:
        return OracleAction.AVOID_TRAP
    if candidate.move_pct > 200:
        return OracleAction.AVOID_CHASE
    if multi_day.classification in (MultiDayClass.SWING_RUNNER, MultiDayClass.STRONG_MULTI_DAY_CANDIDATE):
        return OracleAction.SWING_WATCH
    if continuation.same_day_continuation > 55 and candidate.move_pct < 120:
        return OracleAction.TRADEABLE
    if candidate.move_pct < 30 and candidate.news_impact_score > 50:
        return OracleAction.WATCH
    if continuation.second_leg_probability > 50:
        return OracleAction.WAIT_FOR_RETEST
    return OracleAction.WATCH


def estimate_move_range(
    candidate: NewsMomentumCandidate,
) -> dict:
    """Estimate conservative, bullish, and extreme price move percentages."""
    base = candidate.news_impact_score * 0.5
    float_mult = {"ultra_low": 2.0, "low": 1.5, "medium": 1.0, "high": 0.6}.get(
        candidate.float_category.value, 1.0
    )

    conservative = base * 0.3 * float_mult
    bullish = base * 0.7 * float_mult
    extreme = base * 1.5 * float_mult

    return {
        "conservative_pct": round(conservative, 1),
        "bullish_pct": round(bullish, 1),
        "extreme_pct": round(extreme, 1),
    }
