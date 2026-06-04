"""
Missed Positive Catalyst Learning Engine (V22)

Detects when Oracle missed a winner, analyzes why, and generates
learning recommendations with safe adaptation guardrails.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional

from src.core.agentic.news_momentum_models import (
    CatalystSubType,
    MissedWinnerReason,
    MissedWinnerRecord,
    MissedWinnerLearningReport,
    NewsMomentumCandidate,
    NewsMomentumConfig,
    OracleAction,
)
from src.utils.atomic_json import save_json_file, load_json_file

logger = logging.getLogger(__name__)

DATA_DIR = Path("data/agentic")
MISSED_FILE = DATA_DIR / "news_momentum_missed_winners.json"
SHADOW_FILE = DATA_DIR / "news_momentum_shadow_adjustments.json"

# ── Constants ───────────────────────────────────────────────────────────────

MISSED_WINNER_THRESHOLDS = {
    "1h": 20.0,
    "same_day": 50.0,
    "2day": 75.0,
    "5day": 100.0,
}

MIN_MISSED_FOR_CATALYST_ADJUSTMENT = 30
MIN_TOTAL_OUTCOMES_FOR_GLOBAL_ADJUSTMENT = 100


class MissedCatalystLearningEngine:
    """Detects missed winners and generates learning recommendations."""

    def __init__(self, config: Optional[NewsMomentumConfig] = None):
        self.config = config or NewsMomentumConfig()
        self._records: List[MissedWinnerRecord] = []
        self._shadow_adjustments: Dict[str, dict] = {}
        self._load()
        self._load_shadow()

    # ── Persistence ──────────────────────────────────────────────────────────

    def _load(self) -> None:
        raw = load_json_file(MISSED_FILE, default=[])
        self._records = []
        for r in raw:
            try:
                self._records.append(MissedWinnerRecord.model_validate(r))
            except Exception as exc:
                logger.debug("MissedLearning: skip bad record: %s", exc)

    def _persist(self) -> None:
        save_json_file(MISSED_FILE, [r.model_dump(mode="json") for r in self._records])

    def _load_shadow(self) -> None:
        self._shadow_adjustments = load_json_file(SHADOW_FILE, default={})

    def _persist_shadow(self) -> None:
        save_json_file(SHADOW_FILE, self._shadow_adjustments)

    # ── Missed Winner Detection ──────────────────────────────────────────────

    def analyze_candidate(
        self,
        candidate: NewsMomentumCandidate,
        alert_sent: bool,
        prices: Optional[dict] = None,
    ) -> Optional[MissedWinnerRecord]:
        """Analyze a candidate post-move to see if it was a missed winner."""
        if not prices:
            return None

        # Calculate moves
        price_at_news = prices.get("price_at_news") or candidate.current_price or 0
        if price_at_news <= 0:
            return None

        moves = self._calculate_moves(price_at_news, prices)
        is_winner = self._is_missed_winner(moves, alert_sent, candidate)

        if not is_winner:
            return None

        # Build missed record
        record = self._build_missed_record(candidate, moves, alert_sent, prices)

        # Check if already tracked
        existing = next((r for r in self._records if r.ticker == record.ticker and r.headline == record.headline), None)
        if existing:
            # Update if more complete
            if not existing.max_price_after_news and record.max_price_after_news:
                existing.max_price_after_news = record.max_price_after_news
                existing.move_same_day_pct = record.move_same_day_pct
                existing.move_2day_pct = record.move_2day_pct
                existing.move_5day_pct = record.move_5day_pct
                self._persist()
            return existing

        self._records.append(record)
        self._persist()
        # Log at DEBUG (was INFO) — this is an internal learning signal and
        # tickers like RKTO can accumulate 15+ records/day due to Finviz
        # tagging unrelated headlines with the same ticker. Also rate-limit
        # to one log per ticker per hour so even at DEBUG it doesn't spam.
        now_ts = datetime.now(timezone.utc)
        last = getattr(self, "_last_logged_at_by_ticker", None)
        if last is None:
            last = {}
            self._last_logged_at_by_ticker = last  # type: ignore[attr-defined]
        prev = last.get(record.ticker)
        if prev is None or (now_ts - prev).total_seconds() >= 3600:
            logger.info(
                "MissedLearning: detected missed winner %s (+%s%% same-day, reason: %s)",
                record.ticker, record.move_same_day_pct or "N/A", record.blocking_rule
            )
            last[record.ticker] = now_ts
        else:
            logger.debug(
                "MissedLearning: detected missed winner %s (+%s%% same-day, reason: %s)",
                record.ticker, record.move_same_day_pct or "N/A", record.blocking_rule
            )
        return record

    def _calculate_moves(self, price_at_news: float, prices: dict) -> dict:
        """Calculate move percentages from price data."""
        moves = {}
        for key in ["1h", "same_day", "2day", "5day"]:
            p = prices.get(f"price_{key}")
            if p and price_at_news > 0:
                moves[key] = round(((p - price_at_news) / price_at_news) * 100, 2)
            else:
                moves[key] = None
        return moves

    def _is_missed_winner(
        self,
        moves: dict,
        alert_sent: bool,
        candidate: NewsMomentumCandidate,
    ) -> bool:
        """Determine if this was a missed winner."""
        # Must be positive news
        if candidate.is_negative or candidate.is_vague:
            # Only count if misclassified (strong move despite negative/vague)
            if not (moves.get("same_day") and moves["same_day"] > 30):
                return False

        # Check move thresholds
        winner = False
        if moves.get("1h") and moves["1h"] >= MISSED_WINNER_THRESHOLDS["1h"]:
            winner = True
        if moves.get("same_day") and moves["same_day"] >= MISSED_WINNER_THRESHOLDS["same_day"]:
            winner = True
        if moves.get("2day") and moves["2day"] >= MISSED_WINNER_THRESHOLDS["2day"]:
            winner = True
        if moves.get("5day") and moves["5day"] >= MISSED_WINNER_THRESHOLDS["5day"]:
            winner = True

        if not winner:
            return False

        # Missed if no alert, or alert was late/after move, or action was wrong
        if not alert_sent:
            return True
        if candidate.oracle_action in (OracleAction.AVOID_TRAP, OracleAction.AVOID_CHASE):
            if moves.get("same_day", 0) > 30:
                return True

        return False

    def _build_missed_record(
        self,
        candidate: NewsMomentumCandidate,
        moves: dict,
        alert_sent: bool,
        prices: dict,
    ) -> MissedWinnerRecord:
        """Build a missed winner record with full analysis."""
        reasons: List[MissedWinnerReason] = []
        blocking = []
        score_gap = 0.0

        # Determine why it was missed
        if not alert_sent:
            if candidate.news_impact_score < self.config.telegram_min_score:
                reasons.append(MissedWinnerReason.NEWS_IMPACT_TOO_LOW)
                blocking.append(f"news_impact {candidate.news_impact_score:.0f} < {self.config.telegram_min_score}")
                score_gap = max(score_gap, self.config.telegram_min_score - candidate.news_impact_score)
            if candidate.expected_return_score < self.config.expected_return_threshold:
                reasons.append(MissedWinnerReason.EXPECTED_RETURN_TOO_LOW)
                blocking.append(f"expected_return {candidate.expected_return_score:.0f} < {self.config.expected_return_threshold}")
                score_gap = max(score_gap, self.config.expected_return_threshold - candidate.expected_return_score)
            if candidate.continuation_probability < self.config.continuation_threshold:
                reasons.append(MissedWinnerReason.CONTINUATION_TOO_LOW)
                blocking.append(f"continuation {candidate.continuation_probability:.0f} < {self.config.continuation_threshold}")
                score_gap = max(score_gap, self.config.continuation_threshold - candidate.continuation_probability)
            if candidate.multi_day_continuation_score < self.config.multi_day_threshold:
                reasons.append(MissedWinnerReason.MULTI_DAY_TOO_LOW)
                blocking.append(f"multi_day {candidate.multi_day_continuation_score:.0f} < {self.config.multi_day_threshold}")
                score_gap = max(score_gap, self.config.multi_day_threshold - candidate.multi_day_continuation_score)
            if candidate.trap_risk > 80:
                reasons.append(MissedWinnerReason.TRAP_RISK_TOO_HIGH)
                blocking.append(f"trap_risk {candidate.trap_risk:.0f} > 80")
            if candidate.dilution_risk > 70:
                reasons.append(MissedWinnerReason.DILUTION_RISK_BLOCKED)
                blocking.append(f"dilution_risk {candidate.dilution_risk:.0f} > 70")
            if candidate.is_negative:
                reasons.append(MissedWinnerReason.NEGATIVE_CLASSIFIED)
                blocking.append("classified as negative catalyst")
            if candidate.is_vague and candidate.news_impact_score < 80:
                reasons.append(MissedWinnerReason.VAGUE_CLASSIFIED)
                blocking.append("vague PR blocked")
            if not self.config.telegram_enabled:
                reasons.append(MissedWinnerReason.TELEGRAM_DISABLED)
                blocking.append("telegram alerts disabled")

        else:
            # Alert was sent but wrong action
            if candidate.oracle_action == OracleAction.AVOID_TRAP:
                reasons.append(MissedWinnerReason.TRAP_RISK_TOO_HIGH)
                blocking.append("avoid_trap action prevented entry")

        # Build recommendation
        recommendation = self._generate_recommendation(candidate, reasons, moves)

        primary_reason = reasons[0].value if reasons else MissedWinnerReason.UNKNOWN.value

        return MissedWinnerRecord(
            id=str(uuid.uuid4())[:8],
            ticker=candidate.ticker,
            headline=candidate.headline,
            catalyst_category=candidate.catalyst_category,
            catalyst_sub_type=candidate.catalyst_sub_type,
            source=candidate.source,
            news_time=candidate.published_at or datetime.now(timezone.utc),
            detected_time=candidate.detected_at,
            alert_time=candidate.detected_at if alert_sent else None,
            price_at_news=candidate.current_price,
            price_at_alert_scan=candidate.current_price,
            max_price_after_news=prices.get("max_price"),
            price_1h=prices.get("price_1h"),
            price_same_day=prices.get("price_same_day"),
            price_2day=prices.get("price_2day"),
            price_5day=prices.get("price_5day"),
            move_1h_pct=moves.get("1h"),
            move_same_day_pct=moves.get("same_day"),
            move_2day_pct=moves.get("2day"),
            move_5day_pct=moves.get("5day"),
            missed=not alert_sent or candidate.oracle_action == OracleAction.AVOID_TRAP,
            missed_reasons=reasons,
            missed_reason=primary_reason,
            blocking_rule=" | ".join(blocking) if blocking else "unknown",
            score_gap=round(score_gap, 1),
            news_impact_score=candidate.news_impact_score,
            expected_return_score=candidate.expected_return_score,
            continuation_probability=candidate.continuation_probability,
            multi_day_score=candidate.multi_day_continuation_score,
            trap_risk=candidate.trap_risk,
            dilution_risk=candidate.dilution_risk,
            oracle_action=candidate.oracle_action,
            alert_sent_late=alert_sent and moves.get("same_day", 0) > 20,
            recommendation=recommendation,
            similar_historical_winners=self._count_similar_winners(candidate.catalyst_sub_type),
        )

    def _generate_recommendation(
        self,
        candidate: NewsMomentumCandidate,
        reasons: List[MissedWinnerReason],
        moves: dict,
    ) -> str:
        """Generate a learning recommendation from missed reasons."""
        parts = []

        for reason in reasons:
            if reason == MissedWinnerReason.NEWS_IMPACT_TOO_LOW:
                parts.append(
                    f"Lower alert threshold for {candidate.catalyst_sub_type.value} "
                    f"catalysts (score was {candidate.news_impact_score:.0f})."
                )
            elif reason == MissedWinnerReason.EXPECTED_RETURN_TOO_LOW:
                parts.append(
                    f"Increase expected-return weight for {candidate.catalyst_sub_type.value} "
                    f"and low-float setups."
                )
            elif reason == MissedWinnerReason.CONTINUATION_TOO_LOW:
                parts.append(
                    f"Raise continuation probability base for {candidate.catalyst_sub_type.value}."
                )
            elif reason == MissedWinnerReason.TRAP_RISK_TOO_HIGH:
                parts.append(
                    f"Reduce trap-risk penalty for {candidate.catalyst_sub_type.value} "
                    f"when news impact > 60."
                )
            elif reason == MissedWinnerReason.DILUTION_RISK_BLOCKED:
                parts.append(
                    f"Review dilution scoring — no offering detected in headline."
                )
            elif reason == MissedWinnerReason.NEGATIVE_CLASSIFIED:
                parts.append(
                    f"Improve headline classification for {candidate.ticker} — "
                    f"news was positive but flagged negative."
                )
            elif reason == MissedWinnerReason.VAGUE_CLASSIFIED:
                parts.append(
                    f"Re-evaluate vague-PR filter for {candidate.catalyst_sub_type.value}."
                )
            elif reason == MissedWinnerReason.VOLUME_CONFIRMATION_MISSED:
                parts.append(
                    f"Allow alert before full volume confirmation if news impact > 75."
                )
            elif reason == MissedWinnerReason.PRICE_FILTER_EXCLUDED:
                parts.append(
                    f"Consider expanding price filter — winner was outside range."
                )

        # Shadow adjustment advice
        if len(self._records) >= MIN_TOTAL_OUTCOMES_FOR_GLOBAL_ADJUSTMENT:
            parts.append(
                "Global threshold adjustment available — apply in shadow mode."
            )

        catalyst_records = [r for r in self._records if r.catalyst_sub_type == candidate.catalyst_sub_type]
        if len(catalyst_records) >= MIN_MISSED_FOR_CATALYST_ADJUSTMENT:
            parts.append(
                f"30+ missed {candidate.catalyst_sub_type.value} cases — "
                f"catalyst-specific weight adjustment recommended."
            )

        return " ".join(parts) if parts else "No specific recommendation."

    def _count_similar_winners(self, catalyst_type: CatalystSubType) -> int:
        """Count how many similar catalysts were missed winners."""
        return sum(
            1 for r in self._records
            if r.catalyst_sub_type == catalyst_type and r.missed
        )

    # ── Shadow Adjustments ────────────────────────────────────────────────────

    def get_shadow_adjustments(self, catalyst_type: CatalystSubType) -> dict:
        """Get shadow score adjustments for a catalyst type."""
        key = catalyst_type.value
        return self._shadow_adjustments.get(key, {
            "news_impact_boost": 0.0,
            "expected_return_boost": 0.0,
            "continuation_boost": 0.0,
            "trap_risk_reduction": 0.0,
            "dilution_risk_reduction": 0.0,
            "applied_at": None,
            "confidence": 0.0,
        })

    def apply_shadow_adjustment(self, catalyst_type: CatalystSubType) -> bool:
        """Apply a shadow adjustment based on missed winner data."""
        missed_for_cat = [r for r in self._records if r.catalyst_sub_type == catalyst_type and r.missed]
        if len(missed_for_cat) < MIN_MISSED_FOR_CATALYST_ADJUSTMENT:
            return False

        # Calculate average score gaps
        avg_impact_gap = sum(r.score_gap for r in missed_for_cat if MissedWinnerReason.NEWS_IMPACT_TOO_LOW in r.missed_reasons) / max(1, sum(1 for r in missed_for_cat if MissedWinnerReason.NEWS_IMPACT_TOO_LOW in r.missed_reasons))
        avg_cont_gap = sum(r.score_gap for r in missed_for_cat if MissedWinnerReason.CONTINUATION_TOO_LOW in r.missed_reasons) / max(1, sum(1 for r in missed_for_cat if MissedWinnerReason.CONTINUATION_TOO_LOW in r.missed_reasons))
        avg_trap = sum(r.trap_risk for r in missed_for_cat) / len(missed_for_cat)

        self._shadow_adjustments[catalyst_type.value] = {
            "news_impact_boost": round(min(avg_impact_gap * 0.5, 15.0), 1),
            "expected_return_boost": round(min(avg_impact_gap * 0.4, 12.0), 1),
            "continuation_boost": round(min(avg_cont_gap * 0.5, 10.0), 1),
            "trap_risk_reduction": round(min(max(avg_trap - 50, 0) * 0.3, 15.0), 1),
            "dilution_risk_reduction": 0.0,
            "applied_at": datetime.now(timezone.utc).isoformat(),
            "confidence": round(min(len(missed_for_cat) / MIN_MISSED_FOR_CATALYST_ADJUSTMENT * 100, 100), 1),
            "sample_size": len(missed_for_cat),
        }
        self._persist_shadow()

        # Mark records as shadow applied
        for r in missed_for_cat:
            if not r.shadow_adjustment_applied:
                r.shadow_adjustment_applied = True
                r.status = "shadow_applied"
        self._persist()

        logger.info(
            "MissedLearning: shadow adjustment applied for %s (impact+%s, cont+%s, trap-%s)",
            catalyst_type.value,
            self._shadow_adjustments[catalyst_type.value]["news_impact_boost"],
            self._shadow_adjustments[catalyst_type.value]["continuation_boost"],
            self._shadow_adjustments[catalyst_type.value]["trap_risk_reduction"],
        )
        return True

    # ── Report ───────────────────────────────────────────────────────────────

    def get_report(self) -> MissedWinnerLearningReport:
        """Generate a summary report of missed winner learning."""
        missed = [r for r in self._records if r.missed]
        alerted = [r for r in self._records if not r.missed]

        by_reason: Dict[str, int] = {}
        by_catalyst: Dict[str, int] = {}
        for r in missed:
            for reason in r.missed_reasons:
                by_reason[reason.value] = by_reason.get(reason.value, 0) + 1
            cat = r.catalyst_sub_type.value
            by_catalyst[cat] = by_catalyst.get(cat, 0) + 1

        avg_move_missed = sum(r.move_same_day_pct or 0 for r in missed) / max(1, len(missed))
        avg_move_alerted = sum(r.move_same_day_pct or 0 for r in alerted) / max(1, len(alerted))

        top_movers = sorted(missed, key=lambda x: x.move_same_day_pct or 0, reverse=True)[:10]

        return MissedWinnerLearningReport(
            total_missed=len(missed),
            total_detected=len(self._records),
            by_reason=by_reason,
            by_catalyst=by_catalyst,
            avg_move_missed=round(avg_move_missed, 1),
            avg_move_alerted=round(avg_move_alerted, 1),
            recommendations_pending=sum(1 for r in missed if r.status == "pending"),
            recommendations_applied=sum(1 for r in missed if r.status == "approved"),
            shadow_adjustments_active=len(self._shadow_adjustments),
            top_missed_movers=[
                {
                    "ticker": r.ticker,
                    "headline": r.headline[:60],
                    "move": r.move_same_day_pct,
                    "reason": r.missed_reason,
                    "blocking_rule": r.blocking_rule,
                }
                for r in top_movers
            ],
            recent_missed=sorted(
                [r for r in missed if r.status == "pending"],
                key=lambda x: x.created_at,
                reverse=True,
            )[:20],
        )

    def get_missed_winners(self, limit: int = 100) -> List[MissedWinnerRecord]:
        """Get all missed winner records."""
        missed = [r for r in self._records if r.missed]
        return sorted(missed, key=lambda x: x.created_at, reverse=True)[:limit]

    def get_record(self, record_id: str) -> Optional[MissedWinnerRecord]:
        """Get a specific missed winner record by ID."""
        return next((r for r in self._records if r.id == record_id), None)

    def update_status(self, record_id: str, status: str) -> bool:
        """Update the status of a missed winner record."""
        record = self.get_record(record_id)
        if not record:
            return False
        record.status = status
        record.resolved_at = datetime.now(timezone.utc)
        self._persist()
        return True

    # ── Admin Alert Formatting ────────────────────────────────────────────────

    def format_admin_alert(self, record: MissedWinnerRecord) -> str:
        """Format a missed winner for admin Telegram notification.
        IMPORTANT: any field that may contain `<`, `>`, or `&` must be HTML-escaped
        before being inlined — otherwise Telegram returns 400 'can't parse entities'.
        """
        from html import escape as _esc

        def e(v: object) -> str:
            return _esc(str(v) if v is not None else "")

        return (
            "<b>🧠 MISSED WINNER LEARNING EVENT</b>\n\n"
            f"<b>Ticker:</b> {e(record.ticker)}\n"
            f"<b>Headline:</b> {e(record.headline[:120])}\n"
            f"<b>Catalyst:</b> {e(record.catalyst_sub_type.value)}\n\n"
            f"<b>📈 Move After News:</b>\n"
            f"  1h: {e(record.move_1h_pct or 'N/A')}%\n"
            f"  Same Day: {e(record.move_same_day_pct or 'N/A')}%\n"
            f"  2-Day: {e(record.move_2day_pct or 'N/A')}%\n"
            f"  5-Day: {e(record.move_5day_pct or 'N/A')}%\n\n"
            f"<b>❌ No Alert Reason:</b> {e(record.missed_reason.replace('_', ' '))}\n"
            f"<b>🚫 Blocking Rule:</b> {e(record.blocking_rule)}\n"
            f"<b>📉 Score Gap:</b> {e(record.score_gap)}\n\n"
            f"<b>Scores at Scan:</b>\n"
            f"  Impact: {e(record.news_impact_score)}\n"
            f"  Expected Return: {e(record.expected_return_score)}\n"
            f"  Continuation: {e(record.continuation_probability)}%\n"
            f"  Trap Risk: {e(record.trap_risk)}\n\n"
            f"<b>💡 Recommended Fix:</b> {e(record.recommendation[:200])}\n\n"
            f"<i>Similar missed {e(record.catalyst_sub_type.value)} winners: {e(record.similar_historical_winners)}</i>"
        )
