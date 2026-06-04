"""
Agentic Failure Velocity Engine — Part 8

Measures how fast and strong a selloff is to distinguish:
- Slow pullback = healthy retracement
- Fast drop = institutional distribution
"""

import logging

from src.models.market_data import OHLCVBar
from src.core.agentic.models import FailureVelocityResult, AgenticCandidate

logger = logging.getLogger(__name__)


class FailureVelocityEngine:
    """Analyze selloff character to detect distribution vs healthy pullback."""

    def analyze(self, candidate: AgenticCandidate, bars: list[OHLCVBar]) -> AgenticCandidate:
        if not bars or len(bars) < 5:
            candidate.failure_velocity = FailureVelocityResult(reason="Insufficient data")
            return candidate

        # Focus on the pullback portion: from high of day to current
        highs = [b.high for b in bars]
        hod_idx = highs.index(max(highs))

        # Bars after high of day
        pullback_bars = bars[hod_idx:]
        if len(pullback_bars) < 3:
            candidate.failure_velocity = FailureVelocityResult(
                velocity_score=10, reason="No meaningful pullback yet"
            )
            return candidate

        # ── Red candle strength ──────────────────────────────────────────
        red_candle_pcts = []
        sell_volume = 0.0
        buy_volume = 0.0
        for b in pullback_bars:
            if b.close < b.open:
                drop_pct = (b.open - b.close) / b.open * 100 if b.open > 0 else 0
                red_candle_pcts.append(drop_pct)
                sell_volume += b.volume
            else:
                buy_volume += b.volume

        avg_red = sum(red_candle_pcts) / len(red_candle_pcts) if red_candle_pcts else 0
        sell_ratio = sell_volume / buy_volume if buy_volume > 0 else 5.0

        # ── Speed of drop ────────────────────────────────────────────────
        # How fast did it go from HOD to low?
        hod_price = max(highs)
        post_hod_low = min(b.low for b in pullback_bars)
        total_drop_pct = (hod_price - post_hod_low) / hod_price * 100 if hod_price > 0 else 0
        bars_to_low = len(pullback_bars)
        drop_speed = total_drop_pct / bars_to_low if bars_to_low > 0 else 0

        # ── Compute velocity score ───────────────────────────────────────
        score = 0.0

        # Speed contribution (fast drop = bad)
        if drop_speed > 2.0:
            score += 40
        elif drop_speed > 1.0:
            score += 25
        elif drop_speed > 0.5:
            score += 12

        # Sell volume ratio contribution
        if sell_ratio > 3.0:
            score += 30
        elif sell_ratio > 2.0:
            score += 20
        elif sell_ratio > 1.5:
            score += 10

        # Red candle avg size
        if avg_red > 1.5:
            score += 20
        elif avg_red > 0.8:
            score += 10

        score = min(100, max(0, score))
        is_dist = score >= 55

        reason = (
            f"Drop {total_drop_pct:.1f}% in {bars_to_low} bars "
            f"(speed={drop_speed:.2f}%/bar, sell_ratio={sell_ratio:.1f}x)"
        )
        if is_dist:
            reason = f"DISTRIBUTION: {reason}"
        else:
            reason = f"Healthy pullback: {reason}"

        candidate.failure_velocity = FailureVelocityResult(
            velocity_score=round(score, 1),
            is_distribution=is_dist,
            red_candle_strength=round(avg_red, 2),
            sell_volume_ratio=round(sell_ratio, 2),
            reason=reason,
        )

        return candidate
