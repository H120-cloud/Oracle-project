"""
Bounce Detection Engine — V1 (rule-based)

Evaluates whether a dip is ending and a bounce is forming.

Inputs:
  - distance from nearest support
  - change in selling pressure
  - buy/sell volume ratio
  - higher-low formation
  - key-level reclaim
  - RSI / MACD histogram (optional)
"""

import logging
from dataclasses import dataclass

from src.models.schemas import BounceFeatures, BounceResult

logger = logging.getLogger(__name__)


@dataclass
class BounceThresholds:
    # Max distance from support to be in "bounce zone"
    max_support_distance_pct: float = 1.5
    # Selling pressure must decrease by this much (negative = less selling)
    selling_pressure_reduction: float = -0.1
    # Minimum buy/sell ratio to flag buying pressure
    min_buy_sell_ratio: float = 1.1
    # RSI oversold boundary
    rsi_oversold: float = 35.0
    # Minimum MACD histogram slope for upturn
    macd_upturn_threshold: float = 0.0
    # Minimum probability to be valid bounce
    validity_threshold: float = 40.0
    # Minimum probability to signal entry readiness
    entry_readiness_threshold: float = 60.0


class BounceDetector:
    """Rule-based bounce detection scoring engine."""

    def __init__(self, thresholds: BounceThresholds | None = None):
        self.t = thresholds or BounceThresholds()

    def detect(
        self, ticker: str, features: BounceFeatures, current_price: float
    ) -> BounceResult:
        score = 0.0
        reasons: list[str] = []

        # 1. Near support
        if abs(features.support_distance_pct) <= self.t.max_support_distance_pct:
            contribution = (
                self.t.max_support_distance_pct - abs(features.support_distance_pct)
            ) / self.t.max_support_distance_pct * 20
            score += contribution
            reasons.append(
                f"Near support ({features.support_distance_pct:.1f}% away)"
            )

        # 2. Reduced selling pressure
        if features.selling_pressure_change < self.t.selling_pressure_reduction:
            contribution = min(abs(features.selling_pressure_change) * 15, 20)
            score += contribution
            reasons.append("Selling pressure declining")

        # 3. Buying pressure ratio
        if features.buying_pressure_ratio >= self.t.min_buy_sell_ratio:
            contribution = min(
                (features.buying_pressure_ratio - 1.0) * 20, 20
            )
            score += contribution
            reasons.append(
                f"Buy/sell ratio {features.buying_pressure_ratio:.2f}"
            )

        # 4. Higher low formed
        if features.higher_low_formed:
            score += 15
            reasons.append("Higher low formed")

        # 5. Key level reclaimed
        if features.key_level_reclaimed:
            score += 10
            reasons.append("Key level reclaimed")

        # 6. RSI oversold bounce
        if features.rsi is not None and features.rsi <= self.t.rsi_oversold:
            contribution = min((self.t.rsi_oversold - features.rsi) * 0.5, 10)
            score += contribution
            reasons.append(f"RSI oversold at {features.rsi:.1f}")

        # 7. MACD histogram turning up
        if (
            features.macd_histogram_slope is not None
            and features.macd_histogram_slope > self.t.macd_upturn_threshold
        ):
            contribution = min(features.macd_histogram_slope * 20, 10)
            score += contribution
            reasons.append("MACD histogram turning up")

        probability = max(0.0, min(score, 100.0))
        is_valid = probability >= self.t.validity_threshold
        entry_ready = probability >= self.t.entry_readiness_threshold

        # Trigger price: slight buffer above current price for confirmation
        trigger_price = round(current_price * 1.002, 2) if entry_ready else None

        logger.info(
            "BounceDetector [%s]: prob=%.1f entry_ready=%s valid=%s reasons=%s",
            ticker, probability, entry_ready, is_valid, reasons,
        )

        return BounceResult(
            ticker=ticker,
            probability=round(probability, 1),
            entry_ready=entry_ready,
            trigger_price=trigger_price,
            features=features,
            is_valid_bounce=is_valid,
        )
