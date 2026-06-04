"""
Pre-News V2 — Pattern Memory (Step 12)

Compares current anomaly features to historical winner/loser outcomes and
returns similarity scores.

Guardrails per spec:
  - Minimum 100 total outcomes before similarity is activated
  - Minimum 30 outcomes per anomaly_type
  - No single feature > 40% influence on composite
  - Pass-through (returns 50/50 neutral) when insufficient data

Does NOT auto-change live thresholds — it only produces `winner_similarity_score`
and `loser_similarity_score` which the detector uses as tie-breakers, not hard gates.
"""

from __future__ import annotations

import logging
import math
from collections import defaultdict
from typing import Optional

from src.core.agentic.pre_news_models import (
    PreNewsAnomaly,
    PreNewsOutcome,
    TimingStage,
)

logger = logging.getLogger(__name__)

MIN_TOTAL_OUTCOMES = 100
MIN_PER_TYPE = 30

# Feature weights for similarity (each < 40% per guardrail)
FEATURE_WEIGHTS = {
    "rvol":                 0.18,
    "smart_money":          0.20,
    "buy_pressure":         0.15,
    "float_pressure":       0.15,
    "volume_acceleration":  0.12,
    "session":              0.10,
    "timing_stage":         0.10,
}


def _is_winner(o: PreNewsOutcome) -> bool:
    """A winner has a real price move and isn't classified as pump."""
    return bool(o.was_real_move) and not bool(o.was_pump)


def _is_loser(o: PreNewsOutcome) -> bool:
    """A loser is a false alarm or pump."""
    return bool(o.was_false_alarm) or bool(o.was_pump)


def _feature_vector(anomaly_like) -> dict:
    """
    Extract comparable feature vector from either an anomaly or an outcome.
    Missing features get neutral defaults (50 or None) so comparisons are stable.
    """
    # PreNewsAnomaly path
    if hasattr(anomaly_like, "volume_metrics"):
        a = anomaly_like
        return {
            "rvol": a.volume_metrics.rvol_current or 0.0,
            "smart_money": a.smart_money_score,
            "buy_pressure": a.buy_pressure_score,
            "float_pressure": a.float_pressure_score,
            "volume_acceleration": a.volume_metrics.volume_acceleration_score,
            "session": a.session.value,
            "timing_stage": a.timing_stage.value,
        }

    # PreNewsOutcome path
    o = anomaly_like
    return {
        "rvol": o.rvol_at_detection or 0.0,
        "smart_money": o.smart_money_score_at_detection if o.smart_money_score_at_detection is not None else 50.0,
        "buy_pressure": o.buy_pressure_score_at_detection if o.buy_pressure_score_at_detection is not None else 50.0,
        "float_pressure": o.float_pressure_score_at_detection if o.float_pressure_score_at_detection is not None else 50.0,
        "volume_acceleration": 50.0,  # not snapshotted pre-V2
        "session": o.session_at_detection.value if o.session_at_detection else "open",
        "timing_stage": o.timing_stage_at_detection.value if o.timing_stage_at_detection else TimingStage.EARLY.value,
    }


def _numeric_similarity(a: float, b: float, scale: float = 100.0) -> float:
    """Returns 0-1 similarity based on normalized absolute distance."""
    if scale <= 0:
        return 0.5
    diff = abs(a - b) / scale
    return max(0.0, 1.0 - diff)


def _similarity(vec_a: dict, vec_b: dict) -> float:
    """
    Cosine-ish weighted similarity 0-1 between two feature vectors.
    """
    total = 0.0

    # RVOL: scale 0-10x roughly, compress with log
    ra = math.log1p(max(0, vec_a["rvol"]))
    rb = math.log1p(max(0, vec_b["rvol"]))
    total += _numeric_similarity(ra, rb, scale=3.0) * FEATURE_WEIGHTS["rvol"]

    # 0-100 scores
    for key in ("smart_money", "buy_pressure", "float_pressure", "volume_acceleration"):
        total += _numeric_similarity(vec_a[key], vec_b[key], scale=100.0) * FEATURE_WEIGHTS[key]

    # Categorical: exact match or not
    total += (1.0 if vec_a["session"] == vec_b["session"] else 0.0) * FEATURE_WEIGHTS["session"]
    total += (1.0 if vec_a["timing_stage"] == vec_b["timing_stage"] else 0.0) * FEATURE_WEIGHTS["timing_stage"]

    return total  # sum of weights = 1.0 → score is 0-1


class PreNewsPatternMemory:
    """Compute winner/loser similarity for a new anomaly using past outcomes."""

    def __init__(self, outcomes: list[PreNewsOutcome]):
        self.outcomes = outcomes or []
        self.winners: list[PreNewsOutcome] = [o for o in self.outcomes if _is_winner(o)]
        self.losers: list[PreNewsOutcome] = [o for o in self.outcomes if _is_loser(o)]

        self.active = (
            len(self.outcomes) >= MIN_TOTAL_OUTCOMES
            and len(self.winners) >= 10
            and len(self.losers) >= 10
        )

        self._by_type = defaultdict(int)
        for o in self.outcomes:
            self._by_type[o.anomaly_type.value] += 1

        if self.active:
            logger.info(
                "PreNewsPatternMemory active — %d winners, %d losers (%d total)",
                len(self.winners), len(self.losers), len(self.outcomes),
            )
        else:
            logger.info(
                "PreNewsPatternMemory insufficient data: %d outcomes (need %d)",
                len(self.outcomes), MIN_TOTAL_OUTCOMES,
            )

    def score(self, anomaly: PreNewsAnomaly) -> tuple[float, float]:
        """
        Returns (winner_similarity_0_100, loser_similarity_0_100).

        Neutral 50/50 when pattern memory is inactive (below thresholds).
        """
        if not self.active:
            return 50.0, 50.0

        # Optional per-type sufficiency
        type_count = self._by_type.get(anomaly.anomaly_type.value, 0)
        if type_count < MIN_PER_TYPE:
            return 50.0, 50.0

        cur = _feature_vector(anomaly)

        # Average similarity to all winners
        sims_w = [_similarity(cur, _feature_vector(o)) for o in self.winners]
        sims_l = [_similarity(cur, _feature_vector(o)) for o in self.losers]

        ws = (sum(sims_w) / len(sims_w)) * 100.0 if sims_w else 50.0
        ls = (sum(sims_l) / len(sims_l)) * 100.0 if sims_l else 50.0

        return round(ws, 1), round(ls, 1)
