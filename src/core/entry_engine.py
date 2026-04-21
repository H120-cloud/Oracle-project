"""
Entry Engine — Parts 12, 13, 14, 15

Part 12: Reversal Detection (Sell Signals)
  - Lower highs, support breaks, distribution, heavy selling
  - reversal_stage: EARLY / CONFIRMED / STRONG

Part 13: Entry Timing Engine
  - Valid entries: structure break + volume + pullback to support/OB + liquidity confirm
  - Classify: EARLY / CONFIRMED / CHASE

Part 14: Risk/Reward Filter
  - Minimum 2:1 R:R required, ideal 3:1+
  - Reject poor structure, late entries, low upside

Part 15: "Too Late" Detector
  - Classify: EARLY / IDEAL / EXTENDED / TOO_LATE
  - Based on % move, VWAP distance, extension from structure
"""

import logging
from dataclasses import dataclass
from typing import Optional
from enum import Enum

import numpy as np

logger = logging.getLogger(__name__)


# ── Enums ─────────────────────────────────────────────────────────────────────

class ReversalStage(str, Enum):
    NONE = "NONE"
    EARLY = "EARLY"
    CONFIRMED = "CONFIRMED"
    STRONG = "STRONG"


class EntryQuality(str, Enum):
    EARLY = "EARLY"
    CONFIRMED = "CONFIRMED"
    CHASE = "CHASE"


class TimingLabel(str, Enum):
    EARLY = "EARLY"
    IDEAL = "IDEAL"
    EXTENDED = "EXTENDED"
    TOO_LATE = "TOO_LATE"


class TradeDecision(str, Enum):
    ENTER = "ENTER"
    WAIT = "WAIT"
    AVOID = "AVOID"


# ── Data Classes ──────────────────────────────────────────────────────────────

@dataclass
class ReversalSignal:
    """Part 12: Reversal detection output."""
    detected: bool = False
    reversal_stage: ReversalStage = ReversalStage.NONE
    bearish_alert: bool = False
    lower_highs: bool = False
    support_broken: bool = False
    distribution_detected: bool = False
    heavy_selling: bool = False
    reasons: list = None

    def __post_init__(self):
        if self.reasons is None:
            self.reasons = []


@dataclass
class EntrySignal:
    """Part 13: Entry timing output."""
    entry_quality: EntryQuality = EntryQuality.CHASE
    structure_break: bool = False
    volume_confirmed: bool = False
    pullback_to_support: bool = False
    liquidity_confirmed: bool = False
    reasons: list = None

    def __post_init__(self):
        if self.reasons is None:
            self.reasons = []


@dataclass
class TimingResult:
    """Part 15: Too-late detector output."""
    timing_label: TimingLabel = TimingLabel.TOO_LATE
    pct_from_origin: float = 0.0
    distance_from_vwap_pct: float = 0.0
    extension_from_structure_pct: float = 0.0


@dataclass
class EntryAnalysis:
    """Complete entry analysis combining all sub-engines."""
    ticker: str

    # Part 12: Reversal
    reversal: ReversalSignal = None

    # Part 13: Entry quality
    entry: EntrySignal = None

    # Part 14: Risk/Reward
    reward_risk_ratio: float = 0.0
    rr_acceptable: bool = False      # >= 2:1
    rr_ideal: bool = False           # >= 3:1

    # Part 15: Timing
    timing: TimingResult = None

    # Final decision
    trade_decision: TradeDecision = TradeDecision.AVOID
    decision_reasons: list = None

    def __post_init__(self):
        if self.reversal is None:
            self.reversal = ReversalSignal()
        if self.entry is None:
            self.entry = EntrySignal()
        if self.timing is None:
            self.timing = TimingResult()
        if self.decision_reasons is None:
            self.decision_reasons = []

    def to_dict(self) -> dict:
        return {
            "ticker": self.ticker,
            "trade_decision": self.trade_decision.value,
            "entry_quality": self.entry.entry_quality.value,
            "timing_label": self.timing.timing_label.value,
            "reversal_stage": self.reversal.reversal_stage.value,
            "reward_risk_ratio": self.reward_risk_ratio,
            "rr_acceptable": self.rr_acceptable,
            "decision_reasons": self.decision_reasons,
        }


class EntryEngine:
    """Combined entry analysis engine."""

    def analyze(
        self,
        ticker: str,
        bars: list,
        target=None,           # PriceTarget
        ict_features=None,     # ICTFeatures
        liquidity=None,        # LiquidityAnalysis
        probability=None,      # ProbabilityResult
        vol_profile=None,      # VolumeProfileData
    ) -> EntryAnalysis:
        """Run full entry analysis."""
        if not bars or len(bars) < 20:
            return EntryAnalysis(ticker=ticker)

        h = np.array([float(b.high) for b in bars])
        l = np.array([float(b.low) for b in bars])
        c = np.array([float(b.close) for b in bars])
        o = np.array([float(b.open) for b in bars])
        v = np.array([float(b.volume) for b in bars])

        price = float(c[-1])
        result = EntryAnalysis(ticker=ticker)

        # Part 12: Reversal detection
        result.reversal = self._detect_reversal(h, l, c, o, v)

        # Part 13: Entry quality
        result.entry = self._evaluate_entry(h, l, c, o, v, price, ict_features, liquidity)

        # Part 14: Risk/Reward
        if target:
            result.reward_risk_ratio = target.reward_risk_ratio
            result.rr_acceptable = target.reward_risk_ratio >= 2.0
            result.rr_ideal = target.reward_risk_ratio >= 3.0

        # Part 15: Timing
        result.timing = self._evaluate_timing(h, l, c, v, price, vol_profile)

        # Final decision
        result.trade_decision, result.decision_reasons = self._make_decision(result, probability)

        logger.info(
            "Entry [%s]: decision=%s quality=%s timing=%s reversal=%s R:R=%.1f",
            ticker, result.trade_decision.value, result.entry.entry_quality.value,
            result.timing.timing_label.value, result.reversal.reversal_stage.value,
            result.reward_risk_ratio,
        )

        return result

    # ── Part 12: Reversal Detection ───────────────────────────────────────

    def _detect_reversal(self, h, l, c, o, v) -> ReversalSignal:
        """Detect reversal signals."""
        signal = ReversalSignal()

        if len(c) < 20:
            return signal

        # Lower highs detection
        swing_highs = []
        lb = 3
        for i in range(lb, len(h) - lb):
            if h[i] == max(h[i-lb:i+lb+1]):
                swing_highs.append(float(h[i]))

        if len(swing_highs) >= 3:
            if swing_highs[-1] < swing_highs[-2] < swing_highs[-3]:
                signal.lower_highs = True
                signal.reasons.append("Three consecutive lower highs")

        # Support break
        recent_low = float(np.min(l[-10:]))
        prev_support = float(np.min(l[-20:-10])) if len(l) >= 20 else recent_low
        if c[-1] < prev_support:
            signal.support_broken = True
            signal.reasons.append(f"Price below support {prev_support:.2f}")

        # Distribution detection (high volume + price going nowhere)
        if len(v) >= 10:
            avg_vol = float(np.mean(v[-20:])) if len(v) >= 20 else float(np.mean(v))
            recent_vol = float(np.mean(v[-5:]))
            price_range = float(np.max(c[-10:]) - np.min(c[-10:]))
            avg_price = float(np.mean(c[-10:]))
            range_pct = price_range / avg_price * 100 if avg_price > 0 else 0

            if recent_vol > avg_vol * 1.5 and range_pct < 2:
                signal.distribution_detected = True
                signal.reasons.append("High volume distribution (tight range)")

        # Heavy selling (consecutive red candles with above-avg volume)
        red_count = 0
        for i in range(-5, 0):
            idx = len(c) + i
            if idx >= 0 and c[idx] < o[idx]:
                avg_v = float(np.mean(v)) if len(v) > 0 else 0
                if v[idx] > avg_v * 1.3:
                    red_count += 1
        if red_count >= 3:
            signal.heavy_selling = True
            signal.reasons.append(f"Heavy selling: {red_count} high-vol red bars")

        # Classify reversal stage
        bearish_signals = sum([signal.lower_highs, signal.support_broken,
                              signal.distribution_detected, signal.heavy_selling])

        if bearish_signals >= 3:
            signal.reversal_stage = ReversalStage.STRONG
            signal.detected = True
            signal.bearish_alert = True
        elif bearish_signals >= 2:
            signal.reversal_stage = ReversalStage.CONFIRMED
            signal.detected = True
            signal.bearish_alert = True
        elif bearish_signals >= 1:
            signal.reversal_stage = ReversalStage.EARLY
            signal.detected = True

        return signal

    # ── Part 13: Entry Quality ────────────────────────────────────────────

    def _evaluate_entry(self, h, l, c, o, v, price, ict_features, liquidity) -> EntrySignal:
        """Evaluate entry quality."""
        entry = EntrySignal()

        # Structure break
        if ict_features and getattr(ict_features, 'structure_break_confirmed', False):
            entry.structure_break = True
            entry.reasons.append("Structure break confirmed")
        elif len(h) >= 10:
            recent_high = float(np.max(h[-10:]))
            prev_high = float(np.max(h[-20:-10])) if len(h) >= 20 else recent_high
            if recent_high > prev_high:
                entry.structure_break = True
                entry.reasons.append("Recent high > previous high")

        # Volume confirmation
        if len(v) >= 10:
            avg_vol = float(np.mean(v[-20:])) if len(v) >= 20 else float(np.mean(v))
            recent_vol = float(np.mean(v[-3:]))
            if recent_vol > avg_vol * 1.5:
                entry.volume_confirmed = True
                entry.reasons.append("Volume confirmed (1.5x avg)")

        # Pullback to support / order block
        if ict_features:
            ob_price = getattr(ict_features, 'order_block_price', 0)
            dist = getattr(ict_features, 'distance_to_order_block_pct', 100)
            if dist < 3:
                entry.pullback_to_support = True
                entry.reasons.append(f"Near order block ({dist:.1f}%)")

        # Check if near recent support (within 1%)
        if len(l) >= 20:
            support = float(np.min(l[-20:]))
            dist_pct = (price - support) / price * 100 if price > 0 else 100
            if dist_pct < 2:
                entry.pullback_to_support = True
                entry.reasons.append(f"Near support ({dist_pct:.1f}%)")

        # Liquidity confirmation
        if liquidity:
            if liquidity.sweep_detected and liquidity.sweep_reclaimed:
                entry.liquidity_confirmed = True
                entry.reasons.append("Liquidity sweep + reclaim")
            if liquidity.breakout_type.value == "TRUE_BREAKOUT":
                entry.liquidity_confirmed = True
                entry.reasons.append("True breakout confirmed")

        # Classify quality
        confirms = sum([entry.structure_break, entry.volume_confirmed,
                       entry.pullback_to_support, entry.liquidity_confirmed])

        if confirms >= 3:
            entry.entry_quality = EntryQuality.CONFIRMED
        elif confirms >= 2:
            entry.entry_quality = EntryQuality.EARLY
        else:
            entry.entry_quality = EntryQuality.CHASE

        return entry

    # ── Part 15: Timing (Too Late Detector) ───────────────────────────────

    def _evaluate_timing(self, h, l, c, v, price, vol_profile) -> TimingResult:
        """Evaluate if entry is too late."""
        timing = TimingResult()

        # % move from day's origin (or recent swing low)
        if len(c) >= 20:
            origin = float(np.min(l[-20:]))
            move_from_origin = (price - origin) / origin * 100 if origin > 0 else 0
            timing.pct_from_origin = round(move_from_origin, 2)

        # Distance from VWAP
        if len(c) >= 10:
            typical = (h + l + c) / 3
            cum_vol = np.cumsum(v)
            cum_tp_vol = np.cumsum(typical * v)
            vwap = float(cum_tp_vol[-1] / cum_vol[-1]) if cum_vol[-1] > 0 else price
            vwap_dist = (price - vwap) / vwap * 100 if vwap > 0 else 0
            timing.distance_from_vwap_pct = round(vwap_dist, 2)

        # Extension from structure (EMA20)
        if len(c) >= 20:
            ema20 = self._ema(c, 20)
            ext = (price - ema20) / ema20 * 100 if ema20 > 0 else 0
            timing.extension_from_structure_pct = round(ext, 2)

        # Classify timing
        move = abs(timing.pct_from_origin)
        vwap_ext = abs(timing.distance_from_vwap_pct)
        struct_ext = abs(timing.extension_from_structure_pct)

        if move < 3 and vwap_ext < 1 and struct_ext < 1:
            timing.timing_label = TimingLabel.EARLY
        elif move < 6 and vwap_ext < 2 and struct_ext < 2:
            timing.timing_label = TimingLabel.IDEAL
        elif move < 12 and vwap_ext < 4:
            timing.timing_label = TimingLabel.EXTENDED
        else:
            timing.timing_label = TimingLabel.TOO_LATE

        return timing

    # ── Final Decision ────────────────────────────────────────────────────

    def _make_decision(self, result: EntryAnalysis, probability) -> tuple:
        """Make final trade decision."""
        reasons = []

        # Hard rejects
        if result.reversal.reversal_stage == ReversalStage.STRONG:
            reasons.append("BLOCKED: Strong reversal detected")
            return TradeDecision.AVOID, reasons

        if result.timing.timing_label == TimingLabel.TOO_LATE:
            reasons.append("BLOCKED: Entry too late")
            return TradeDecision.AVOID, reasons

        if result.reward_risk_ratio > 0 and result.reward_risk_ratio < 1.5:
            reasons.append(f"BLOCKED: Poor R:R ({result.reward_risk_ratio:.1f}:1)")
            return TradeDecision.AVOID, reasons

        if result.entry.entry_quality == EntryQuality.CHASE:
            reasons.append("WARNING: Chase entry — no confirmations")

        # Soft warnings
        if result.reversal.reversal_stage == ReversalStage.CONFIRMED:
            reasons.append("WARNING: Confirmed reversal — reduce size")
            return TradeDecision.WAIT, reasons

        if result.timing.timing_label == TimingLabel.EXTENDED:
            reasons.append("WARNING: Extended move — wait for pullback")
            return TradeDecision.WAIT, reasons

        # Positive signals
        if (result.entry.entry_quality == EntryQuality.CONFIRMED and
            result.timing.timing_label in (TimingLabel.EARLY, TimingLabel.IDEAL) and
            result.rr_acceptable):
            reasons.append("CONFIRMED: Quality entry with good R:R")
            if result.rr_ideal:
                reasons.append("BONUS: Ideal 3:1+ R:R")
            return TradeDecision.ENTER, reasons

        if result.entry.entry_quality == EntryQuality.EARLY and result.rr_acceptable:
            reasons.append("EARLY: Developing setup — monitor for confirmation")
            return TradeDecision.WAIT, reasons

        reasons.append("INSUFFICIENT: Not enough confirmations")
        return TradeDecision.AVOID, reasons

    @staticmethod
    def _ema(data, period):
        if len(data) < period:
            return float(data[-1]) if len(data) > 0 else 0.0
        multiplier = 2 / (period + 1)
        ema = float(data[0])
        for val in data[1:]:
            ema = (float(val) - ema) * multiplier + ema
        return ema
