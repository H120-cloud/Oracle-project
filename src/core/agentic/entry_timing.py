"""
V17 Entry Timing Engine

Classifies entries into 5 states:
  TOO_EARLY, WAITING_FOR_CONFIRMATION, IDEAL_ENTRY, LATE_CHASE, INVALID_ENTRY.
Computes entry zones, targets, stop levels, and risk/reward.
Only candidates with timing_state == IDEAL_ENTRY, R:R >= 2:1, and trap < 65 are actionable.
"""

import logging
from typing import Optional, List

from src.models.market_data import OHLCVBar
from src.core.agentic.models import (
    EntryTimingResult, EntryTimingState, EntryQuality, AgenticCandidate, MomentumState,
)

logger = logging.getLogger(__name__)


class EntryTimingEngine:
    """Classify entry timing quality for a candidate using 5-state V17 system."""

    # Thresholds
    MIN_RR = 2.0
    TRAP_THRESHOLD = 65
    SPREAD_PCT_MAX = 3.0

    def classify(self, candidate: AgenticCandidate, bars: list[OHLCVBar]) -> AgenticCandidate:
        if not bars or len(bars) < 5:
            candidate.entry_timing = EntryTimingResult(
                quality=EntryQuality.EARLY,
                timing_state=EntryTimingState.INVALID_ENTRY,
                entry_timing_score=0,
                reasons=["Insufficient data for timing"],
                next_entry_condition="Need at least 5 bars of data",
            )
            return candidate

        result = self._evaluate(candidate, bars)
        candidate.entry_timing = result
        return candidate

    def _evaluate(self, candidate: AgenticCandidate, bars: list[OHLCVBar]) -> EntryTimingResult:
        m = candidate.momentum
        state = m.state
        price = m.price or bars[-1].close
        vwap = m.vwap or price
        lows = [b.low for b in bars]
        highs = [b.high for b in bars]
        closes = [b.close for b in bars]
        volumes = [b.volume for b in bars]
        opens = [b.open for b in bars]

        score = 0
        reasons: list[str] = []
        warnings: list[str] = []
        entry_low: Optional[float] = None
        entry_high: Optional[float] = None
        invalidation: Optional[float] = None
        stop_level: Optional[float] = None
        target_1: Optional[float] = None
        target_2: Optional[float] = None
        stretch: Optional[float] = None
        rr = 0.0
        next_condition = ""
        timing_state = EntryTimingState.INVALID_ENTRY
        quality = EntryQuality.LATE

        # ── Compute derived bar metrics ─────────────────────────────────
        atr = self._atr(closes, highs, lows)
        spread_pct = self._spread_pct(bars[-1]) if bars else 0.0
        vol_accel = self._volume_acceleration(volumes)
        vol_persist = candidate.momentum.volume_persistence_pct
        upper_wick = self._upper_wick_pct(bars[-1]) if bars else 0.0
        recent_low = min(lows[-10:]) if len(lows) >= 10 else min(lows) if lows else price
        recent_high = max(highs[-5:]) if len(highs) >= 5 else max(highs) if highs else price
        consol_high = max(highs[-15:-3]) if len(highs) >= 15 else max(highs[:-3]) if len(highs) > 3 else price
        extension = ((price - consol_high) / consol_high * 100) if consol_high > 0 else 0

        # ── Base scoring ────────────────────────────────────────────────
        if m.vwap_reclaimed:
            score += 20
            reasons.append("✓ VWAP reclaimed")
        else:
            warnings.append("✗ Below VWAP")

        if m.higher_low_formed:
            score += 20
            reasons.append("✓ Higher low formed")
        else:
            warnings.append("✗ No higher low")

        if m.breakout_confirmed:
            score += 20
            reasons.append("✓ Breakout confirmed")
        else:
            warnings.append("✗ Breakout not confirmed")

        if m.consolidation_bars >= 4:
            score += 15
            reasons.append(f"✓ Consolidation ({m.consolidation_bars} bars)")
        else:
            warnings.append("Insufficient consolidation")

        if vol_persist >= 50:
            score += 10
            reasons.append(f"✓ Volume persist {vol_persist:.0f}%")
        else:
            warnings.append("Volume fading")

        if spread_pct <= self.SPREAD_PCT_MAX:
            score += 5
            reasons.append("✓ Spread acceptable")
        else:
            warnings.append(f"Wide spread {spread_pct:.1f}%")

        # Time-of-day bonus
        tod = candidate.time_of_day.session.value if candidate.time_of_day.session else ""
        if tod in ("open", "power_hour"):
            score += 5
            reasons.append("✓ Favourable session")

        # ── Penalties ───────────────────────────────────────────────────
        if extension > 3:
            penalty = min(30, int(extension * 3))
            score -= penalty
            warnings.append(f"Extended {extension:.1f}% above breakout (-{penalty})")

        if upper_wick > 5:
            score -= 10
            warnings.append(f"Upper wick {upper_wick:.1f}% (-10)")

        if vol_accel < -20:
            score -= 10
            warnings.append("Volume decelerating (-10)")

        if candidate.trap.trap_risk_score >= self.TRAP_THRESHOLD:
            score -= 20
            warnings.append(f"Trap risk {candidate.trap.trap_risk_score:.0f}% (-20)")

        if spread_pct > self.SPREAD_PCT_MAX:
            score -= 15
            warnings.append(f"Wide spread (-15)")

        # ── State classification ──────────────────────────────────────
        if state in (MomentumState.DEAD, MomentumState.FAILED):
            timing_state = EntryTimingState.INVALID_ENTRY
            quality = EntryQuality.LATE
            next_condition = "Setup invalidated"

        elif candidate.rejected or (candidate.hard_rejection and candidate.hard_rejection.triggered):
            timing_state = EntryTimingState.INVALID_ENTRY
            quality = EntryQuality.LATE
            next_condition = "Hard rejection active"

        elif candidate.trap.trap_risk_score >= 80:
            timing_state = EntryTimingState.INVALID_ENTRY
            quality = EntryQuality.LATE
            next_condition = "High trap risk"

        elif state in (MomentumState.INITIAL_SPIKE, MomentumState.SPIKE_PULLBACK):
            if score >= 30:
                timing_state = EntryTimingState.TOO_EARLY
                quality = EntryQuality.EARLY
                next_condition = "Wait for VWAP reclaim and higher low"
            else:
                timing_state = EntryTimingState.INVALID_ENTRY
                quality = EntryQuality.LATE
                next_condition = "No structure in initial spike"

        elif state in (MomentumState.CONSOLIDATION, MomentumState.SECOND_LEG_FORMING):
            if score >= 70 and m.vwap_reclaimed and m.higher_low_formed and m.breakout_confirmed:
                timing_state = EntryTimingState.IDEAL_ENTRY
                quality = EntryQuality.IDEAL
                next_condition = "Entry timing confirmed"
            elif score >= 40 and (m.vwap_reclaimed or m.higher_low_formed):
                timing_state = EntryTimingState.WAITING_FOR_CONFIRMATION
                quality = EntryQuality.EARLY
                missing = []
                if not m.vwap_reclaimed: missing.append("VWAP reclaim")
                if not m.higher_low_formed: missing.append("higher low")
                if not m.breakout_confirmed: missing.append("breakout")
                next_condition = f"Wait for {' + '.join(missing)}"
            else:
                timing_state = EntryTimingState.TOO_EARLY
                quality = EntryQuality.EARLY
                next_condition = "Structure forming — hold for confirmation"

        elif state == MomentumState.CONTINUATION_CONFIRMED:
            if extension < 3 and score >= 60:
                timing_state = EntryTimingState.IDEAL_ENTRY
                quality = EntryQuality.IDEAL
                next_condition = "Breakout retest zone"
            else:
                timing_state = EntryTimingState.LATE_CHASE
                quality = EntryQuality.LATE
                next_condition = "Already extended — wait for pullback"

        else:
            timing_state = EntryTimingState.INVALID_ENTRY
            quality = EntryQuality.LATE
            next_condition = f"State {state.value} — no entry"

        # ── Zone calculation ───────────────────────────────────────────
        if timing_state == EntryTimingState.IDEAL_ENTRY:
            entry_low = max(vwap, recent_low)
            entry_high = min(recent_high, consol_high * 1.02)
            invalidation = recent_low * 0.97
            stop_level = invalidation
            risk = entry_low - stop_level if entry_low and stop_level else atr
            if risk <= 0: risk = atr * 0.5
            target_1 = entry_low + risk * 2.0
            target_2 = entry_low + risk * 3.0
            stretch = recent_high * 1.05
            rr = round(risk * 2.0 / risk, 2) if risk > 0 else 0.0
        elif timing_state == EntryTimingState.WAITING_FOR_CONFIRMATION:
            entry_low = vwap
            entry_high = consol_high
            invalidation = recent_low * 0.97
            stop_level = invalidation
            risk = entry_low - stop_level if entry_low and stop_level else atr
            if risk <= 0: risk = atr * 0.5
            target_1 = entry_low + risk * 2.0
            target_2 = entry_low + risk * 3.0
            rr = round(risk * 2.0 / risk, 2) if risk > 0 else 0.0
        elif timing_state == EntryTimingState.TOO_EARLY:
            if m.post_spike_low:
                invalidation = m.post_spike_low * 0.97
                next_condition += f" | Support ${m.post_spike_low:.2f}"
        elif timing_state in (EntryTimingState.LATE_CHASE, EntryTimingState.INVALID_ENTRY):
            invalidation = recent_low * 0.97
            stop_level = invalidation

        # ── R:R filter ──────────────────────────────────────────────────
        if timing_state == EntryTimingState.IDEAL_ENTRY and rr < self.MIN_RR:
            timing_state = EntryTimingState.LATE_CHASE
            quality = EntryQuality.LATE
            warnings.append(f"R:R {rr:.1f} below minimum {self.MIN_RR}:1")
            next_condition = "Poor risk/reward — wait for better entry"

        # ── Clamp score ─────────────────────────────────────────────────
        score = max(0, min(100, score))

        return EntryTimingResult(
            quality=quality,
            timing_state=timing_state,
            entry_timing_score=score,
            entry_zone_low=round(entry_low, 4) if entry_low else None,
            entry_zone_high=round(entry_high, 4) if entry_high else None,
            ideal_entry_price=round((entry_low + entry_high) / 2, 4) if entry_low and entry_high else None,
            invalidation_level=round(invalidation, 4) if invalidation else None,
            stop_level=round(stop_level, 4) if stop_level else None,
            target_1=round(target_1, 4) if target_1 else None,
            target_2=round(target_2, 4) if target_2 else None,
            stretch_target=round(stretch, 4) if stretch else None,
            risk_reward_ratio=rr,
            next_entry_condition=next_condition,
            entry_warnings=warnings,
            reasons=reasons,
        )

    # ── Helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _atr(closes: list[float], highs: list[float], lows: list[float], period: int = 10) -> float:
        if len(closes) < 2:
            return 0.0
        trs = []
        for i in range(1, min(period, len(closes))):
            tr1 = highs[-i] - lows[-i]
            tr2 = abs(highs[-i] - closes[-i - 1]) if len(closes) > i else 0
            tr3 = abs(lows[-i] - closes[-i - 1]) if len(closes) > i else 0
            trs.append(max(tr1, tr2, tr3))
        return sum(trs) / len(trs) if trs else 0.0

    @staticmethod
    def _spread_pct(bar) -> float:
        if bar.close == 0:
            return 0.0
        return abs(bar.high - bar.low) / bar.close * 100

    @staticmethod
    def _volume_acceleration(volumes: list[float]) -> float:
        if len(volumes) < 3:
            return 0.0
        recent = sum(volumes[-3:]) / 3
        prior = sum(volumes[-6:-3]) / 3 if len(volumes) >= 6 else recent
        if prior == 0:
            return 0.0
        return (recent - prior) / prior * 100

    @staticmethod
    def _upper_wick_pct(bar) -> float:
        body = abs(bar.close - bar.open)
        wick = bar.high - max(bar.close, bar.open)
        if body == 0:
            return 0.0
        return wick / body * 100
