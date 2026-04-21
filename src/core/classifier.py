"""
Classification System — V1 (rule-based)

Classifies each stock into one of:
  - dip_forming
  - bounce_forming
  - breakout_continuation
  - sideways
  - breakdown_risk
  - overextended
  - no_valid_setup
"""

import logging
from typing import Optional

from src.models.schemas import (
    StockClassification,
    DipResult,
    BounceResult,
    DipPhase,
)

logger = logging.getLogger(__name__)


class StockClassifier:
    """Classify a stock's current state from dip/bounce analysis."""

    def classify(
        self,
        dip: Optional[DipResult],
        bounce: Optional[BounceResult],
        change_percent: Optional[float] = None,
    ) -> StockClassification:

        has_dip = dip is not None and dip.is_valid_dip
        has_bounce = bounce is not None and bounce.is_valid_bounce
        has_bounce_signal = bounce is not None and bounce.probability > 0

        # Bounce forming takes precedence when both dip and bounce are valid
        if has_bounce and bounce.entry_ready:
            return StockClassification.BOUNCE_FORMING

        # Both dip and bounce signals present (bounce developing but not fully ready)
        if has_dip and has_bounce_signal:
            # Late-phase dip with no real bounce => breakdown risk
            if dip.phase == DipPhase.LATE and dip.probability >= 75 and bounce.probability < 15:
                return StockClassification.BREAKDOWN_RISK
            return StockClassification.DIP_BOUNCE_FORMING

        if has_dip:
            # Late-phase dip with no bounce => breakdown risk
            if dip.phase == DipPhase.LATE and dip.probability >= 75:
                return StockClassification.BREAKDOWN_RISK
            return StockClassification.DIP_FORMING

        # Strong gainer with no dip signals — might be overextended
        if change_percent is not None and change_percent > 15:
            return StockClassification.OVEREXTENDED

        # Moderate gainer with no dip — possible continuation
        if change_percent is not None and change_percent > 5:
            return StockClassification.BREAKOUT_CONTINUATION

        # Low movement — sideways
        if (
            change_percent is not None
            and -2 < change_percent < 2
        ):
            return StockClassification.SIDEWAYS

        return StockClassification.NO_VALID_SETUP
