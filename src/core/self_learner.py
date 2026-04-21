"""
Self-Learning Engine — V4

Tracks signal outcomes, computes performance metrics, and auto-adjusts
detection thresholds based on historical win/loss patterns.

Workflow:
  1. Record outcomes against signals (from logging_service)
  2. Compute aggregate performance snapshots
  3. Suggest threshold adjustments to improve win rate
"""

import logging
from typing import Optional

from sqlalchemy.orm import Session

from src.models.database import Signal as SignalRecord, SignalOutcome
from src.models.schemas import (
    PerformanceSnapshot,
    ThresholdAdjustment,
    OutcomeType,
)

logger = logging.getLogger(__name__)

# Grade ordering for comparison
GRADE_ORDER = {"A": 5, "B": 4, "C": 3, "D": 2, "F": 1}
GRADE_REVERSE = {v: k for k, v in GRADE_ORDER.items()}


class SelfLearner:
    """Track outcomes and auto-tune system thresholds."""

    def __init__(self, db: Session):
        self.db = db

    # ── Performance snapshot ─────────────────────────────────────────────

    def get_performance(self, last_n: Optional[int] = None) -> PerformanceSnapshot:
        """Compute performance metrics from stored outcomes."""
        query = (
            self.db.query(SignalRecord, SignalOutcome)
            .join(SignalOutcome, SignalRecord.id == SignalOutcome.signal_id, isouter=True)
            .order_by(SignalRecord.created_at.desc())
        )
        if last_n:
            query = query.limit(last_n)

        rows = query.all()

        if not rows:
            return PerformanceSnapshot()

        total = len(rows)
        wins, losses = 0, 0
        pnls = []
        confidences = []
        grade_scores = []

        for signal, outcome in rows:
            if signal.confidence:
                confidences.append(signal.confidence)
            if signal.setup_grade and signal.setup_grade in GRADE_ORDER:
                grade_scores.append((GRADE_ORDER[signal.setup_grade], signal.setup_grade))

            if outcome is None:
                continue
            if outcome.outcome == OutcomeType.WIN.value:
                wins += 1
            elif outcome.outcome == OutcomeType.LOSS.value:
                losses += 1
            if outcome.pnl_percent is not None:
                pnls.append(outcome.pnl_percent)

        win_rate = (wins / (wins + losses) * 100) if (wins + losses) > 0 else 0
        avg_pnl = sum(pnls) / len(pnls) if pnls else 0

        win_pnls = [p for p in pnls if p > 0]
        loss_pnls = [p for p in pnls if p < 0]
        gross_profit = sum(win_pnls) if win_pnls else 0
        gross_loss = abs(sum(loss_pnls)) if loss_pnls else 0
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf") if gross_profit > 0 else 0

        best_grade = max(grade_scores, key=lambda x: x[0])[1] if grade_scores else None
        worst_grade = min(grade_scores, key=lambda x: x[0])[1] if grade_scores else None
        avg_conf = sum(confidences) / len(confidences) if confidences else 0

        return PerformanceSnapshot(
            total_signals=total,
            total_wins=wins,
            total_losses=losses,
            win_rate=round(win_rate, 1),
            avg_pnl_pct=round(avg_pnl, 2),
            profit_factor=round(profit_factor, 2) if profit_factor != float("inf") else 999.0,
            best_setup_grade=best_grade,
            worst_setup_grade=worst_grade,
            avg_confidence=round(avg_conf, 1),
        )

    # ── Threshold adjustment suggestions ─────────────────────────────────

    def suggest_adjustments(self) -> list[ThresholdAdjustment]:
        """Analyze outcomes and suggest threshold tweaks."""
        perf = self.get_performance(last_n=100)
        adjustments = []

        if perf.total_signals < 20:
            logger.info("Not enough signals (%d) for adjustment suggestions", perf.total_signals)
            return adjustments

        # If win rate too low, tighten entry thresholds
        if perf.win_rate < 40:
            adjustments.append(ThresholdAdjustment(
                parameter="bounce_min_probability",
                old_value=40.0,
                new_value=50.0,
                reason=f"Win rate {perf.win_rate}% — tighten bounce threshold",
            ))
            adjustments.append(ThresholdAdjustment(
                parameter="dip_min_probability",
                old_value=40.0,
                new_value=50.0,
                reason=f"Win rate {perf.win_rate}% — tighten dip threshold",
            ))

        # If profit factor too low, widen stops
        if perf.profit_factor < 1.0 and perf.profit_factor > 0:
            adjustments.append(ThresholdAdjustment(
                parameter="stop_loss_multiplier",
                old_value=1.0,
                new_value=1.3,
                reason=f"Profit factor {perf.profit_factor:.2f} — widen stops",
            ))

        # If win rate high but avg PnL low, tighten targets
        if perf.win_rate > 60 and perf.avg_pnl_pct < 0.5:
            adjustments.append(ThresholdAdjustment(
                parameter="target_risk_reward_ratio",
                old_value=2.0,
                new_value=2.5,
                reason=f"High win rate ({perf.win_rate}%) but low avg PnL ({perf.avg_pnl_pct}%) — raise targets",
            ))

        # If confidence is low on winning trades, adjust confidence weighting
        if perf.avg_confidence < 40:
            adjustments.append(ThresholdAdjustment(
                parameter="min_confidence_for_buy",
                old_value=30.0,
                new_value=45.0,
                reason=f"Avg confidence {perf.avg_confidence:.0f}% — raise min confidence",
            ))

        logger.info("SelfLearner suggests %d adjustments", len(adjustments))
        return adjustments
