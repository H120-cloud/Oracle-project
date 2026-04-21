"""
Adaptation Engine — Parts 9 + 10

Part 9: Real-Time Adaptation
- Continuously update probabilities, targets, reaction state
- Track status: ON_TRACK / OVERPERFORMING / UNDERPERFORMING / FAILED

Part 10: End-of-Day Learning
- Track MFE (Maximum Favorable Excursion) / MAE (Maximum Adverse Excursion)
- Classify outcomes: PERFECT / GOOD / PARTIAL / FAILED
- Adjust model weights dynamically
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, List, Dict
from enum import Enum

import numpy as np

logger = logging.getLogger(__name__)


# ── Part 9: Real-Time Status ─────────────────────────────────────────────────

class TradeStatus(str, Enum):
    ON_TRACK = "ON_TRACK"
    OVERPERFORMING = "OVERPERFORMING"
    UNDERPERFORMING = "UNDERPERFORMING"
    FAILED = "FAILED"


class OutcomeGrade(str, Enum):
    PERFECT = "PERFECT"       # Hit T2, max drawdown < 30% of target
    GOOD = "GOOD"             # Hit T1, controlled drawdown
    PARTIAL = "PARTIAL"       # Partial target hit
    FAILED = "FAILED"         # Stopped out or no target hit


@dataclass
class TradeTracker:
    """Tracks a live trade for real-time adaptation."""
    ticker: str
    entry_price: float = 0.0
    entry_time: Optional[datetime] = None
    target_1: float = 0.0
    target_2: float = 0.0
    stop_loss: float = 0.0
    predicted_direction: str = "bullish"

    # Live tracking
    current_price: float = 0.0
    status: TradeStatus = TradeStatus.ON_TRACK
    progress_to_t1_pct: float = 0.0
    progress_to_t2_pct: float = 0.0

    # MFE / MAE
    mfe: float = 0.0          # Maximum Favorable Excursion (best unrealized P&L %)
    mae: float = 0.0          # Maximum Adverse Excursion (worst unrealized loss %)
    highest_price: float = 0.0
    lowest_price: float = 0.0

    # Flags
    t1_hit: bool = False
    t2_hit: bool = False
    stop_hit: bool = False

    def to_dict(self) -> dict:
        return {
            "ticker": self.ticker,
            "entry_price": self.entry_price,
            "current_price": self.current_price,
            "status": self.status.value,
            "progress_t1": self.progress_to_t1_pct,
            "progress_t2": self.progress_to_t2_pct,
            "mfe": self.mfe,
            "mae": self.mae,
            "t1_hit": self.t1_hit,
            "t2_hit": self.t2_hit,
            "stop_hit": self.stop_hit,
        }


@dataclass
class EODResult:
    """End-of-day outcome analysis."""
    ticker: str
    outcome_grade: OutcomeGrade = OutcomeGrade.FAILED
    pnl_pct: float = 0.0
    mfe: float = 0.0
    mae: float = 0.0
    t1_hit: bool = False
    t2_hit: bool = False
    prediction_error_pct: float = 0.0   # Actual vs predicted move
    duration_minutes: float = 0.0

    # For learning
    entry_quality_correct: bool = False  # Was the entry timing good?
    target_accuracy: float = 0.0        # How close were targets?
    stop_placement_quality: float = 0.0  # Was stop well placed?


@dataclass
class WeightAdjustment:
    """Dynamic weight adjustment from learning."""
    component: str
    old_weight: float
    new_weight: float
    reason: str


class AdaptationEngine:
    """Real-time adaptation and end-of-day learning."""

    def __init__(self):
        self.active_trades: Dict[str, TradeTracker] = {}
        self.completed_trades: List[EODResult] = []

        # Dynamic weights (start with defaults)
        self.weights = {
            "catalyst": 0.15,
            "freshness": 0.08,
            "reaction": 0.12,
            "volume": 0.12,
            "structure": 0.15,
            "trend": 0.12,
            "liquidity": 0.10,
            "market_context": 0.08,
            "mtf_alignment": 0.08,
        }

    # ── Part 9: Real-Time Tracking ────────────────────────────────────────

    def start_tracking(
        self, ticker: str, entry_price: float,
        target_1: float, target_2: float, stop_loss: float,
        direction: str = "bullish",
    ) -> TradeTracker:
        """Start tracking a new trade."""
        tracker = TradeTracker(
            ticker=ticker,
            entry_price=entry_price,
            entry_time=datetime.now(timezone.utc),
            target_1=target_1,
            target_2=target_2,
            stop_loss=stop_loss,
            predicted_direction=direction,
            current_price=entry_price,
            highest_price=entry_price,
            lowest_price=entry_price,
        )
        self.active_trades[ticker] = tracker
        logger.info("Tracking started for %s: entry=%.2f T1=%.2f T2=%.2f SL=%.2f",
                    ticker, entry_price, target_1, target_2, stop_loss)
        return tracker

    def update(self, ticker: str, current_price: float) -> Optional[TradeTracker]:
        """Update a tracked trade with new price."""
        tracker = self.active_trades.get(ticker)
        if not tracker:
            return None

        tracker.current_price = current_price
        is_long = tracker.predicted_direction == "bullish"

        # Update high/low
        tracker.highest_price = max(tracker.highest_price, current_price)
        tracker.lowest_price = min(tracker.lowest_price, current_price)

        # MFE / MAE
        if is_long:
            tracker.mfe = round((tracker.highest_price - tracker.entry_price) / tracker.entry_price * 100, 2)
            tracker.mae = round((tracker.entry_price - tracker.lowest_price) / tracker.entry_price * 100, 2)
        else:
            tracker.mfe = round((tracker.entry_price - tracker.lowest_price) / tracker.entry_price * 100, 2)
            tracker.mae = round((tracker.highest_price - tracker.entry_price) / tracker.entry_price * 100, 2)

        # Progress to targets
        if is_long:
            total_move_t1 = tracker.target_1 - tracker.entry_price
            total_move_t2 = tracker.target_2 - tracker.entry_price
            current_move = current_price - tracker.entry_price

            tracker.progress_to_t1_pct = round(current_move / total_move_t1 * 100, 1) if total_move_t1 > 0 else 0
            tracker.progress_to_t2_pct = round(current_move / total_move_t2 * 100, 1) if total_move_t2 > 0 else 0

            tracker.t1_hit = current_price >= tracker.target_1
            tracker.t2_hit = current_price >= tracker.target_2
            tracker.stop_hit = current_price <= tracker.stop_loss
        else:
            total_move_t1 = tracker.entry_price - tracker.target_1
            total_move_t2 = tracker.entry_price - tracker.target_2
            current_move = tracker.entry_price - current_price

            tracker.progress_to_t1_pct = round(current_move / total_move_t1 * 100, 1) if total_move_t1 > 0 else 0
            tracker.progress_to_t2_pct = round(current_move / total_move_t2 * 100, 1) if total_move_t2 > 0 else 0

            tracker.t1_hit = current_price <= tracker.target_1
            tracker.t2_hit = current_price <= tracker.target_2
            tracker.stop_hit = current_price >= tracker.stop_loss

        # Status
        tracker.status = self._compute_status(tracker)

        return tracker

    def _compute_status(self, t: TradeTracker) -> TradeStatus:
        """Compute current trade status."""
        if t.stop_hit:
            return TradeStatus.FAILED
        if t.t2_hit:
            return TradeStatus.OVERPERFORMING
        if t.t1_hit or t.progress_to_t1_pct >= 80:
            return TradeStatus.ON_TRACK
        if t.progress_to_t1_pct >= 30:
            return TradeStatus.ON_TRACK
        if t.mae > 3:
            return TradeStatus.UNDERPERFORMING
        return TradeStatus.ON_TRACK

    def get_all_active(self) -> List[dict]:
        """Get all active trade trackers."""
        return [t.to_dict() for t in self.active_trades.values()]

    # ── Part 10: End-of-Day Learning ──────────────────────────────────────

    def close_trade(self, ticker: str, exit_price: float) -> Optional[EODResult]:
        """Close a trade and compute EOD metrics."""
        tracker = self.active_trades.pop(ticker, None)
        if not tracker:
            return None

        is_long = tracker.predicted_direction == "bullish"

        # PnL
        if is_long:
            pnl = (exit_price - tracker.entry_price) / tracker.entry_price * 100
        else:
            pnl = (tracker.entry_price - exit_price) / tracker.entry_price * 100

        # Prediction error
        predicted_target = tracker.target_1
        if is_long:
            actual_move = exit_price - tracker.entry_price
            predicted_move = predicted_target - tracker.entry_price
        else:
            actual_move = tracker.entry_price - exit_price
            predicted_move = tracker.entry_price - predicted_target

        pred_error = abs(actual_move - predicted_move) / abs(predicted_move) * 100 if predicted_move != 0 else 0

        # Duration
        duration = 0
        if tracker.entry_time:
            duration = (datetime.now(timezone.utc) - tracker.entry_time).total_seconds() / 60

        # Grade
        grade = self._grade_outcome(tracker, pnl)

        result = EODResult(
            ticker=ticker,
            outcome_grade=grade,
            pnl_pct=round(pnl, 2),
            mfe=tracker.mfe,
            mae=tracker.mae,
            t1_hit=tracker.t1_hit,
            t2_hit=tracker.t2_hit,
            prediction_error_pct=round(pred_error, 1),
            duration_minutes=round(duration, 1),
            entry_quality_correct=tracker.mae < 2,
            target_accuracy=round(max(0, 100 - pred_error), 1),
            stop_placement_quality=round(max(0, 100 - tracker.mae * 20), 1),
        )

        self.completed_trades.append(result)
        logger.info(
            "Trade closed [%s]: grade=%s pnl=%.2f%% mfe=%.2f%% mae=%.2f%%",
            ticker, grade.value, pnl, tracker.mfe, tracker.mae,
        )

        return result

    def _grade_outcome(self, tracker: TradeTracker, pnl: float) -> OutcomeGrade:
        """Classify trade outcome grade."""
        if tracker.t2_hit and tracker.mae < (tracker.mfe * 0.3):
            return OutcomeGrade.PERFECT
        if tracker.t1_hit and pnl > 0:
            return OutcomeGrade.GOOD
        if pnl > 0:
            return OutcomeGrade.PARTIAL
        return OutcomeGrade.FAILED

    def compute_learning_adjustments(self, min_trades: int = 10) -> List[WeightAdjustment]:
        """Analyze completed trades and suggest weight adjustments."""
        if len(self.completed_trades) < min_trades:
            return []

        adjustments = []
        wins = [t for t in self.completed_trades if t.pnl_pct > 0]
        losses = [t for t in self.completed_trades if t.pnl_pct <= 0]
        win_rate = len(wins) / len(self.completed_trades) * 100

        # If win rate low, increase structure weight (be more selective)
        if win_rate < 45:
            old = self.weights.get("structure", 0.15)
            new = min(0.25, old + 0.03)
            if new != old:
                adjustments.append(WeightAdjustment("structure", old, new,
                    f"Win rate {win_rate:.0f}% — increase structure weight"))
                self.weights["structure"] = new

        # If MAE too high on average, increase liquidity weight (better trap avoidance)
        avg_mae = np.mean([t.mae for t in self.completed_trades]) if self.completed_trades else 0
        if avg_mae > 3:
            old = self.weights.get("liquidity", 0.10)
            new = min(0.20, old + 0.02)
            if new != old:
                adjustments.append(WeightAdjustment("liquidity", old, new,
                    f"Avg MAE {avg_mae:.1f}% — increase liquidity awareness"))
                self.weights["liquidity"] = new

        # If prediction error high, increase trend weight
        avg_pred_err = np.mean([t.prediction_error_pct for t in self.completed_trades]) if self.completed_trades else 0
        if avg_pred_err > 50:
            old = self.weights.get("trend", 0.12)
            new = min(0.20, old + 0.02)
            if new != old:
                adjustments.append(WeightAdjustment("trend", old, new,
                    f"Avg prediction error {avg_pred_err:.0f}% — increase trend weight"))
                self.weights["trend"] = new

        # Normalize weights
        total = sum(self.weights.values())
        if total > 0:
            self.weights = {k: round(v / total, 4) for k, v in self.weights.items()}

        logger.info("Learning: %d adjustments from %d trades (WR=%.0f%% MAE=%.1f%%)",
                    len(adjustments), len(self.completed_trades), win_rate, avg_mae)

        return adjustments

    def get_weights(self) -> dict:
        """Get current dynamic weights."""
        return dict(self.weights)
