"""
V18 ABCD Pattern Confirmation Layer

Detects micro-cap / low-float ABCD-style setups:
  A = tight base / quiet accumulation
  B = breakout on volume
  C = retest confirmation
  D = continuation potential

Used as a confirmation filter within the Agentic pipeline:
  Pre-News V2 → Agentic Candidate → ABCD Confirmation → Risk Rules → Entry Timing → Alert

ABCD is NOT an alert signal by itself. It confirms whether a candidate
has structural pattern quality before Entry Timing and Risk Rules run.
"""

from __future__ import annotations

import logging
from typing import Optional, List, Tuple

from src.models.market_data import OHLCVBar
from src.core.agentic.models import (
    AgenticCandidate,
    ABCDResult,
    ABCDState,
    ABCDPhase,
    MomentumState,
)

logger = logging.getLogger(__name__)

# ── Thresholds ─────────────────────────────────────────────────────────────

# Phase A — Tight Base
MIN_BASE_BARS = 5          # minimum bars to consider a base
MAX_RANGE_PCT = 3.0        # max price range % for base to be "tight"
MAX_UPPER_WICK_PCT = 15.0  # max upper wick % of body
MIN_HIGHER_LOWS = 2        # at least 2 higher lows
MAX_VOLUME_STD_PCT = 50.0  # volume should be quiet/controlled (<50% std dev)

# Phase B — Breakout
BREAKOUT_MIN_PCT = 2.0     # price must close > base high by at least 2%
VOLUME_EXPANSION_MIN = 150.0  # volume at breakout vs base avg (150%)
MIN_RVOL = 1.5             # minimum relative volume at breakout
MAX_SPREAD_PCT = 3.0       # spread must be acceptable
MAX_EXTENSION_PCT = 8.0    # not excessively extended from base

# Phase C — Retest
RETEST_MAX_PULLBACK_PCT = 3.0   # pullback from breakout high
RETEST_VWAP_TOLERANCE = 2.0    # VWAP distance tolerance
MIN_RETEST_BARS = 3            # min bars in retest zone
DECLINING_VOLUME_THRESHOLD = -10.0  # selling pressure declining %

# Phase D — Continuation
CONTINUATION_MIN_MOVE_PCT = 1.0  # price reclaims breakout level
CONTINUATION_VOLUME_RETURN = 120.0  # volume returns to at least 120%

# Scoring
BASE_TIGHTNESS_WEIGHT = 25
BREAKOUT_QUALITY_WEIGHT = 25
RETEST_QUALITY_WEIGHT = 25
CONTINUATION_QUALITY_WEIGHT = 25


class ABCDDetector:
    """Detect and classify ABCD pattern states from intraday OHLCV bars."""

    def analyze(self, candidate: AgenticCandidate, bars: list[OHLCVBar]) -> ABCDResult:
        """Run full ABCD analysis on a candidate's intraday bars."""
        if not bars or len(bars) < 10:
            return ABCDResult(
                abcd_state=ABCDState.NO_PATTERN,
                abcd_reasons=["Insufficient bar data for ABCD analysis"],
            )

        result = ABCDResult()
        result.abcd_reasons = []
        result.abcd_warnings = []

        # Compute derived series
        closes = [b.close for b in bars]
        highs = [b.high for b in bars]
        lows = [b.low for b in bars]
        volumes = [b.volume for b in bars]
        opens = [b.open for b in bars]

        # VWAP approximation
        vwap = self._compute_vwap(bars)

        # ── Phase A: Tight Base Detection ───────────────────────────────
        base_ok, base_high, base_low, base_bars, base_reasons, base_warnings = self._detect_base(
            bars, closes, highs, lows, volumes
        )
        result.abcd_reasons.extend(base_reasons)
        result.abcd_warnings.extend(base_warnings)

        if not base_ok:
            result.abcd_state = ABCDState.NO_PATTERN
            result.abcd_phase = ABCDPhase.A
            result.base_formed = False
            result.abcd_score = 0
            return result

        result.base_formed = True
        result.abcd_key_level = round(base_high, 4)
        result.abcd_invalidation_level = round(base_low * 0.98, 4)  # 2% below base low

        # Score base tightness
        base_range_pct = ((base_high - base_low) / base_low * 100) if base_low > 0 else 0
        result.base_tightness_score = self._score_base_tightness(base_range_pct, len(base_bars))

        # ── Phase B: Breakout Detection ──────────────────────────────────
        breakout_ok, breakout_bars, breakout_volume_exp, breakout_reasons, breakout_warnings = self._detect_breakout(
            bars, base_high, base_low, volumes, vwap
        )
        result.abcd_reasons.extend(breakout_reasons)
        result.abcd_warnings.extend(breakout_warnings)

        if not breakout_ok:
            result.abcd_state = ABCDState.BASE_FORMING
            result.abcd_phase = ABCDPhase.A
            result.abcd_score = max(0, result.base_tightness_score - 10)
            result.abcd_entry_valid = False
            return result

        result.breakout_confirmed = True
        result.breakout_volume_expansion = round(breakout_volume_exp, 1)
        breakout_bar = breakout_bars[-1] if breakout_bars else bars[-1]
        breakout_high = max(b.high for b in breakout_bars) if breakout_bars else base_high

        # ── Phase C: Retest Detection ────────────────────────────────────
        retest_ok, retest_bars, retest_reasons, retest_warnings = self._detect_retest(
            bars, breakout_bars, base_high, vwap, volumes
        )
        result.abcd_reasons.extend(retest_reasons)
        result.abcd_warnings.extend(retest_warnings)

        if not retest_ok:
            result.abcd_state = ABCDState.BREAKOUT_CONFIRMED
            result.abcd_phase = ABCDPhase.B
            result.abcd_score = max(0, result.base_tightness_score + 15)
            result.abcd_entry_valid = False
            return result

        result.retest_confirmed = True
        retest_low = min(b.low for b in retest_bars) if retest_bars else base_high
        result.abcd_retest_level = round(retest_low, 4)

        # ── Phase D: Continuation Detection ────────────────────────────
        cont_ok, cont_bars, cont_reasons, cont_warnings = self._detect_continuation(
            bars, retest_bars, base_high, volumes
        )
        result.abcd_reasons.extend(cont_reasons)
        result.abcd_warnings.extend(cont_warnings)

        if cont_ok:
            result.continuation_ready = True
            result.abcd_state = ABCDState.CONTINUATION_READY
            result.abcd_phase = ABCDPhase.D
            result.abcd_entry_valid = True
            result.abcd_score = self._compute_total_score(result)
            result.abcd_reasons.append(
                "ABCD pattern complete: base formed, breakout confirmed, retest held, continuation ready"
            )
        else:
            # Retest confirmed but continuation not yet ready
            result.abcd_state = ABCDState.RETEST_CONFIRMED
            result.abcd_phase = ABCDPhase.C
            result.abcd_entry_valid = True  # Entry timing may still flag IDEAL_ENTRY
            result.abcd_score = self._compute_total_score(result)
            result.abcd_reasons.append(
                "ABCD retest confirmed. Waiting for continuation (D) signal."
            )

        return result

    # ═══════════════════════════════════════════════════════════════════════
    #  Phase A: Tight Base
    # ═══════════════════════════════════════════════════════════════════════

    def _detect_base(
        self,
        bars: list[OHLCVBar],
        closes: list[float],
        highs: list[float],
        lows: list[float],
        volumes: list[float],
    ) -> tuple:
        """
        Detect whether a tight base has formed.

        Returns: (base_ok, base_high, base_low, base_bars, reasons, warnings)
        """
        reasons: list[str] = []
        warnings: list[str] = []

        # Require at least MIN_BASE_BARS of relatively quiet price action
        if len(bars) < MIN_BASE_BARS + 3:
            return False, 0.0, 0.0, [], reasons, warnings

        # Sliding window: look for the earliest tight range (base forms first)
        # Search forward from start for consecutive quiet bars
        # Stop when either: (a) a single bar exceeds MAX_RANGE_PCT, or
        #                   (b) the accumulated base range exceeds MAX_RANGE_PCT
        base_end = 0
        for i, bar in enumerate(bars):
            bar_range_pct = self._bar_range_pct(bar)
            if bar_range_pct > MAX_RANGE_PCT:
                warnings.append(f"Bar {i} range {bar_range_pct:.1f}% exceeds {MAX_RANGE_PCT}% threshold")
                if i >= MIN_BASE_BARS:
                    base_end = i - 1
                    break
                else:
                    return False, 0.0, 0.0, [], reasons, warnings

            # Check accumulated range so far
            candidate_bars = bars[:i + 1]
            cand_high = max(b.high for b in candidate_bars)
            cand_low = min(b.low for b in candidate_bars)
            accum_range = ((cand_high - cand_low) / cand_low * 100) if cand_low > 0 else 0
            if accum_range > MAX_RANGE_PCT and i >= MIN_BASE_BARS:
                base_end = i - 1
                break

            base_end = i

        if base_end < MIN_BASE_BARS - 1:
            return False, 0.0, 0.0, [], reasons, warnings

        base_bars = bars[:base_end + 1]
        base_high = max(b.high for b in base_bars)
        base_low = min(b.low for b in base_bars)

        # Check tightness
        range_pct = ((base_high - base_low) / base_low * 100) if base_low > 0 else 0
        if range_pct > MAX_RANGE_PCT:
            warnings.append(f"Base range {range_pct:.1f}% exceeds {MAX_RANGE_PCT}% threshold")
            return False, base_high, base_low, base_bars, reasons, warnings

        # Check for higher lows
        swing_lows = []
        for i in range(1, len(base_bars) - 1):
            if base_bars[i].low < base_bars[i - 1].low and base_bars[i].low < base_bars[i + 1].low:
                swing_lows.append(base_bars[i].low)

        higher_lows = len(swing_lows) >= MIN_HIGHER_LOWS and swing_lows[-1] > swing_lows[-2] if len(swing_lows) >= 2 else False

        # Check upper wicks
        avg_upper_wick = sum(self._upper_wick_pct(b) for b in base_bars) / len(base_bars)
        if avg_upper_wick > MAX_UPPER_WICK_PCT:
            warnings.append(f"Upper wick avg {avg_upper_wick:.1f}% > {MAX_UPPER_WICK_PCT}%")

        # Check volume is quiet/controlled
        base_volumes = [b.volume for b in base_bars]
        vol_mean = sum(base_volumes) / len(base_volumes)
        vol_std = (sum((v - vol_mean) ** 2 for v in base_volumes) / len(base_volumes)) ** 0.5
        vol_std_pct = (vol_std / vol_mean * 100) if vol_mean > 0 else 0

        quiet_volume = vol_std_pct <= MAX_VOLUME_STD_PCT

        if quiet_volume:
            reasons.append(f"Quiet base: {len(base_bars)} bars, range {range_pct:.1f}%, volume controlled")
        else:
            warnings.append(f"Volume erratic: std {vol_std_pct:.1f}% > {MAX_VOLUME_STD_PCT}%")

        base_ok = quiet_volume and (avg_upper_wick <= MAX_UPPER_WICK_PCT) and (range_pct <= MAX_RANGE_PCT)
        return base_ok, base_high, base_low, base_bars, reasons, warnings

    # ═══════════════════════════════════════════════════════════════════════
    #  Phase B: Breakout
    # ═══════════════════════════════════════════════════════════════════════

    def _detect_breakout(
        self,
        bars: list[OHLCVBar],
        base_high: float,
        base_low: float,
        volumes: list[float],
        vwap: float,
    ) -> tuple:
        """
        Detect breakout above base high on volume expansion.

        Returns: (breakout_ok, breakout_bars, volume_expansion, reasons, warnings)
        """
        reasons: list[str] = []
        warnings: list[str] = []

        # Need at least one bar after base
        # Find first bar that closes decisively above base_high
        breakout_idx = None
        for i, bar in enumerate(bars):
            close_pct_above = ((bar.close - base_high) / base_high * 100) if base_high > 0 else 0
            if close_pct_above >= BREAKOUT_MIN_PCT:
                breakout_idx = i
                break

        if breakout_idx is None:
            return False, [], 0.0, reasons, warnings

        breakout_bar = bars[breakout_idx]
        breakout_bars = bars[breakout_idx:breakout_idx + 3]  # breakout + 2 follow-through bars

        # Check spread
        spread_pct = self._bar_range_pct(breakout_bar)
        if spread_pct > MAX_SPREAD_PCT:
            warnings.append(f"Breakout spread {spread_pct:.1f}% > {MAX_SPREAD_PCT}%")

        # Check extension from base
        extension_pct = ((breakout_bar.close - base_high) / base_high * 100) if base_high > 0 else 0
        if extension_pct > MAX_EXTENSION_PCT:
            warnings.append(f"Breakout extended {extension_pct:.1f}% > {MAX_EXTENSION_PCT}%")

        # Check volume expansion
        base_volumes = volumes[:breakout_idx]
        base_avg_vol = sum(base_volumes) / len(base_volumes) if base_volumes else breakout_bar.volume
        volume_exp = (breakout_bar.volume / base_avg_vol * 100) if base_avg_vol > 0 else 0

        if volume_exp >= VOLUME_EXPANSION_MIN:
            reasons.append(f"Breakout volume expansion {volume_exp:.0f}% (>{VOLUME_EXPANSION_MIN}%)")
        else:
            warnings.append(f"Volume expansion {volume_exp:.0f}% < {VOLUME_EXPANSION_MIN}%")

        breakout_ok = volume_exp >= VOLUME_EXPANSION_MIN and spread_pct <= MAX_SPREAD_PCT and extension_pct <= MAX_EXTENSION_PCT

        return breakout_ok, breakout_bars, volume_exp, reasons, warnings

    # ═══════════════════════════════════════════════════════════════════════
    #  Phase C: Retest
    # ═══════════════════════════════════════════════════════════════════════

    def _detect_retest(
        self,
        bars: list[OHLCVBar],
        breakout_bars: list[OHLCVBar],
        base_high: float,
        vwap: float,
        volumes: list[float],
    ) -> tuple:
        """
        Detect whether the breakout held a retest: pullback to prior resistance
        (now support) with VWAP hold and declining selling pressure.

        Returns: (retest_ok, retest_bars, reasons, warnings)
        """
        reasons: list[str] = []
        warnings: list[str] = []

        if not breakout_bars:
            return False, [], reasons, warnings

        breakout_idx = bars.index(breakout_bars[-1]) if breakout_bars[-1] in bars else -1
        if breakout_idx < 0 or breakout_idx >= len(bars) - 1:
            return False, [], reasons, warnings

        # Look at bars after breakout
        post_bars = bars[breakout_idx + 1:]
        if len(post_bars) < MIN_RETEST_BARS:
            return False, [], reasons, warnings

        # Find pullback bars that stay above base_high (support flip)
        retest_bars = []
        for bar in post_bars:
            if bar.low >= base_high * 0.97:  # allow 3% dip below base high
                retest_bars.append(bar)
            else:
                break

        if len(retest_bars) < MIN_RETEST_BARS:
            warnings.append(f"Pullback broke below base high support")
            return False, retest_bars, reasons, warnings

        # VWAP hold during retest
        vwap_lows = [b.low for b in retest_bars]
        vwap_held = all(low >= vwap * (1 - RETEST_VWAP_TOLERANCE / 100) for low in vwap_lows)

        if vwap_held:
            reasons.append("VWAP held during retest")
        else:
            warnings.append("Price dipped below VWAP during retest")

        # Higher low in retest
        retest_lows = [b.low for b in retest_bars]
        higher_low = retest_lows[-1] > retest_lows[0] if len(retest_lows) >= 2 else False
        if higher_low:
            reasons.append("Higher low formed during retest")

        # Selling pressure declining
        retest_volumes = [b.volume for b in retest_bars]
        if len(retest_volumes) >= 3:
            early_avg = sum(retest_volumes[:len(retest_volumes)//2]) / max(1, len(retest_volumes)//2)
            late_avg = sum(retest_volumes[len(retest_volumes)//2:]) / max(1, len(retest_volumes) - len(retest_volumes)//2)
            vol_decline = ((late_avg - early_avg) / early_avg * 100) if early_avg > 0 else 0
            selling_declining = vol_decline <= DECLINING_VOLUME_THRESHOLD
        else:
            selling_declining = False
            vol_decline = 0.0

        if selling_declining:
            reasons.append(f"Selling pressure declining ({vol_decline:.1f}%)")
        else:
            warnings.append(f"Selling pressure not declining ({vol_decline:.1f}%)")

        # Risk/reward still valid (retest zone not too far from base)
        retest_low = min(b.low for b in retest_bars)
        retest_high = max(b.high for b in retest_bars)
        risk = retest_high - retest_low
        reward = base_high - retest_low  # target is breakout level
        rr_valid = (reward / risk >= 1.5) if risk > 0 else False

        if rr_valid:
            reasons.append("Risk/reward still valid in retest zone")
        else:
            warnings.append("Risk/reward no longer valid in retest zone")

        retest_ok = vwap_held and (selling_declining or higher_low)
        return retest_ok, retest_bars, reasons, warnings

    # ═══════════════════════════════════════════════════════════════════════
    #  Phase D: Continuation
    # ═══════════════════════════════════════════════════════════════════════

    def _detect_continuation(
        self,
        bars: list[OHLCVBar],
        retest_bars: list[OHLCVBar],
        base_high: float,
        volumes: list[float],
    ) -> tuple:
        """
        Detect continuation: price reclaims breakout level, volume returns, no trap.

        Returns: (cont_ok, cont_bars, reasons, warnings)
        """
        reasons: list[str] = []
        warnings: list[str] = []

        if not retest_bars:
            return False, [], reasons, warnings

        retest_idx = bars.index(retest_bars[-1]) if retest_bars[-1] in bars else -1
        if retest_idx < 0 or retest_idx >= len(bars) - 1:
            return False, [], reasons, warnings

        cont_bars = bars[retest_idx + 1:]
        if not cont_bars:
            return False, [], reasons, warnings

        # Check price reclaims breakout level
        first_cont_bar = cont_bars[0]
        reclaim = first_cont_bar.close >= base_high * (1 + CONTINUATION_MIN_MOVE_PCT / 100)

        if reclaim:
            reasons.append(f"Price reclaimed breakout level +{CONTINUATION_MIN_MOVE_PCT}%")
        else:
            warnings.append(f"Price failed to reclaim breakout level")
            return False, cont_bars, reasons, warnings

        # Check volume returns
        cont_volume = first_cont_bar.volume
        retest_avg_vol = sum(b.volume for b in retest_bars) / len(retest_bars)
        vol_return = (cont_volume / retest_avg_vol * 100) if retest_avg_vol > 0 else 0

        if vol_return >= CONTINUATION_VOLUME_RETURN:
            reasons.append(f"Volume returned {vol_return:.0f}% (>{CONTINUATION_VOLUME_RETURN}%)")
        else:
            warnings.append(f"Volume return {vol_return:.0f}% < {CONTINUATION_VOLUME_RETURN}%")

        # Check no trap/rejection
        upper_wick = self._upper_wick_pct(first_cont_bar)
        if upper_wick > 20:
            warnings.append(f"Continuation bar has upper wick {upper_wick:.1f}%")

        # Check momentum expanding (close > open with increasing volume)
        momentum_expanding = first_cont_bar.close > first_cont_bar.open and vol_return >= CONTINUATION_VOLUME_RETURN
        if momentum_expanding:
            reasons.append("Momentum expanding on continuation")

        cont_ok = reclaim and vol_return >= CONTINUATION_VOLUME_RETURN and upper_wick <= 20
        return cont_ok, cont_bars, reasons, warnings

    # ═══════════════════════════════════════════════════════════════════════
    #  Scoring
    # ═══════════════════════════════════════════════════════════════════════

    def _score_base_tightness(self, range_pct: float, base_bars: int) -> int:
        """Score base tightness 0-100."""
        if range_pct <= 0.5 and base_bars >= 8:
            return 95
        if range_pct <= 1.0 and base_bars >= 6:
            return 85
        if range_pct <= 1.5 and base_bars >= 5:
            return 70
        if range_pct <= 2.0:
            return 55
        if range_pct <= MAX_RANGE_PCT:
            return 40
        return 20

    def _compute_total_score(self, result: ABCDResult) -> int:
        """Compute overall ABCD score from component scores."""
        base_score = result.base_tightness_score
        breakout_score = 0
        if result.breakout_confirmed:
            breakout_score = min(100, int(result.breakout_volume_expansion))
            if breakout_score > 100:
                breakout_score = 100
        retest_score = 0
        if result.retest_confirmed:
            retest_score = 75 if result.retest_vwap_hold else 50
            if result.retest_selling_pressure_declining:
                retest_score += 15
        cont_score = 0
        if result.continuation_ready:
            cont_score = 85
        elif result.retest_confirmed:
            cont_score = 40  # retest confirmed but not yet continuation

        total = (
            base_score * BASE_TIGHTNESS_WEIGHT +
            breakout_score * BREAKOUT_QUALITY_WEIGHT +
            retest_score * RETEST_QUALITY_WEIGHT +
            cont_score * CONTINUATION_QUALITY_WEIGHT
        ) // 100

        return max(0, min(100, total))

    # ═══════════════════════════════════════════════════════════════════════
    #  Helpers
    # ═══════════════════════════════════════════════════════════════════════

    @staticmethod
    def _compute_vwap(bars: list[OHLCVBar]) -> float:
        """Volume-weighted average price."""
        cum_pv = 0.0
        cum_vol = 0.0
        for b in bars:
            typical = (b.high + b.low + b.close) / 3
            cum_pv += typical * b.volume
            cum_vol += b.volume
        return cum_pv / cum_vol if cum_vol > 0 else bars[-1].close if bars else 0.0

    @staticmethod
    def _bar_range_pct(bar: OHLCVBar) -> float:
        """Bar range as % of close."""
        if bar.close == 0:
            return 0.0
        return (bar.high - bar.low) / bar.close * 100

    @staticmethod
    def _upper_wick_pct(bar: OHLCVBar) -> float:
        """Upper wick as % of body. Capped for tiny-body bars in tight bases."""
        body = abs(bar.close - bar.open)
        wick = bar.high - max(bar.close, bar.open)
        if body == 0:
            # Doji-like bar: assess wick relative to full range instead
            full_range = bar.high - bar.low
            if full_range == 0:
                return 0.0
            return (wick / full_range * 100) if full_range > 0 else 0.0
        wick_pct = wick / body * 100
        # Cap to avoid extreme values on micro-body bars
        return min(wick_pct, 100.0)
