"""
Liquidity & Smart Money Engine — Part 5 + Part 11 (Fake Breakout Detection)

Detects:
- Liquidity sweeps (stop hunts)
- Equal highs/lows
- False breakdown → reclaim
- False breakout → rejection
- Inducement moves

Classifies each event:
- LIQUIDITY_GRAB
- TRUE_BREAKOUT
- MANIPULATION
"""

import logging
from dataclasses import dataclass, field
from typing import List, Optional
from enum import Enum

import numpy as np

logger = logging.getLogger(__name__)


class LiquidityEventType(str, Enum):
    LIQUIDITY_GRAB = "LIQUIDITY_GRAB"
    TRUE_BREAKOUT = "TRUE_BREAKOUT"
    MANIPULATION = "MANIPULATION"
    INDUCEMENT = "INDUCEMENT"
    EQUAL_LEVEL = "EQUAL_LEVEL"


class BreakoutType(str, Enum):
    TRUE_BREAKOUT = "TRUE_BREAKOUT"
    FAKE_BREAKOUT = "FAKE_BREAKOUT"
    FAILED_BREAKOUT = "FAILED_BREAKOUT"
    NO_BREAKOUT = "NO_BREAKOUT"


@dataclass
class LiquidityEvent:
    event_type: LiquidityEventType
    level: float
    direction: str = "none"      # "up" or "down"
    description: str = ""
    confidence: float = 0.0      # 0–100
    bar_index: int = -1


@dataclass
class LiquidityAnalysis:
    """Full liquidity analysis output."""
    ticker: str

    # Sweep detection
    sweep_detected: bool = False
    sweep_direction: str = "none"        # "up" / "down"
    sweep_level: float = 0.0
    sweep_reclaimed: bool = False        # Did price reclaim after sweep?

    # Equal levels
    equal_highs_detected: bool = False
    equal_highs_level: float = 0.0
    equal_lows_detected: bool = False
    equal_lows_level: float = 0.0

    # Breakout classification
    breakout_type: BreakoutType = BreakoutType.NO_BREAKOUT
    breakout_level: float = 0.0
    breakout_volume_confirmed: bool = False

    # Fake breakout signals (Part 11)
    fake_breakout_detected: bool = False
    fake_breakout_reason: str = ""
    fake_breakout_score: float = 0.0     # 0–100

    # Inducement
    inducement_detected: bool = False
    inducement_direction: str = "none"

    # Events timeline
    events: List[LiquidityEvent] = field(default_factory=list)

    # Composite
    liquidity_score: float = 0.0         # 0–100, how much liquidity activity
    trap_risk: float = 0.0              # 0–100, risk of being trapped

    def to_dict(self) -> dict:
        return {
            "sweep_detected": self.sweep_detected,
            "sweep_direction": self.sweep_direction,
            "sweep_reclaimed": self.sweep_reclaimed,
            "equal_highs": self.equal_highs_detected,
            "equal_lows": self.equal_lows_detected,
            "breakout_type": self.breakout_type.value,
            "fake_breakout": self.fake_breakout_detected,
            "fake_breakout_reason": self.fake_breakout_reason,
            "inducement": self.inducement_detected,
            "liquidity_score": self.liquidity_score,
            "trap_risk": self.trap_risk,
        }


class LiquidityEngine:
    """Detects liquidity events, fake breakouts, and manipulation."""

    def __init__(self, equal_level_tolerance: float = 0.003, swing_lookback: int = 5):
        self.equal_tol = equal_level_tolerance
        self.swing_lb = swing_lookback

    def analyze(self, ticker: str, bars: list) -> LiquidityAnalysis:
        """Full liquidity analysis."""
        if not bars or len(bars) < 30:
            return LiquidityAnalysis(ticker=ticker)

        result = LiquidityAnalysis(ticker=ticker)
        h = np.array([float(b.high) for b in bars])
        l = np.array([float(b.low) for b in bars])
        c = np.array([float(b.close) for b in bars])
        o = np.array([float(b.open) for b in bars])
        v = np.array([float(b.volume) for b in bars])

        # Detect swing points
        swing_highs, swing_lows = self._find_swings(h, l, c)

        # 1. Equal highs/lows
        self._detect_equal_levels(result, swing_highs, swing_lows, h, l)

        # 2. Liquidity sweeps
        self._detect_sweeps(result, h, l, c, o, v, swing_highs, swing_lows)

        # 3. Fake breakout detection (Part 11)
        self._detect_fake_breakouts(result, h, l, c, v, swing_highs, swing_lows)

        # 4. Inducement moves
        self._detect_inducement(result, h, l, c, v, swing_highs, swing_lows)

        # Compute composite scores
        result.liquidity_score = self._compute_liquidity_score(result)
        result.trap_risk = self._compute_trap_risk(result)

        logger.info(
            "Liquidity [%s]: sweep=%s fake=%s equal_hi=%s equal_lo=%s score=%.0f trap=%.0f",
            ticker, result.sweep_detected, result.fake_breakout_detected,
            result.equal_highs_detected, result.equal_lows_detected,
            result.liquidity_score, result.trap_risk,
        )

        return result

    def _find_swings(self, h, l, c) -> tuple:
        """Find swing highs and lows."""
        swing_highs = []  # (index, price)
        swing_lows = []

        lb = self.swing_lb
        for i in range(lb, len(h) - lb):
            # Swing high
            if h[i] == max(h[i-lb:i+lb+1]):
                swing_highs.append((i, float(h[i])))
            # Swing low
            if l[i] == min(l[i-lb:i+lb+1]):
                swing_lows.append((i, float(l[i])))

        return swing_highs, swing_lows

    def _detect_equal_levels(self, result, swing_highs, swing_lows, h, l):
        """Detect equal highs and equal lows (liquidity pools)."""
        # Equal highs
        if len(swing_highs) >= 2:
            for i in range(len(swing_highs) - 1):
                for j in range(i + 1, len(swing_highs)):
                    diff = abs(swing_highs[i][1] - swing_highs[j][1])
                    avg = (swing_highs[i][1] + swing_highs[j][1]) / 2
                    if diff / avg < self.equal_tol:
                        result.equal_highs_detected = True
                        result.equal_highs_level = avg
                        result.events.append(LiquidityEvent(
                            event_type=LiquidityEventType.EQUAL_LEVEL,
                            level=avg, direction="up",
                            description=f"Equal highs at {avg:.2f}",
                            confidence=70,
                        ))
                        break
                if result.equal_highs_detected:
                    break

        # Equal lows
        if len(swing_lows) >= 2:
            for i in range(len(swing_lows) - 1):
                for j in range(i + 1, len(swing_lows)):
                    diff = abs(swing_lows[i][1] - swing_lows[j][1])
                    avg = (swing_lows[i][1] + swing_lows[j][1]) / 2
                    if diff / avg < self.equal_tol:
                        result.equal_lows_detected = True
                        result.equal_lows_level = avg
                        result.events.append(LiquidityEvent(
                            event_type=LiquidityEventType.EQUAL_LEVEL,
                            level=avg, direction="down",
                            description=f"Equal lows at {avg:.2f}",
                            confidence=70,
                        ))
                        break
                if result.equal_lows_detected:
                    break

    def _detect_sweeps(self, result, h, l, c, o, v, swing_highs, swing_lows):
        """Detect liquidity sweeps (wicks through key levels with reversal)."""
        if len(c) < 10:
            return

        price = c[-1]

        # Check recent bars for sweep pattern
        for i in range(-5, 0):
            idx = len(c) + i
            if idx < 1:
                continue

            wick_up = h[idx] - max(o[idx], c[idx])
            wick_down = min(o[idx], c[idx]) - l[idx]
            body = abs(c[idx] - o[idx])

            # Downward sweep: long lower wick, closed above open (reversal)
            if wick_down > body * 1.5 and c[idx] > o[idx]:
                # Check if wick went below recent swing low
                for si, sl in swing_lows:
                    if si < idx and l[idx] < sl and c[idx] > sl:
                        result.sweep_detected = True
                        result.sweep_direction = "down"
                        result.sweep_level = sl
                        result.sweep_reclaimed = price > sl
                        result.events.append(LiquidityEvent(
                            event_type=LiquidityEventType.LIQUIDITY_GRAB,
                            level=sl, direction="down",
                            description=f"Sweep below {sl:.2f} with reversal",
                            confidence=80, bar_index=idx,
                        ))
                        break

            # Upward sweep: long upper wick, closed below open (rejection)
            if wick_up > body * 1.5 and c[idx] < o[idx]:
                for si, sh in swing_highs:
                    if si < idx and h[idx] > sh and c[idx] < sh:
                        result.sweep_detected = True
                        result.sweep_direction = "up"
                        result.sweep_level = sh
                        result.sweep_reclaimed = price < sh
                        result.events.append(LiquidityEvent(
                            event_type=LiquidityEventType.LIQUIDITY_GRAB,
                            level=sh, direction="up",
                            description=f"Sweep above {sh:.2f} with rejection",
                            confidence=80, bar_index=idx,
                        ))
                        break

    def _detect_fake_breakouts(self, result, h, l, c, v, swing_highs, swing_lows):
        """Part 11: Detect fake breakouts."""
        if len(c) < 15:
            return

        reasons = []
        fake_score = 0

        # Check last 5 bars for breakout pattern
        recent_high = float(np.max(h[-5:]))
        prev_resistance = float(np.max(h[-15:-5])) if len(h) >= 15 else 0

        recent_low = float(np.min(l[-5:]))
        prev_support = float(np.min(l[-15:-5])) if len(l) >= 15 else 0

        # 1. Breakout without volume
        avg_vol = float(np.mean(v[-20:])) if len(v) >= 20 else float(np.mean(v))
        breakout_vol = float(np.mean(v[-3:])) if len(v) >= 3 else avg_vol

        if recent_high > prev_resistance:
            if breakout_vol < avg_vol * 1.2:
                reasons.append("Breakout without volume confirmation")
                fake_score += 30

        # 2. Repeated resistance tests (3+ touches)
        if swing_highs:
            touches_near_high = sum(1 for _, sh in swing_highs if abs(sh - prev_resistance) / prev_resistance < 0.005)
            if touches_near_high >= 3:
                reasons.append(f"Repeated resistance tests ({touches_near_high}x)")
                fake_score += 20

        # 3. Long wicks (rejection)
        for i in range(-3, 0):
            idx = len(c) + i
            if idx < 0:
                continue
            body = abs(c[idx] - o[idx])
            upper_wick = h[idx] - max(c[idx], o[idx])
            if body > 0 and upper_wick > body * 2:
                reasons.append("Long rejection wick detected")
                fake_score += 25
                break

        # 4. Failure to hold level
        if recent_high > prev_resistance and c[-1] < prev_resistance:
            reasons.append("Failed to hold above breakout level")
            fake_score += 30

        # 5. Declining volume on approach
        if len(v) >= 10:
            vol_trend = np.polyfit(range(10), v[-10:], 1)[0]
            if vol_trend < 0 and recent_high > prev_resistance:
                reasons.append("Declining volume on approach to resistance")
                fake_score += 15

        if fake_score >= 30:
            result.fake_breakout_detected = True
            result.fake_breakout_reason = "; ".join(reasons[:3])
            result.fake_breakout_score = min(100, fake_score)
            result.breakout_type = BreakoutType.FAKE_BREAKOUT

            result.events.append(LiquidityEvent(
                event_type=LiquidityEventType.MANIPULATION,
                level=prev_resistance, direction="up",
                description=f"Fake breakout: {result.fake_breakout_reason}",
                confidence=min(90, fake_score),
            ))
        elif recent_high > prev_resistance and breakout_vol > avg_vol * 1.5 and c[-1] > prev_resistance:
            result.breakout_type = BreakoutType.TRUE_BREAKOUT
            result.breakout_level = prev_resistance
            result.breakout_volume_confirmed = True

    def _detect_inducement(self, result, h, l, c, v, swing_highs, swing_lows):
        """Detect inducement moves (small false moves to trap traders)."""
        if len(c) < 15:
            return

        # Look for a small push above resistance followed by quick reversal
        for i in range(-5, -1):
            idx = len(c) + i
            if idx < 1:
                continue

            # Small breakout followed by reversal in next bar
            if idx + 1 < len(c):
                # Upward inducement
                if c[idx] > c[idx-1] and c[idx+1] < c[idx] * 0.995:
                    body_break = abs(c[idx] - o[idx])
                    body_reverse = abs(c[idx+1] - o[idx+1])
                    if body_reverse > body_break * 1.5:
                        result.inducement_detected = True
                        result.inducement_direction = "up"
                        result.events.append(LiquidityEvent(
                            event_type=LiquidityEventType.INDUCEMENT,
                            level=float(c[idx]), direction="up",
                            description="Inducement move: small break then strong reversal",
                            confidence=60, bar_index=idx,
                        ))
                        break

    def _compute_liquidity_score(self, result: LiquidityAnalysis) -> float:
        """Score overall liquidity activity (0–100)."""
        score = 0
        if result.sweep_detected: score += 30
        if result.equal_highs_detected: score += 15
        if result.equal_lows_detected: score += 15
        if result.fake_breakout_detected: score += 20
        if result.inducement_detected: score += 10
        score += len(result.events) * 5
        return min(100, score)

    def _compute_trap_risk(self, result: LiquidityAnalysis) -> float:
        """Compute risk of being trapped (0–100)."""
        risk = 0
        if result.fake_breakout_detected: risk += 40
        if result.inducement_detected: risk += 20
        if result.sweep_detected and not result.sweep_reclaimed: risk += 25
        if result.equal_highs_detected: risk += 10
        if result.equal_lows_detected: risk += 10
        return min(100, risk)
