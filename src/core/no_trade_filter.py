"""
No-Trade Filter — V1

Hard-gate filter that rejects low-quality or dangerous setups.
The system must be willing to say "NO VALID SETUP" rather than force trades.
"""

import logging
from dataclasses import dataclass
from typing import Optional

from src.models.schemas import (
    DipResult,
    BounceResult,
    StockClassification,
    ScannedStock,
)

logger = logging.getLogger(__name__)


@dataclass
class FilterThresholds:
    min_dip_probability: float = 35.0
    min_bounce_probability: float = 35.0
    max_spread_pct: float = 1.0  # placeholder for V3 spread data
    min_volume: float = 300_000
    blocked_classifications: tuple = (
        StockClassification.BREAKDOWN_RISK,
        StockClassification.OVEREXTENDED,
        StockClassification.SIDEWAYS,
        StockClassification.NO_VALID_SETUP,
    )


@dataclass
class FilterResult:
    passed: bool
    reasons: list[str]


class NoTradeFilter:
    """Rejects setups that don't meet minimum quality thresholds."""

    def __init__(self, thresholds: FilterThresholds | None = None):
        self.t = thresholds or FilterThresholds()

    def evaluate(
        self,
        stock: ScannedStock,
        classification: StockClassification,
        dip: Optional[DipResult] = None,
        bounce: Optional[BounceResult] = None,
    ) -> FilterResult:
        rejections: list[str] = []

        # 1. Classification gate
        if classification in self.t.blocked_classifications:
            rejections.append(f"Blocked classification: {classification.value}")

        # 2. Volume gate
        if stock.volume < self.t.min_volume:
            rejections.append(
                f"Volume {stock.volume:,.0f} below minimum {self.t.min_volume:,.0f}"
            )

        # 3. Dip quality gate
        if dip is not None and dip.probability < self.t.min_dip_probability:
            rejections.append(
                f"Dip probability {dip.probability:.1f}% below threshold"
            )

        # 4. Bounce quality gate
        if bounce is not None and bounce.probability < self.t.min_bounce_probability:
            rejections.append(
                f"Bounce probability {bounce.probability:.1f}% below threshold"
            )

        passed = len(rejections) == 0

        if not passed:
            logger.info(
                "NoTradeFilter REJECTED [%s]: %s", stock.ticker, rejections
            )

        return FilterResult(passed=passed, reasons=rejections)
