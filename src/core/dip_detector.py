"""
Dip Detection Engine — V1 (rule-based)

Evaluates whether a stock is experiencing a pullback and scores the
dip probability (0-100) with a phase classification (early/mid/late).

Inputs (computed from OHLCV + indicators):
  - distance from VWAP
  - EMA distance (9, 20)
  - % drop from intraday high
  - lower-high count
  - red candle volume spikes
  - momentum decay
"""

import logging
from dataclasses import dataclass

from src.models.schemas import DipFeatures, DipResult, DipPhase

logger = logging.getLogger(__name__)


# ── Configurable thresholds ──────────────────────────────────────────────────

@dataclass
class DipThresholds:
    # Minimum % below VWAP to consider a dip
    vwap_min_distance: float = -0.3
    # Minimum % below EMA-9
    ema9_min_distance: float = -0.5
    # Minimum % drop from high to flag a dip
    min_drop_from_high: float = 2.0
    # Red candle volume ratio threshold
    red_vol_ratio_threshold: float = 1.3
    # Consecutive red candles to flag
    min_red_candles: int = 2
    # Lower-high count to confirm trend
    min_lower_highs: int = 2
    # Minimum probability to be considered a valid dip
    validity_threshold: float = 40.0
    # V7: Falling knife thresholds
    falling_knife_velocity: float = -2.0  # Reject if velocity < -2%
    falling_knife_acceleration: float = -0.5  # Reject if acceleration < -0.5
    # V7: Momentum bonus thresholds
    slowing_momentum_bonus: float = 10.0  # Bonus for slowing sell pressure
    structure_penalty: float = 15.0  # Penalty for broken structure


class DipDetector:
    """Rule-based dip detection scoring engine."""

    def __init__(self, thresholds: DipThresholds | None = None):
        self.t = thresholds or DipThresholds()

    def detect(self, ticker: str, features: DipFeatures) -> DipResult:
        score = 0.0
        reasons: list[str] = []
        warnings: list[str] = []
        quality_score = 0.0

        # V7: FALLING KNIFE DETECTION - Hard reject
        is_falling_knife = (
            features.price_velocity < self.t.falling_knife_velocity
            and features.price_acceleration < self.t.falling_knife_acceleration
        )

        if is_falling_knife:
            warnings.append(
                f"FALLING KNIFE: velocity={features.price_velocity:.2f}%, "
                f"acceleration={features.price_acceleration:.2f}%"
            )
            # Severe penalty - reduces probability by 50+ points
            score -= 50.0

        # V7: Momentum-aware scoring
        momentum_bonus = 0.0
        if features.momentum_state == "slowing_down":
            # Selling pressure slowing - good for bounce
            momentum_bonus = self.t.slowing_momentum_bonus
            score += momentum_bonus
            reasons.append(f"Selling slowing (velocity={features.price_velocity:.2f}%)")
        elif features.momentum_state == "accelerating_down":
            # Selling accelerating - danger
            momentum_bonus = -20.0
            score += momentum_bonus
            warnings.append(f"Selling accelerating (accel={features.price_acceleration:.2f}%)")

        # V7: Structure validation
        if not features.structure_intact:
            score -= self.t.structure_penalty
            warnings.append("Structure broken (no higher low/reclaim)")
        else:
            quality_score += 10.0
            reasons.append("Structure intact (higher low or reclaim)")

        # 1. VWAP distance — stock trading below VWAP
        if features.vwap_distance_pct < self.t.vwap_min_distance:
            contribution = min(abs(features.vwap_distance_pct) * 5, 20)
            score += contribution
            reasons.append(f"Below VWAP by {features.vwap_distance_pct:.1f}%")

        # 2. EMA-9 distance
        if features.ema9_distance_pct < self.t.ema9_min_distance:
            contribution = min(abs(features.ema9_distance_pct) * 4, 15)
            score += contribution
            reasons.append(f"Below EMA-9 by {features.ema9_distance_pct:.1f}%")

        # 3. EMA-20 distance
        if features.ema20_distance_pct < 0:
            contribution = min(abs(features.ema20_distance_pct) * 3, 10)
            score += contribution

        # 4. Drop from intraday high
        if features.drop_from_high_pct >= self.t.min_drop_from_high:
            contribution = min(features.drop_from_high_pct * 3, 20)
            score += contribution
            reasons.append(f"Dropped {features.drop_from_high_pct:.1f}% from high")

        # 5. Consecutive red candles
        if features.consecutive_red_candles >= self.t.min_red_candles:
            contribution = min(features.consecutive_red_candles * 4, 12)
            score += contribution
            reasons.append(f"{features.consecutive_red_candles} consecutive red candles")

        # 6. Red candle volume ratio (sellers aggressive)
        if features.red_candle_volume_ratio >= self.t.red_vol_ratio_threshold:
            contribution = min(
                (features.red_candle_volume_ratio - 1.0) * 10, 13
            )
            score += contribution
            reasons.append(
                f"Red candle vol ratio {features.red_candle_volume_ratio:.2f}x"
            )

        # 7. Lower highs
        if features.lower_highs_count >= self.t.min_lower_highs:
            contribution = min(features.lower_highs_count * 3, 10)
            score += contribution
            reasons.append(f"{features.lower_highs_count} lower highs")

        # Clamp to 0-100
        probability = max(0.0, min(score, 100.0))

        # Determine phase
        phase = self._classify_phase(probability, features)

        # V7: Enhanced validity - require structure intact AND not falling knife
        is_valid = (
            probability >= self.t.validity_threshold
            and not is_falling_knife
            and features.structure_intact
        )

        # V7: Dip quality score (0-100)
        dip_quality = quality_score + (momentum_bonus if momentum_bonus > 0 else 0)
        dip_quality += probability * 0.5  # 50% weight on base probability
        dip_quality = max(0.0, min(100.0, dip_quality))

        logger.info(
            "DipDetector V7 [%s]: prob=%.1f quality=%.1f phase=%s valid=%s "
            "momentum=%s structure=%s falling_knife=%s reasons=%s warnings=%s",
            ticker, probability, dip_quality, phase.value, is_valid,
            features.momentum_state, features.structure_intact, is_falling_knife,
            reasons, warnings,
        )

        return DipResult(
            ticker=ticker,
            probability=round(probability, 1),
            phase=phase,
            features=features,
            is_valid_dip=is_valid,
        )

    @staticmethod
    def _classify_phase(probability: float, features: DipFeatures) -> DipPhase:
        if probability < 35:
            return DipPhase.EARLY
        if probability < 65:
            return DipPhase.MID
        return DipPhase.LATE
