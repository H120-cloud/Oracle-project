"""
Agentic Second Leg Probability Engine — Part 5

Computes a 0-100 probability that the stock will produce a continuation (second leg)
based on catalyst, float, momentum, volume, VWAP, consolidation quality, and more.
"""

import logging

from src.core.agentic.models import (
    AgenticCandidate, SecondLegResult, ConfidenceLevel, LearningWeights,
    MomentumState,
)
from src.core.agentic.calibration_provider import get_calibration_weights

logger = logging.getLogger(__name__)

DEFAULT_WEIGHTS = LearningWeights()
MAX_MULTIPLIER = 1.15
MIN_MULTIPLIER = 0.85


def _clamp_multiplier(m: float) -> float:
    return max(MIN_MULTIPLIER, min(MAX_MULTIPLIER, m))


def _score_catalyst(candidate: AgenticCandidate) -> float:
    """0-100 score for catalyst strength and freshness."""
    s = candidate.catalyst.strength_score
    fresh = max(0, 100 - candidate.catalyst.freshness_minutes * 0.5)  # decays over ~3h
    return min(100, s * 0.7 + fresh * 0.3)


def _score_float(candidate: AgenticCandidate) -> float:
    return candidate.float_intel.float_score


def _score_volume(candidate: AgenticCandidate) -> float:
    vp = candidate.momentum.volume_persistence_pct
    if vp >= 80:
        return 95.0
    if vp >= 50:
        return 70.0
    if vp >= 30:
        return 45.0
    return 20.0


def _score_vwap(candidate: AgenticCandidate) -> float:
    if candidate.momentum.vwap_reclaimed:
        # How far above VWAP? More = stronger
        if candidate.momentum.price and candidate.momentum.vwap:
            pct_above = ((candidate.momentum.price - candidate.momentum.vwap)
                         / candidate.momentum.vwap * 100) if candidate.momentum.vwap > 0 else 0
            if pct_above > 3:
                return 90.0
            if pct_above > 1:
                return 75.0
            return 60.0
    return 15.0  # Below VWAP — weak


def _score_higher_low(candidate: AgenticCandidate) -> float:
    return 90.0 if candidate.momentum.higher_low_formed else 20.0


def _score_consolidation(candidate: AgenticCandidate) -> float:
    bars = candidate.momentum.consolidation_bars
    state = candidate.momentum.state
    if state == MomentumState.CONSOLIDATION and bars >= 8:
        return 85.0
    if state == MomentumState.CONSOLIDATION and bars >= 4:
        return 65.0
    if bars >= 2:
        return 40.0
    return 15.0


def _score_breakout(candidate: AgenticCandidate) -> float:
    return 95.0 if candidate.momentum.breakout_confirmed else 20.0


def _score_spread(candidate: AgenticCandidate) -> float:
    # Placeholder — requires level 2 data. Use float as proxy.
    if candidate.float_intel.float_shares and candidate.float_intel.float_shares < 5_000_000:
        return 40.0  # Thin stock, wide spread likely
    return 65.0


class SecondLegEngine:
    """Compute second-leg continuation probability."""

    def __init__(self, weights: LearningWeights | None = None):
        self.w = weights or DEFAULT_WEIGHTS
        self.cw = get_calibration_weights()
        if self.cw:
            logger.info("SecondLegEngine loaded calibration v%s", self.cw.version)

    def compute(self, candidate: AgenticCandidate) -> AgenticCandidate:
        scores = {
            "catalyst": _score_catalyst(candidate),
            "float": _score_float(candidate),
            "volume": _score_volume(candidate),
            "vwap": _score_vwap(candidate),
            "higher_low": _score_higher_low(candidate),
            "consolidation": _score_consolidation(candidate),
            "breakout": _score_breakout(candidate),
            "spread": _score_spread(candidate),
        }

        # Apply calibration multipliers to component scores (max 15% drift)
        if self.cw:
            if self.cw.catalyst_strength_w != 1.0 and scores["catalyst"]:
                mult = _clamp_multiplier(self.cw.catalyst_strength_w)
                scores["catalyst"] = round(min(100, scores["catalyst"] * mult), 1)
                logger.debug("SecondLegEngine calibrated catalyst score: %s", scores["catalyst"])
            if self.cw.volume_acceleration_w != 1.0 and scores["volume"]:
                mult = _clamp_multiplier(self.cw.volume_acceleration_w)
                scores["volume"] = round(min(100, scores["volume"] * mult), 1)
                logger.debug("SecondLegEngine calibrated volume score: %s", scores["volume"])
            if self.cw.vwap_hold_w != 1.0 and scores["vwap"]:
                mult = _clamp_multiplier(self.cw.vwap_hold_w)
                scores["vwap"] = round(min(100, scores["vwap"] * mult), 1)
                logger.debug("SecondLegEngine calibrated vwap score: %s", scores["vwap"])

        weights = {
            "catalyst": self.w.catalyst_strength_w + self.w.catalyst_freshness_w,
            "float": self.w.float_w,
            "volume": self.w.volume_persistence_w,
            "vwap": self.w.vwap_position_w,
            "higher_low": self.w.higher_low_w,
            "consolidation": self.w.consolidation_quality_w,
            "breakout": self.w.breakout_strength_w,
            "spread": self.w.spread_liquidity_w,
        }

        weighted_sum = sum(scores[k] * weights[k] for k in scores)
        total_weight = sum(weights.values())
        probability = weighted_sum / total_weight if total_weight > 0 else 0

        # State-based adjustments
        state = candidate.momentum.state
        if state == MomentumState.DEAD:
            probability *= 0.1
        elif state == MomentumState.FAILED:
            probability *= 0.3
        elif state == MomentumState.CONTINUATION_CONFIRMED:
            probability = min(100, probability * 1.2)
        elif state == MomentumState.INITIAL_SPIKE:
            probability *= 0.7  # Too early to judge

        # Apply final second-leg probability calibration multiplier (max 15% drift)
        if self.cw and self.cw.second_leg_probability_w != 1.0:
            mult = _clamp_multiplier(self.cw.second_leg_probability_w)
            probability = round(min(100, probability * mult), 1)
            logger.info("SecondLegEngine applied second_leg_probability_w=%s -> prob=%s", mult, probability)

        probability = round(max(0, min(100, probability)), 1)

        # Confidence level
        if probability >= 80:
            conf = ConfidenceLevel.VERY_HIGH
        elif probability >= 65:
            conf = ConfidenceLevel.HIGH
        elif probability >= 50:
            conf = ConfidenceLevel.WATCH
        else:
            conf = ConfidenceLevel.LOW

        # Build reasons
        reasons = []
        if scores["catalyst"] >= 70:
            reasons.append(f"Strong catalyst ({candidate.catalyst.catalyst_type.value})")
        if scores["volume"] >= 70:
            reasons.append("Volume persisting above spike levels")
        if candidate.momentum.vwap_reclaimed:
            reasons.append("Holding above VWAP")
        if candidate.momentum.higher_low_formed:
            reasons.append("Higher low confirmed")
        if candidate.momentum.breakout_confirmed:
            reasons.append("Breaking consolidation")

        warnings = []
        if scores["volume"] < 40:
            warnings.append("Volume fading")
        if not candidate.momentum.vwap_reclaimed:
            warnings.append("Below VWAP")
        if candidate.float_intel.dilution_risk:
            warnings.append("Dilution risk detected")

        candidate.second_leg = SecondLegResult(
            probability=probability,
            confidence_level=conf,
            components=scores,
            reasons=reasons,
            warnings=warnings,
            calibrated=bool(self.cw),
        )

        return candidate
