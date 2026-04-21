"""
Enhanced Probability Engine — Part 6

Computes bullish_probability and bearish_probability (0–100) using:
- Catalyst strength + freshness + reaction
- Volume profile
- Structure (ICT / liquidity)
- Trend alignment (multi-timeframe)
- Market context
- Liquidity signals
"""

import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class ProbabilityResult:
    """Composite probability output."""
    ticker: str
    bullish_probability: float = 50.0   # 0–100
    bearish_probability: float = 50.0   # 0–100

    # Component scores (each 0–100)
    catalyst_score: float = 0.0
    freshness_score: float = 0.0
    reaction_score: float = 0.0
    volume_score: float = 0.0
    structure_score: float = 0.0
    trend_score: float = 0.0
    liquidity_score: float = 0.0
    market_context_score: float = 0.0
    mtf_alignment_score: float = 0.0

    # Confidence in the probability estimate
    confidence: float = 50.0
    dominant_factor: str = "none"

    def to_dict(self) -> dict:
        return {
            "ticker": self.ticker,
            "bullish_probability": self.bullish_probability,
            "bearish_probability": self.bearish_probability,
            "confidence": self.confidence,
            "dominant_factor": self.dominant_factor,
            "components": {
                "catalyst": self.catalyst_score,
                "freshness": self.freshness_score,
                "reaction": self.reaction_score,
                "volume": self.volume_score,
                "structure": self.structure_score,
                "trend": self.trend_score,
                "liquidity": self.liquidity_score,
                "market_context": self.market_context_score,
                "mtf_alignment": self.mtf_alignment_score,
            },
        }


# Component weights for probability calculation
WEIGHTS = {
    "catalyst":       0.15,
    "freshness":      0.08,
    "reaction":       0.12,
    "volume":         0.12,
    "structure":      0.15,
    "trend":          0.12,
    "liquidity":      0.10,
    "market_context": 0.08,
    "mtf_alignment":  0.08,
}


class ProbabilityEngine:
    """
    Aggregates all analysis components into a composite probability.
    """

    def compute(
        self,
        ticker: str,
        news_summary=None,        # TickerNewsSummary
        market_context=None,      # MarketContext
        mtf_result=None,          # MTFResult
        liquidity=None,           # LiquidityAnalysis
        ict_features=None,        # ICTFeatures
        dip_result=None,          # DipResult
        bounce_result=None,       # BounceResult
        bearish_data=None,        # BearishTransitionData
        stock=None,               # ScannedStock
        vol_profile=None,         # VolumeProfileData
    ) -> ProbabilityResult:
        """Compute composite bullish/bearish probabilities."""
        result = ProbabilityResult(ticker=ticker)

        # 1. Catalyst score
        if news_summary:
            result.catalyst_score = min(100, news_summary.catalyst_score)

        # 2. Freshness score
        if news_summary and news_summary.freshness_label:
            freshness_map = {
                "BREAKING": 100, "FRESH": 80, "SAME_DAY": 60,
                "AGING": 30, "STALE": 10, "DEAD": 0,
            }
            result.freshness_score = freshness_map.get(
                news_summary.freshness_label.value if hasattr(news_summary.freshness_label, 'value')
                else str(news_summary.freshness_label), 0
            )

        # 3. Reaction score
        if news_summary and news_summary.reaction_state:
            reaction_map = {
                "ACTIVE": 90, "INITIAL": 60, "NO_REACTION": 20,
                "FADING": 15, "EXHAUSTED": 5,
            }
            result.reaction_score = reaction_map.get(
                news_summary.reaction_state.value if hasattr(news_summary.reaction_state, 'value')
                else str(news_summary.reaction_state), 20
            )

        # 4. Volume score
        if stock:
            rvol = getattr(stock, 'rvol', None) or 0
            vol = getattr(stock, 'volume', 0)
            if rvol >= 3.0:
                result.volume_score = 95
            elif rvol >= 2.0:
                result.volume_score = 80
            elif rvol >= 1.5:
                result.volume_score = 65
            elif rvol >= 1.0:
                result.volume_score = 45
            else:
                result.volume_score = 20

            if vol >= 5_000_000:
                result.volume_score = min(100, result.volume_score + 10)

        # 5. Structure score (from ICT + liquidity)
        structure_bull = 50
        if ict_features:
            if getattr(ict_features, 'structure_break_confirmed', False):
                structure_bull += 20
            if getattr(ict_features, 'near_order_block', False):
                structure_bull += 15
            if getattr(ict_features, 'trap_detected', False):
                structure_bull -= 25
            if getattr(ict_features, 'is_overextended', False):
                structure_bull -= 15
            if getattr(ict_features, 'structure_reclaimed', False):
                structure_bull += 15
        if liquidity:
            if liquidity.sweep_detected and liquidity.sweep_reclaimed:
                structure_bull += 15
            if liquidity.fake_breakout_detected:
                structure_bull -= 20
            if liquidity.inducement_detected:
                structure_bull -= 10
        result.structure_score = max(0, min(100, structure_bull))

        # 6. Trend score (from dip/bounce detectors)
        trend_bull = 50
        if dip_result and getattr(dip_result, 'is_valid_dip', False):
            trend_bull += 15
        if bounce_result:
            prob = getattr(bounce_result, 'probability', 0)
            if prob >= 65:
                trend_bull += 25
            elif prob >= 50:
                trend_bull += 15
            if getattr(bounce_result, 'entry_ready', False):
                trend_bull += 10
        if bearish_data:
            bp = getattr(bearish_data, 'bearish_probability', 0)
            if bp > 60:
                trend_bull -= 30
            elif bp > 40:
                trend_bull -= 15
        result.trend_score = max(0, min(100, trend_bull))

        # 7. Liquidity signal score
        if liquidity:
            liq_bull = 50
            if liquidity.sweep_detected and liquidity.sweep_direction == "down" and liquidity.sweep_reclaimed:
                liq_bull += 25  # Bullish sweep reclaim
            elif liquidity.sweep_detected and liquidity.sweep_direction == "up":
                liq_bull -= 20  # Bearish rejection
            if liquidity.breakout_type.value == "TRUE_BREAKOUT":
                liq_bull += 20
            elif liquidity.breakout_type.value == "FAKE_BREAKOUT":
                liq_bull -= 25
            result.liquidity_score = max(0, min(100, liq_bull))

        # 8. Market context score
        if market_context:
            ctx_map = {
                "BULL_MARKET": 80, "SIDEWAYS": 50, "BEAR_MARKET": 20,
            }
            cond = market_context.condition.value if hasattr(market_context.condition, 'value') else str(market_context.condition)
            result.market_context_score = ctx_map.get(cond, 50)

        # 9. MTF alignment score
        if mtf_result:
            result.mtf_alignment_score = mtf_result.alignment_score
            bias = mtf_result.overall_bias.value if hasattr(mtf_result.overall_bias, 'value') else str(mtf_result.overall_bias)
            if "BEARISH" in bias:
                result.mtf_alignment_score = 100 - result.mtf_alignment_score

        # ── Weighted combination ──────────────────────────────────────────
        components = {
            "catalyst": result.catalyst_score,
            "freshness": result.freshness_score,
            "reaction": result.reaction_score,
            "volume": result.volume_score,
            "structure": result.structure_score,
            "trend": result.trend_score,
            "liquidity": result.liquidity_score,
            "market_context": result.market_context_score,
            "mtf_alignment": result.mtf_alignment_score,
        }

        weighted_sum = sum(components[k] * WEIGHTS[k] for k in WEIGHTS)
        result.bullish_probability = round(max(0, min(100, weighted_sum)), 1)
        result.bearish_probability = round(100 - result.bullish_probability, 1)

        # Determine dominant factor
        max_contribution = 0
        for k, w in WEIGHTS.items():
            contribution = components[k] * w
            if contribution > max_contribution:
                max_contribution = contribution
                result.dominant_factor = k

        # Confidence = how much agreement between components
        scores = list(components.values())
        if scores:
            import numpy as np
            std = float(np.std(scores))
            result.confidence = round(max(20, min(95, 80 - std * 0.5)), 1)

        logger.info(
            "Probability [%s]: bull=%.1f%% bear=%.1f%% conf=%.1f%% dominant=%s",
            ticker, result.bullish_probability, result.bearish_probability,
            result.confidence, result.dominant_factor,
        )

        return result
