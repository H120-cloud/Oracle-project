"""
V17 Entry Timing Alert State Machine

Tracks per-ticker alert transitions and enforces cooldowns.
Only sends actionable HIGH PRIORITY alerts when timing_state == IDEAL_ENTRY.
"""

import time
from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime, timezone

from src.core.agentic.models import EntryTimingState


@dataclass
class TickerAlertState:
    """Per-ticker alert tracking."""
    ticker: str
    last_alert_state: Optional[str] = None
    last_alert_time: float = 0.0
    cooldown_until: float = 0.0
    last_entry_score: float = 0.0
    watch_sent: bool = False
    entry_sent: bool = False
    avoid_sent: bool = False


class AlertStateMachine:
    """
    Manages alert transitions for the Entry Timing Engine.
    States: WATCH (TOO_EARLY/WAITING) -> ENTRY (IDEAL_ENTRY) -> AVOID (LATE_CHASE/INVALID)
    """

    COOLDOWN_SECONDS = 300  # 5 minutes
    SCORE_IMPROVEMENT_THRESHOLD = 10.0

    def __init__(self):
        self._states: dict[str, TickerAlertState] = {}

    def _get_state(self, ticker: str) -> TickerAlertState:
        if ticker not in self._states:
            self._states[ticker] = TickerAlertState(ticker=ticker)
        return self._states[ticker]

    def evaluate(self, ticker: str, timing_state: EntryTimingState,
                 entry_score: float, final_probability: float,
                 hard_rejection_triggered: bool) -> Optional[str]:
        """
        Returns the alert action to take, or None if suppressed.
        Actions: "watch", "entry", "avoid", None
        """
        state = self._get_state(ticker)
        now = time.time()

        # Clear cooldown if expired
        if now >= state.cooldown_until:
            state.cooldown_until = 0.0

        # Determine desired alert type from timing state
        if timing_state == EntryTimingState.IDEAL_ENTRY:
            desired = "entry"
        elif timing_state in (EntryTimingState.TOO_EARLY, EntryTimingState.WAITING_FOR_CONFIRMATION):
            desired = "watch"
        elif timing_state in (EntryTimingState.LATE_CHASE, EntryTimingState.INVALID_ENTRY):
            desired = "avoid"
        else:
            desired = None

        if desired is None:
            return None

        # Hard rejection blocks entry alerts but still allows avoid/watch
        if hard_rejection_triggered and desired == "entry":
            return None

        # Entry alert gating
        if desired == "entry":
            # Probability gating
            if final_probability < 70:
                return None
            # Already sent entry and no material improvement
            if state.entry_sent:
                if state.cooldown_until > now:
                    return None
                if entry_score <= state.last_entry_score + self.SCORE_IMPROVEMENT_THRESHOLD:
                    return None
            state.entry_sent = True
            state.last_entry_score = entry_score
            state.cooldown_until = now + self.COOLDOWN_SECONDS
            state.last_alert_state = "entry"
            state.last_alert_time = now
            return "entry"

        # Watch alert gating
        if desired == "watch":
            if state.watch_sent:
                return None  # Only one WATCH per ticker
            state.watch_sent = True
            state.last_alert_state = "watch"
            state.last_alert_time = now
            return "watch"

        # Avoid alert gating
        if desired == "avoid":
            if state.avoid_sent:
                return None  # Only one AVOID per ticker
            state.avoid_sent = True
            state.last_alert_state = "avoid"
            state.last_alert_time = now
            return "avoid"

        return None

    def reset_ticker(self, ticker: str):
        """Reset a ticker state (e.g., on new catalyst cycle)."""
        self._states.pop(ticker, None)

    def get_summary(self, ticker: str) -> dict:
        state = self._get_state(ticker)
        return {
            "ticker": ticker,
            "last_alert_state": state.last_alert_state,
            "last_alert_time": datetime.fromtimestamp(state.last_alert_time, tz=timezone.utc).isoformat() if state.last_alert_time else None,
            "cooldown_active": state.cooldown_until > time.time(),
            "watch_sent": state.watch_sent,
            "entry_sent": state.entry_sent,
            "avoid_sent": state.avoid_sent,
        }
