"""
Signal Ranker — V2

Ranks signals by composite quality score and returns the top N.
Factors:
  - bounce probability
  - risk score (inverted — lower risk = better)
  - setup grade
  - confidence
  - risk-adjusted return estimate
"""

import logging
from typing import Optional

from src.models.schemas import TradingSignal, SignalAction

logger = logging.getLogger(__name__)

# Grade → numeric value for ranking
GRADE_VALUES = {"A": 5, "B": 4, "C": 3, "D": 2, "F": 1}


class SignalRanker:
    """Rank and filter signals to surface the best setups."""

    def __init__(self, top_n: int = 5):
        self.top_n = top_n

    def rank(self, signals: list[TradingSignal]) -> list[TradingSignal]:
        """
        Score each signal, sort descending, return top N.
        Only BUY and WATCH signals are ranked; others are appended at the end.
        """
        rankable = []
        non_rankable = []

        for sig in signals:
            if sig.action in (SignalAction.BUY, SignalAction.WATCH):
                rankable.append(sig)
            else:
                non_rankable.append(sig)

        scored = [(sig, self._composite_score(sig)) for sig in rankable]
        scored.sort(key=lambda x: x[1], reverse=True)

        top = [sig for sig, _ in scored[: self.top_n]]

        logger.info(
            "Ranked %d signals → top %d: %s",
            len(rankable),
            len(top),
            [f"{s.ticker}({s.action.value})" for s in top],
        )

        return top + non_rankable

    def _composite_score(self, signal: TradingSignal) -> float:
        """Compute a single ranking score for a signal."""
        score = 0.0

        # Bounce probability (0-100 → 0-30 points)
        if signal.bounce_probability is not None:
            score += signal.bounce_probability * 0.3

        # Dip probability (0-100 → 0-15 points)
        if signal.dip_probability is not None:
            score += signal.dip_probability * 0.15

        # Risk score (1-10, inverted → 0-20 points; lower risk = more points)
        if signal.risk_score is not None:
            score += (11 - signal.risk_score) * 2.0

        # Setup grade (A=5 → 0-15 points)
        if signal.setup_grade is not None:
            score += GRADE_VALUES.get(signal.setup_grade, 1) * 3.0

        # Confidence (0-100 → 0-20 points)
        if signal.confidence is not None:
            score += signal.confidence * 0.2

        # Risk-adjusted return estimate
        if (
            signal.entry_price is not None
            and signal.stop_price is not None
            and signal.target_prices
        ):
            risk = signal.entry_price - signal.stop_price
            reward = signal.target_prices[-1] - signal.entry_price
            if risk > 0:
                rr_ratio = reward / risk
                score += min(rr_ratio * 3.0, 15.0)  # cap at 15 points

        # BUY signals get a bonus over WATCH
        if signal.action == SignalAction.BUY:
            score += 10.0

        return score
