"""
Price Target Prediction Engine — Part 8

Generates:
- target_price_1 (conservative)
- target_price_2 (aggressive)
- predicted_move_pct
- confidence

Based on:
- Resistance levels
- Liquidity zones
- Intraday range (ATR)
- Volume profile (POC, VAH, VAL)
- Momentum
"""

import logging
from dataclasses import dataclass
from typing import Optional, List

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class PriceTarget:
    """Price target prediction output."""
    ticker: str
    current_price: float = 0.0

    # Targets
    target_price_1: float = 0.0       # Conservative
    target_price_2: float = 0.0       # Aggressive
    stop_loss: float = 0.0

    # Move prediction
    predicted_move_pct: float = 0.0
    predicted_direction: str = "neutral"  # "bullish" / "bearish" / "neutral"
    confidence: float = 0.0           # 0–100

    # Derived
    reward_risk_ratio: float = 0.0
    upside_pct: float = 0.0
    downside_pct: float = 0.0

    # Basis
    atr: float = 0.0
    nearest_resistance: float = 0.0
    nearest_support: float = 0.0
    vwap: float = 0.0
    poc: float = 0.0  # Point of Control from volume profile

    # V7: Target type and dynamic adjustment
    target_type: str = "fixed_r"  # liquidity/volume_profile/momentum_extended/fixed_r
    momentum_extended: bool = False  # True if targets extended due to strong momentum
    extension_reason: str = ""  # Why targets were extended

    def to_dict(self) -> dict:
        return {
            "ticker": self.ticker,
            "current_price": self.current_price,
            "target_price_1": self.target_price_1,
            "target_price_2": self.target_price_2,
            "stop_loss": self.stop_loss,
            "predicted_move_pct": self.predicted_move_pct,
            "predicted_direction": self.predicted_direction,
            "confidence": self.confidence,
            "reward_risk_ratio": self.reward_risk_ratio,
            "atr": self.atr,
            "nearest_resistance": self.nearest_resistance,
            "nearest_support": self.nearest_support,
        }


class TargetEngine:
    """Generates price targets based on technical levels and momentum."""

    def predict(
        self,
        ticker: str,
        bars: list,
        vol_profile=None,       # VolumeProfileData
        ict_features=None,      # ICTFeatures
        liquidity=None,         # LiquidityAnalysis
        probability=None,       # ProbabilityResult
    ) -> PriceTarget:
        """Generate price targets."""
        if not bars or len(bars) < 20:
            return PriceTarget(ticker=ticker)

        h = np.array([float(b.high) for b in bars])
        l = np.array([float(b.low) for b in bars])
        c = np.array([float(b.close) for b in bars])
        v = np.array([float(b.volume) for b in bars])

        price = float(c[-1])
        result = PriceTarget(ticker=ticker, current_price=price)

        # ATR (14-period)
        atr = self._compute_atr(h, l, c, period=14)
        result.atr = round(atr, 4)

        # VWAP
        vwap = self._compute_vwap(h, l, c, v)
        result.vwap = round(vwap, 4)

        # Key levels
        resistance_levels = self._find_resistance(h, l, c, price)
        support_levels = self._find_support(h, l, c, price)

        if resistance_levels:
            result.nearest_resistance = resistance_levels[0]
        if support_levels:
            result.nearest_support = support_levels[0]

        # Volume profile levels
        if vol_profile:
            poc = getattr(vol_profile, 'poc_price', 0)
            vah = getattr(vol_profile, 'value_area_high', 0)
            val_ = getattr(vol_profile, 'value_area_low', 0)
            if poc:
                result.poc = poc
            if vah and vah > price:
                resistance_levels.insert(0, vah)
            if val_ and val_ < price:
                support_levels.insert(0, val_)

        # ICT levels
        if ict_features:
            ob_price = getattr(ict_features, 'order_block_price', 0)
            if ob_price > 0 and ob_price < price:
                support_levels.insert(0, ob_price)

        # Liquidity levels
        if liquidity:
            if liquidity.equal_highs_level > price:
                resistance_levels.insert(0, liquidity.equal_highs_level)
            if liquidity.equal_lows_level > 0 and liquidity.equal_lows_level < price:
                support_levels.insert(0, liquidity.equal_lows_level)

        # Direction from probability
        bull_prob = 50.0
        if probability:
            bull_prob = probability.bullish_probability

        is_bullish = bull_prob >= 55

        # ── Generate targets ──────────────────────────────────────────────
        if is_bullish:
            result.predicted_direction = "bullish"

            # V7: Dynamic target generation with priority: liquidity > volume profile > momentum
            target_type = "fixed_r"

            # Target 1: nearest resistance (liquidity zone) or 1.5 ATR
            if resistance_levels:
                result.target_price_1 = round(min(resistance_levels), 2)
                target_type = "liquidity"
            elif vol_profile and vol_profile.value_area_high > price:
                result.target_price_1 = round(vol_profile.value_area_high, 2)
                target_type = "volume_profile"
            else:
                result.target_price_1 = round(price + atr * 1.5, 2)

            # Target 2: second resistance or 2.5 ATR or momentum extension
            if len(resistance_levels) >= 2:
                result.target_price_2 = round(resistance_levels[1], 2)
            elif vol_profile and vol_profile.value_area_high > price:
                # Extend to next liquidity zone
                result.target_price_2 = round(vol_profile.value_area_high + atr * 0.5, 2)
            else:
                result.target_price_2 = round(price + atr * 2.5, 2)

            # V7: Momentum-based target extension
            result.target_price_1, result.target_price_2, target_type = self._apply_momentum_adjustment(
                price, result.target_price_1, result.target_price_2, atr, c, v, ict_features, target_type
            )

            # Stop loss: below nearest support or 1 ATR below
            if support_levels:
                result.stop_loss = round(max(support_levels[0], price - atr * 1.5), 2)
            else:
                result.stop_loss = round(price - atr * 1.0, 2)

        else:
            result.predicted_direction = "bearish"
            target_type = "fixed_r"

            # Bearish targets (downside)
            if support_levels:
                result.target_price_1 = round(max(support_levels), 2)
                target_type = "liquidity"
            elif vol_profile and vol_profile.value_area_low < price:
                result.target_price_1 = round(vol_profile.value_area_low, 2)
                target_type = "volume_profile"
            else:
                result.target_price_1 = round(price - atr * 1.5, 2)

            if len(support_levels) >= 2:
                result.target_price_2 = round(support_levels[1], 2)
            else:
                result.target_price_2 = round(price - atr * 2.5, 2)

            # Stop above nearest resistance
            if resistance_levels:
                result.stop_loss = round(min(resistance_levels[0], price + atr * 1.0), 2)
            else:
                result.stop_loss = round(price + atr * 1.0, 2)

        # ── Compute metrics ───────────────────────────────────────────────
        if is_bullish:
            result.upside_pct = round((result.target_price_1 - price) / price * 100, 2)
            result.downside_pct = round((price - result.stop_loss) / price * 100, 2)
            result.predicted_move_pct = result.upside_pct
        else:
            result.upside_pct = round((price - result.target_price_1) / price * 100, 2)
            result.downside_pct = round((result.stop_loss - price) / price * 100, 2)
            result.predicted_move_pct = -result.upside_pct

        if result.downside_pct > 0:
            result.reward_risk_ratio = round(result.upside_pct / result.downside_pct, 2)
        else:
            result.reward_risk_ratio = 0

        # Confidence
        conf = 50.0
        if probability:
            conf = probability.confidence
        if result.reward_risk_ratio >= 3:
            conf += 10
        elif result.reward_risk_ratio >= 2:
            conf += 5
        elif result.reward_risk_ratio < 1.5:
            conf -= 10
        result.confidence = round(max(10, min(95, conf)), 1)

        logger.info(
            "Target [%s]: dir=%s T1=%.2f T2=%.2f SL=%.2f R:R=%.1f move=%.1f%% conf=%.0f%%",
            ticker, result.predicted_direction, result.target_price_1,
            result.target_price_2, result.stop_loss,
            result.reward_risk_ratio, result.predicted_move_pct, result.confidence,
        )

        return result

    def _compute_atr(self, h, l, c, period=14):
        """Average True Range."""
        if len(h) < period + 1:
            return float(np.mean(h - l)) if len(h) > 0 else 0
        trs = []
        for i in range(1, len(h)):
            tr = max(h[i] - l[i], abs(h[i] - c[i-1]), abs(l[i] - c[i-1]))
            trs.append(tr)
        return float(np.mean(trs[-period:]))

    def _compute_vwap(self, h, l, c, v):
        """Volume Weighted Average Price."""
        typical = (h + l + c) / 3
        cum_vol = np.cumsum(v)
        cum_tp_vol = np.cumsum(typical * v)
        if cum_vol[-1] == 0:
            return float(c[-1])
        return float(cum_tp_vol[-1] / cum_vol[-1])

    def _find_resistance(self, h, l, c, price, n=5) -> List[float]:
        """Find resistance levels above current price."""
        levels = []

        # Swing highs above price
        lb = 5
        for i in range(lb, len(h) - lb):
            if h[i] == max(h[i-lb:i+lb+1]) and h[i] > price:
                levels.append(float(h[i]))

        # Recent high
        if len(h) >= 20:
            recent_high = float(np.max(h[-20:]))
            if recent_high > price:
                levels.append(recent_high)

        # Deduplicate and sort
        levels = sorted(set(round(lv, 2) for lv in levels))
        return levels[:n]

    def _find_support(self, h, l, c, price, n=5) -> List[float]:
        """Find support levels below current price."""
        levels = []

        # Swing lows below price
        lb = 5
        for i in range(lb, len(h) - lb):
            if l[i] == min(l[i-lb:i+lb+1]) and l[i] < price:
                levels.append(float(l[i]))

        # Recent low
        if len(l) >= 20:
            recent_low = float(np.min(l[-20:]))
            if recent_low < price:
                levels.append(recent_low)

        # Deduplicate and sort descending (nearest first)
        levels = sorted(set(round(lv, 2) for lv in levels), reverse=True)
        return levels[:n]

    def _apply_momentum_adjustment(
        self, price: float, t1: float, t2: float, atr: float,
        closes: np.ndarray, volumes: np.ndarray, ict_features=None, current_type: str = "fixed_r"
    ) -> tuple[float, float, str]:
        """
        V7: Dynamically adjust targets based on momentum and order flow.

        EXTEND targets if:
        - Strong momentum continuation (3+ consecutive higher closes)
        - Volume increasing with price
        - Order flow bullish (if available)

        REDUCE targets if:
        - Momentum weakening near target
        - Volume declining
        - Upper wick pressure
        """
        if len(closes) < 5:
            return t1, t2, current_type

        # Calculate recent momentum
        recent_closes = closes[-5:]
        consecutive_higher = sum(1 for i in range(1, len(recent_closes)) if recent_closes[i] > recent_closes[i-1])

        # Volume trend
        recent_vol = float(np.mean(volumes[-3:])) if len(volumes) >= 3 else 0
        prior_vol = float(np.mean(volumes[-6:-3])) if len(volumes) >= 6 else recent_vol
        volume_increasing = recent_vol > prior_vol * 1.15 if prior_vol > 0 else False

        # Check for upper wick pressure (rejection)
        upper_wick_pressure = False
        if len(closes) >= 3:
            recent_high = closes[-3:].max()
            recent_close = closes[-1]
            if recent_high > recent_close * 1.005:  # High above close by >0.5%
                upper_wick_pressure = True

        # ICT order flow check
        ict_bullish = False
        if ict_features:
            if getattr(ict_features, 'structure_break_confirmed', False):
                ict_bullish = True
            if getattr(ict_features, 'breakout_quality', '') == 'confirmed':
                ict_bullish = True

        # Decision logic
        extend_targets = (
            consecutive_higher >= 3  # Strong momentum
            and volume_increasing  # Volume confirming
            and not upper_wick_pressure  # No rejection
        ) or (
            ict_bullish  # Order flow confirmation
            and consecutive_higher >= 2
        )

        reduce_targets = (
            upper_wick_pressure  # Rejection at highs
            and not volume_increasing  # Volume not supporting
        ) or (
            consecutive_higher <= 1  # Weak momentum
            and recent_vol < prior_vol * 0.8  # Declining volume
        )

        new_t1, new_t2 = t1, t2
        new_type = current_type
        extension_reason = ""

        if extend_targets:
            # Extend targets by 0.5R (half ATR multiple)
            extension = atr * 0.5
            new_t1 = round(t1 + extension * 0.5, 2)
            new_t2 = round(t2 + extension, 2)
            new_type = "momentum_extended"
            extension_reason = f"Strong momentum ({consecutive_higher}/5 up bars) + volume increase"
        elif reduce_targets:
            # Reduce targets closer to base level
            reduction = atr * 0.3
            new_t1 = round(t1 - reduction * 0.5, 2)
            new_t2 = round(t2 - reduction, 2)
            new_type = "momentum_reduced"
            extension_reason = f"Weakening momentum + upper wick pressure"
        else:
            extension_reason = "Standard targets (neutral momentum)"

        # Log adjustment
        if new_type != current_type:
            logger.info(
                "TargetEngine V7: %s adjustment - T1: %.2f→%.2f, T2: %.2f→%.2f, reason: %s",
                "EXTENDED" if extend_targets else "REDUCED" if reduce_targets else "STANDARD",
                t1, new_t1, t2, new_t2, extension_reason
            )

        return new_t1, new_t2, new_type
