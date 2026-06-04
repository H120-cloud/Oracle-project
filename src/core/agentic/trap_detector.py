"""
Agentic Trap Detection Engine — Part 6

Detects:
- Parabolic exhaustion
- Bull traps / fake breakouts
- VWAP reclaim failures
- Heavy upper wicks (selling pressure)
- Rug pulls / dilution
"""

import logging

from src.models.market_data import OHLCVBar
from src.core.agentic.models import TrapResult, AgenticCandidate
from src.core.agentic.calibration_provider import get_calibration_weights

logger = logging.getLogger(__name__)

MAX_MULTIPLIER = 1.15
MIN_MULTIPLIER = 0.85


def _clamp_multiplier(m: float) -> float:
    return max(MIN_MULTIPLIER, min(MAX_MULTIPLIER, m))


class TrapDetector:
    """Compute trap risk score and classify trap types."""

    def __init__(self):
        self.cw = get_calibration_weights()
        if self.cw:
            logger.info("TrapDetector loaded calibration v%s", self.cw.version)

    def analyze(self, candidate: AgenticCandidate, bars: list[OHLCVBar]) -> AgenticCandidate:
        if not bars or len(bars) < 5:
            candidate.trap = TrapResult(trap_risk_score=50, reasons=["Insufficient data"])
            return candidate

        score = 0.0
        trap_types: list[str] = []
        reasons: list[str] = []

        prices = [b.close for b in bars]
        highs = [b.high for b in bars]
        lows = [b.low for b in bars]
        volumes = [b.volume for b in bars]

        current = prices[-1]
        hod = max(highs)
        drop_pct = ((hod - current) / hod * 100) if hod > 0 else 0

        # ── 1. Parabolic exhaustion ──────────────────────────────────────
        # Multiple >3% candles in a row → parabolic
        big_candles = 0
        for i in range(-min(len(bars), 10), 0):
            bar_range_pct = (highs[i] - lows[i]) / lows[i] * 100 if lows[i] > 0 else 0
            if bar_range_pct > 3:
                big_candles += 1
        if big_candles >= 4:
            score += 25
            trap_types.append("parabolic_exhaustion")
            reasons.append(f"{big_candles} large-range candles — parabolic move")

        # ── 2. Upper wick pressure ───────────────────────────────────────
        # Heavy upper wicks in last 5 bars = selling at highs
        wick_pressure = 0
        for i in range(-min(len(bars), 5), 0):
            body = abs(bars[i].close - bars[i].open)
            upper_wick = bars[i].high - max(bars[i].close, bars[i].open)
            if body > 0 and upper_wick > body * 1.5:
                wick_pressure += 1
        if wick_pressure >= 3:
            score += 20
            trap_types.append("heavy_upper_wicks")
            reasons.append(f"{wick_pressure}/5 bars with heavy upper wicks")
        elif wick_pressure >= 2:
            score += 10
            reasons.append(f"{wick_pressure}/5 bars show selling at highs")

        # ── 3. VWAP reclaim failure ──────────────────────────────────────
        if candidate.momentum.vwap and current < candidate.momentum.vwap:
            # Was above VWAP earlier, now below → failed reclaim
            was_above = any(p > candidate.momentum.vwap for p in prices[:-5])
            if was_above:
                score += 15
                trap_types.append("vwap_reclaim_failure")
                reasons.append("Lost VWAP after reclaim attempt")

        # ── 4. Bull trap / fake breakout ─────────────────────────────────
        # Made new high then immediately reversed
        if len(bars) >= 10:
            last_10_high = max(highs[-10:])
            prior_high = max(highs[:-10]) if len(highs) > 10 else hod * 0.95
            if last_10_high > prior_high and current < prior_high:
                score += 20
                trap_types.append("bull_trap")
                reasons.append("Broke above resistance then reversed below it")

        # ── 5. Volume distribution ───────────────────────────────────────
        # Falling volume + falling price = distribution
        if len(bars) >= 10:
            recent_avg_vol = sum(volumes[-5:]) / 5
            prior_avg_vol = sum(volumes[-10:-5]) / 5 if len(volumes) >= 10 else recent_avg_vol
            recent_avg_price = sum(prices[-5:]) / 5
            prior_avg_price = sum(prices[-10:-5]) / 5 if len(prices) >= 10 else recent_avg_price

            if recent_avg_vol > prior_avg_vol * 1.5 and recent_avg_price < prior_avg_price:
                score += 15
                trap_types.append("distribution")
                reasons.append("Rising volume on falling prices — distribution")

        # ── 6. Dilution risk from catalyst ───────────────────────────────
        if candidate.float_intel.dilution_risk:
            score += 15
            trap_types.append("dilution_risk")
            reasons.append(f"Dilution risk: {candidate.float_intel.dilution_risk_reason}")

        # ── 7. Extreme extension ─────────────────────────────────────────
        if drop_pct < 5 and hod > 0:
            total_move = ((hod - min(lows)) / min(lows) * 100) if min(lows) > 0 else 0
            if total_move > 100:
                score += 15
                trap_types.append("extreme_extension")
                reasons.append(f"Extended {total_move:.0f}% from low — reversal risk high")
            elif total_move > 50:
                score += 8
                reasons.append(f"Extended {total_move:.0f}% — caution")

        # Apply calibration multiplier to trap risk score (max 15% drift)
        calibrated = False
        if self.cw and self.cw.trap_risk_w != 1.0:
            mult = _clamp_multiplier(self.cw.trap_risk_w)
            score = round(min(100, score * mult), 1)
            calibrated = True
            logger.info("TrapDetector applied trap_risk_w=%s -> score=%s", mult, score)

        score = min(100, max(0, score))
        is_trap = score >= 65

        candidate.trap = TrapResult(
            trap_risk_score=round(score, 1),
            is_trap=is_trap,
            trap_types=trap_types,
            reasons=reasons,
            calibrated=calibrated,
        )

        return candidate
