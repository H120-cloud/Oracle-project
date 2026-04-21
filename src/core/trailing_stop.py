"""
Trailing Stop Engine — V11

Deterministic 3-stage stop management system:

  Stage 0 — Initial Protection
    Use entry stop (ATR / structure based). No changes.

  Stage 1 — Breakeven Protection
    Trigger: price reaches entry + 1R (reward == risk)
    Action:  move stop to entry price (breakeven)

  Stage 2 — Profit Lock (Trailing Activated)
    Trigger: price reaches entry + 2R
    Action:  trail stop = highest_price - (ATR × multiplier)

  Stage 3 — Strong Trend Extension (optional)
    If momentum is strong and volume increasing,
    widen trailing multiplier from 1.0 → 1.3 to let winners run.

Safety Rules:
  - Stop NEVER decreases (only tightens)
  - Trailing only activates after profit (+2R)
  - ATR is fixed at entry time (no recalculation)
"""

import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class TrailingStopState:
    """Per-position trailing stop state. Fully serializable."""
    # Entry parameters (frozen at entry time)
    entry_price: float = 0.0
    initial_stop: float = 0.0
    atr_at_entry: float = 0.0

    # Dynamic state
    current_stop: float = 0.0
    highest_price: float = 0.0
    moved_to_breakeven: bool = False
    trailing_active: bool = False

    # Configuration
    trailing_multiplier: float = 1.0
    breakeven_trigger_r: float = 1.0    # Move to BE at +1R
    trailing_trigger_r: float = 2.0     # Activate trail at +2R
    strong_trend_multiplier: float = 1.3  # Wider trail for strong trends

    # Partial profit taking
    partial_close_pct: float = 0.5    # Close 50% at partial trigger
    partial_close_at_r: float = 2.0   # Trigger partial at +2R (same as trailing trigger)
    partial_close_triggered: bool = False

    # Tracking
    max_r_reached: float = 0.0
    exit_type: str = ""  # "", "stop_loss", "breakeven", "trailing_stop", "target", "time_exit"

    @property
    def risk_per_share(self) -> float:
        """1R = entry - initial stop."""
        return abs(self.entry_price - self.initial_stop)

    @property
    def current_r(self) -> float:
        """Current R-multiple based on highest price reached."""
        r = self.risk_per_share
        if r <= 0:
            return 0.0
        return (self.highest_price - self.entry_price) / r

    def to_dict(self) -> dict:
        return {
            "entry_price": self.entry_price,
            "initial_stop": self.initial_stop,
            "atr_at_entry": self.atr_at_entry,
            "current_stop": self.current_stop,
            "highest_price": self.highest_price,
            "moved_to_breakeven": self.moved_to_breakeven,
            "trailing_active": self.trailing_active,
            "trailing_multiplier": self.trailing_multiplier,
            "partial_close_triggered": self.partial_close_triggered,
            "max_r_reached": round(self.max_r_reached, 2),
            "exit_type": self.exit_type,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "TrailingStopState":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


class TrailingStopEngine:
    """
    Stateless engine that evaluates trailing stop logic on each price update.

    Usage:
        engine = TrailingStopEngine()
        state = engine.create_state(entry=150, stop=145, atr=3.0)

        # On each new bar:
        action = engine.update(state, high=155, low=151, close=153)
        # action: "hold", "stop_hit", "partial_close"

        # On stop_hit, read state.exit_type for the reason.
        # On partial_close, close partial_close_pct of position and keep trailing.
    """

    @staticmethod
    def create_state(
        entry_price: float,
        initial_stop: float,
        atr_at_entry: float,
        trailing_multiplier: float = 1.0,
        breakeven_trigger_r: float = 1.0,
        trailing_trigger_r: float = 2.0,
        partial_close_pct: float = 0.5,
        enable_partial: bool = True,
    ) -> TrailingStopState:
        """Initialize trailing stop state at trade entry."""
        return TrailingStopState(
            entry_price=entry_price,
            initial_stop=initial_stop,
            atr_at_entry=atr_at_entry,
            current_stop=initial_stop,
            highest_price=entry_price,
            trailing_multiplier=trailing_multiplier,
            breakeven_trigger_r=breakeven_trigger_r,
            trailing_trigger_r=trailing_trigger_r,
            partial_close_pct=partial_close_pct if enable_partial else 0,
            partial_close_at_r=trailing_trigger_r,  # Partial at same level as trailing
        )

    @staticmethod
    def update(
        state: TrailingStopState,
        high: float,
        low: float,
        close: float,
        momentum_state: str = "neutral",
        volume_increasing: bool = False,
    ) -> str:
        """
        Evaluate one bar against the trailing stop state.

        Returns:
            "hold"          — keep position open
            "stop_hit"      — stop was triggered, exit trade
            "partial_close"  — close partial_close_pct of position, keep rest trailing

        On "stop_hit", state.exit_type is set to the reason.
        """
        r = state.risk_per_share
        if r <= 0:
            # Degenerate case: no risk defined
            return "hold"

        # ── CHECK STOP HIT FIRST (using bar low) ────────────────────────
        if low <= state.current_stop:
            if state.trailing_active:
                state.exit_type = "trailing_stop"
            elif state.moved_to_breakeven:
                state.exit_type = "breakeven"
            else:
                state.exit_type = "stop_loss"
            return "stop_hit"

        # ── UPDATE HIGHEST PRICE ─────────────────────────────────────────
        if high > state.highest_price:
            state.highest_price = high

        # Update max R reached
        current_r = (state.highest_price - state.entry_price) / r
        state.max_r_reached = max(state.max_r_reached, current_r)

        # ── PARTIAL PROFIT TAKING ────────────────────────────────────────
        should_partial = (
            not state.partial_close_triggered
            and state.partial_close_pct > 0
            and current_r >= state.partial_close_at_r
        )
        if should_partial:
            state.partial_close_triggered = True
            logger.debug(
                "Trailing: partial close (%.0f%%) @ %.1fR reached",
                state.partial_close_pct * 100, current_r,
            )
            # NOTE: don't return yet — still need to update breakeven/trailing below
            # The caller handles the partial close action

        # ── STAGE 1: BREAKEVEN ───────────────────────────────────────────
        if not state.moved_to_breakeven and current_r >= state.breakeven_trigger_r:
            new_stop = state.entry_price
            if new_stop > state.current_stop:
                state.current_stop = new_stop
                state.moved_to_breakeven = True
                logger.debug(
                    "Trailing: moved to breakeven @ %.2f (%.1fR reached)",
                    new_stop, current_r,
                )

        # ── STAGE 2: TRAILING ACTIVATED ──────────────────────────────────
        if not state.trailing_active and current_r >= state.trailing_trigger_r:
            state.trailing_active = True
            logger.debug(
                "Trailing: activated @ %.1fR reached", current_r,
            )

        # ── STAGE 3: STRONG TREND EXTENSION ──────────────────────────────
        multiplier = state.trailing_multiplier
        if (
            state.trailing_active
            and momentum_state in ("strong_up", "accelerating_up")
            and volume_increasing
        ):
            multiplier = state.strong_trend_multiplier

        # ── COMPUTE TRAILING STOP ────────────────────────────────────────
        if state.trailing_active and state.atr_at_entry > 0:
            new_stop = state.highest_price - (state.atr_at_entry * multiplier)
            # SAFETY: stop NEVER decreases
            if new_stop > state.current_stop:
                state.current_stop = round(new_stop, 4)

        if should_partial:
            return "partial_close"

        return "hold"

    @staticmethod
    def compute_atr(highs: list, lows: list, closes: list, period: int = 14) -> float:
        """Compute ATR from price arrays. Used at entry time."""
        if len(highs) < period + 1:
            # Fallback: use 2% of last close
            return closes[-1] * 0.02 if closes else 0.0

        trs = []
        for i in range(1, len(highs)):
            h, l, pc = highs[i], lows[i], closes[i - 1]
            tr = max(h - l, abs(h - pc), abs(l - pc))
            trs.append(tr)

        # Simple moving average ATR
        if len(trs) >= period:
            return sum(trs[-period:]) / period
        return sum(trs) / len(trs) if trs else 0.0
