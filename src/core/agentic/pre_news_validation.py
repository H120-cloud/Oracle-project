"""
Pre-News V2 — Live Paper Validation Tracker

PURELY OBSERVATIONAL — no new strategy logic, no new entry signals.
Tracks every PRE_NEWS_V2 handoff candidate from detection through resolution.

Resolution outcomes:
  WIN       — target_1 hit before stop/invalidation
  LOSS      — stop_level or invalidation hit before target
  BREAKEVEN — neither hit after 4h, price within ±2% of entry
  EXPIRED   — 24h tracking window closed without resolution
  CANCELLED — candidate deactivated / removed before resolution

Weekly reports: handoff count, alert count, win rate, false alert rate,
average MFE/MAE, best/worst anomaly types, best timing stages,
missed runners, blocked-but-ran cases.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

from src.utils.atomic_json import save_json_file, load_json_file

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

from src.utils.data_paths import AGENTIC_DATA_DIR as DATA_DIR
VALIDATION_FILE = DATA_DIR / "pre_news_validation.json"
WEEKLY_REPORTS_DIR = DATA_DIR / "validation_reports"

# ── Resolution Constants ────────────────────────────────────────────────────────

TRACKING_WINDOW_HOURS = 24      # How long to watch a candidate after handoff
BREAKEVEN_WINDOW_HOURS = 4     # After this, flat = breakeven
BREAKEVEN_PCT = 2.0            # Within ±2% = breakeven
TARGET_HIT_THRESHOLD_PCT = 1.0  # Must exceed target by 1% to count (avoids wicks)


def _ensure_dirs():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    WEEKLY_REPORTS_DIR.mkdir(parents=True, exist_ok=True)


def _week_key(dt: datetime) -> str:
    """ISO week key: YYYY-WNN."""
    iso = dt.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


# ── Data Models ─────────────────────────────────────────────────────────────────


class PreNewsValidationRecord(BaseModel):
    """Single observational record for a PRE_NEWS_V2 handoff candidate."""

    # ── Identity ────────────────────────────────────────────────────────────────
    record_id: str = Field(default_factory=lambda: f"pnv_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{id(datetime.now()) % 10000:04d}")
    ticker: str
    anomaly_detected_at: datetime
    handoff_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # ── Pre-News Snapshot (at handoff) ────────────────────────────────────────
    smart_money_score: float = 0.0
    suspicion_score: float = 0.0
    anomaly_type: str = ""
    timing_stage: str = ""
    buy_pressure_score: float = 0.0
    float_pressure_score: float = 0.0
    offering_risk_score: float = 0.0
    move_type_prediction: str = ""
    discovery_source: str = ""
    session_quality_score: float = 0.0
    confidence_decay_factor: float = 1.0
    late_detection_flag: bool = False

    # ── Agentic Snapshot (at handoff) ─────────────────────────────────────────
    entry_timing_state: Optional[str] = None
    entry_zone_low: Optional[float] = None
    entry_zone_high: Optional[float] = None
    stop_level: Optional[float] = None
    target_1: Optional[float] = None
    target_2: Optional[float] = None
    invalidation_level: Optional[float] = None
    final_probability: float = 0.0
    agentic_alertable: bool = False

    # ── Alert Tracking ──────────────────────────────────────────────────────────
    telegram_alert_sent: bool = False
    alert_sent_at: Optional[datetime] = None

    # ── Price Tracking (updated periodically) ───────────────────────────────────
    entry_price: Optional[float] = None
    peak_price: Optional[float] = None
    trough_price: Optional[float] = None
    exit_price: Optional[float] = None
    mfe_pct: Optional[float] = None      # max favorable excursion %
    mae_pct: Optional[float] = None      # max adverse excursion %
    last_checked_price: Optional[float] = None
    last_checked_at: Optional[datetime] = None

    # ── Hit Tracking ────────────────────────────────────────────────────────────
    target_hit: bool = False
    target_hit_at: Optional[datetime] = None
    stop_hit: bool = False
    stop_hit_at: Optional[datetime] = None
    invalidation_hit: bool = False
    invalidation_hit_at: Optional[datetime] = None

    # ── News Tracking ───────────────────────────────────────────────────────────
    news_appeared: bool = False
    news_appeared_at: Optional[datetime] = None
    time_to_news_minutes: Optional[float] = None
    news_headline: Optional[str] = None

    # ── Resolution ──────────────────────────────────────────────────────────────
    outcome_label: str = "OPEN"  # OPEN | WIN | LOSS | BREAKEVEN | EXPIRED | CANCELLED
    outcome_resolved_at: Optional[datetime] = None
    outcome_reason: str = ""

    # ── Weekly bucket ───────────────────────────────────────────────────────────
    week_key: str = ""

    def is_resolved(self) -> bool:
        return self.outcome_label in ("WIN", "LOSS", "BREAKEVEN", "EXPIRED", "CANCELLED")

    def is_open(self) -> bool:
        return self.outcome_label == "OPEN"

    def is_alerted(self) -> bool:
        return self.telegram_alert_sent

    def age_hours(self, now: Optional[datetime] = None) -> float:
        if now is None:
            now = datetime.now(timezone.utc)
        return (now - self.handoff_at).total_seconds() / 3600.0


class WeeklyReport(BaseModel):
    """Aggregated statistics for one validation week."""

    week_key: str
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # Counts
    total_handoffs: int = 0
    alerted_count: int = 0
    non_alerted_count: int = 0
    win_count: int = 0
    loss_count: int = 0
    breakeven_count: int = 0
    expired_count: int = 0
    cancelled_count: int = 0
    still_open_count: int = 0

    # Rates
    win_rate_pct: Optional[float] = None       # wins / (wins + losses)
    false_alert_rate_pct: Optional[float] = None  # losses / alerted
    alert_rate_pct: Optional[float] = None      # alerted / total handoffs

    # Performance
    avg_mfe_pct: Optional[float] = None
    avg_mae_pct: Optional[float] = None
    avg_mfe_alerted: Optional[float] = None
    avg_mfe_non_alerted: Optional[float] = None

    # By anomaly type
    by_anomaly_type: dict = Field(default_factory=dict)
    # By timing stage
    by_timing_stage: dict = Field(default_factory=dict)
    # By move type
    by_move_type: dict = Field(default_factory=dict)

    # Missed opportunities
    missed_runners: list[dict] = Field(default_factory=list)  # alerted=False, MFE > 10%
    blocked_but_ran: list[dict] = Field(default_factory=list)  # agentic_alertable=False, MFE > 5%

    # News conversion
    news_appeared_count: int = 0
    news_appeared_rate_pct: Optional[float] = None
    avg_time_to_news_minutes: Optional[float] = None

    # Smart money distribution
    avg_smart_money_score: Optional[float] = None
    avg_smart_money_winners: Optional[float] = None
    avg_smart_money_losers: Optional[float] = None

    # Summary text
    summary: str = ""


# ── Validation Tracker ────────────────────────────────────────────────────────


class PreNewsValidationTracker:
    """
    Observational tracker for PRE_NEWS_V2 handoff candidates.
    Zero strategy changes — only records what happens.
    """

    def __init__(self):
        _ensure_dirs()
        self._records: list[PreNewsValidationRecord] = []
        self._load()

    def _find_open_handoff(self, ticker: str, detected_at: datetime) -> Optional[PreNewsValidationRecord]:
        for record in reversed(self._records):
            if not record.is_open():
                continue
            if record.ticker != ticker:
                continue
            if record.anomaly_detected_at == detected_at:
                return record
        return None

    # ── Recording ────────────────────────────────────────────────────────────

    def record_handoff(
        self,
        anomaly,
        agentic_candidate,
        telegram_alert_sent: bool = False,
        alert_sent_at: Optional[datetime] = None,
    ) -> PreNewsValidationRecord:
        """
        Record a new PRE_NEWS_V2 handoff candidate. Called from orchestrator.
        Returns the created record.
        """
        from src.core.agentic.pre_news_detector import PreNewsDetector

        record = PreNewsValidationRecord(
            ticker=anomaly.ticker,
            anomaly_detected_at=anomaly.detected_at,
            handoff_at=datetime.now(timezone.utc),

            # Pre-News V2 fields
            smart_money_score=anomaly.smart_money_score,
            suspicion_score=anomaly.pre_news_suspicion_score,
            anomaly_type=anomaly.anomaly_type.value,
            timing_stage=anomaly.timing_stage.value,
            buy_pressure_score=anomaly.buy_pressure_score,
            float_pressure_score=anomaly.float_pressure_score,
            offering_risk_score=anomaly.offering_risk_score,
            move_type_prediction=anomaly.move_type_prediction.value,
            discovery_source=anomaly.discovery_source,
            session_quality_score=anomaly.session_quality_score,
            confidence_decay_factor=anomaly.confidence_decay_factor,
            late_detection_flag=anomaly.late_detection_flag,

            # Agentic fields
            entry_timing_state=(
                agentic_candidate.entry_timing.timing_state.value
                if agentic_candidate.entry_timing and agentic_candidate.entry_timing.timing_state
                else None
            ),
            entry_zone_low=agentic_candidate.entry_timing.entry_zone_low if agentic_candidate.entry_timing else None,
            entry_zone_high=agentic_candidate.entry_timing.entry_zone_high if agentic_candidate.entry_timing else None,
            stop_level=agentic_candidate.entry_timing.stop_level if agentic_candidate.entry_timing else None,
            target_1=agentic_candidate.entry_timing.target_1 if agentic_candidate.entry_timing else None,
            target_2=agentic_candidate.entry_timing.target_2 if agentic_candidate.entry_timing else None,
            invalidation_level=agentic_candidate.entry_timing.invalidation_level if agentic_candidate.entry_timing else None,
            final_probability=agentic_candidate.final_probability,
            agentic_alertable=agentic_candidate.alertable,

            # Alert tracking
            telegram_alert_sent=telegram_alert_sent,
            alert_sent_at=alert_sent_at,

            # Price snapshot
            entry_price=agentic_candidate.last_price or anomaly.price,
            last_checked_price=agentic_candidate.last_price or anomaly.price,
            last_checked_at=datetime.now(timezone.utc),

            week_key=_week_key(datetime.now(timezone.utc)),
        )

        existing = self._find_open_handoff(record.ticker, record.anomaly_detected_at)
        if existing is not None:
            alert_was_sent = existing.telegram_alert_sent
            alert_sent_at_was = existing.alert_sent_at
            update_fields = record.model_dump(exclude={"record_id", "handoff_at"})
            for field, value in update_fields.items():
                setattr(existing, field, value)
            if alert_was_sent and not record.telegram_alert_sent:
                existing.telegram_alert_sent = True
                existing.alert_sent_at = alert_sent_at_was
            self._persist()
            logger.info(
                "PreNewsValidation: updated handoff %s %s (smart=%.0f suspicion=%.0f alertable=%s alerted=%s)",
                existing.record_id, existing.ticker,
                existing.smart_money_score, existing.suspicion_score,
                existing.agentic_alertable, existing.telegram_alert_sent,
            )
            return existing

        self._records.append(record)
        self._persist()
        logger.info(
            "PreNewsValidation: recorded handoff %s %s (smart=%.0f suspicion=%.0f alertable=%s alerted=%s)",
            record.record_id, record.ticker,
            record.smart_money_score, record.suspicion_score,
            record.agentic_alertable, record.telegram_alert_sent,
        )
        return record

    def record_alert(self, ticker: str, alert_sent_at: Optional[datetime] = None):
        """Mark that a Telegram alert was sent for an existing record."""
        for r in reversed(self._records):
            if r.ticker == ticker and r.is_open() and not r.telegram_alert_sent:
                r.telegram_alert_sent = True
                r.alert_sent_at = alert_sent_at or datetime.now(timezone.utc)
                self._persist()
                logger.info("PreNewsValidation: alert recorded for %s", ticker)
                return

    def record_news_appeared(self, ticker: str, headline: Optional[str] = None, news_at: Optional[datetime] = None):
        """Mark that news appeared for a candidate."""
        now = news_at or datetime.now(timezone.utc)
        for r in reversed(self._records):
            if r.ticker == ticker and not r.news_appeared:
                r.news_appeared = True
                r.news_appeared_at = now
                r.news_headline = headline
                if r.anomaly_detected_at:
                    r.time_to_news_minutes = round((now - r.anomaly_detected_at).total_seconds() / 60, 1)
                self._persist()
                logger.info("PreNewsValidation: news appeared for %s (+%.0f min)", ticker, r.time_to_news_minutes or 0)
                return

    # ── Price Tracking ───────────────────────────────────────────────────────

    def update_prices(self, price_map: dict[str, float], now: Optional[datetime] = None):
        """
        Update all OPEN records with latest prices.
        Checks target / stop / invalidation hits.
        price_map: {ticker: current_price}
        """
        if now is None:
            now = datetime.now(timezone.utc)

        updated = 0
        for r in self._records:
            if not r.is_open():
                continue
            if r.ticker not in price_map:
                continue

            price = price_map[r.ticker]
            r.last_checked_price = price
            r.last_checked_at = now
            updated += 1

            if r.entry_price is None:
                r.entry_price = price

            # Update peak / trough
            if r.peak_price is None or price > r.peak_price:
                r.peak_price = price
            if r.trough_price is None or price < r.trough_price:
                r.trough_price = price

            # Compute MFE / MAE
            if r.entry_price and r.entry_price > 0:
                r.mfe_pct = max(0.0, ((r.peak_price - r.entry_price) / r.entry_price) * 100)
                r.mae_pct = max(0.0, ((r.entry_price - r.trough_price) / r.entry_price) * 100)

            # Check target hit (must exceed by threshold to avoid wicks)
            if not r.target_hit and r.target_1 and r.entry_price:
                target_pct = (r.target_1 - r.entry_price) / r.entry_price * 100
                actual_pct = (price - r.entry_price) / r.entry_price * 100
                if actual_pct >= target_pct + TARGET_HIT_THRESHOLD_PCT:
                    r.target_hit = True
                    r.target_hit_at = now
                    logger.info("PreNewsValidation: %s TARGET HIT at %.2f (target_1=%.2f)", r.ticker, price, r.target_1)

            # Check stop hit
            if not r.stop_hit and r.stop_level and price <= r.stop_level:
                r.stop_hit = True
                r.stop_hit_at = now
                logger.info("PreNewsValidation: %s STOP HIT at %.2f (stop=%.2f)", r.ticker, price, r.stop_level)

            # Check invalidation hit
            if not r.invalidation_hit and r.invalidation_level and price <= r.invalidation_level:
                r.invalidation_hit = True
                r.invalidation_hit_at = now
                logger.info("PreNewsValidation: %s INVALIDATION at %.2f", r.ticker, price)

        if updated:
            self._persist()

    # ── Resolution ───────────────────────────────────────────────────────────

    def resolve_all(self, now: Optional[datetime] = None):
        """
        Resolve all OPEN records that meet resolution criteria.
        Should be called periodically (e.g. every 15 min).
        """
        if now is None:
            now = datetime.now(timezone.utc)

        resolved = 0
        for r in self._records:
            if not r.is_open():
                continue

            outcome, reason = self._determine_outcome(r, now)
            if outcome:
                r.outcome_label = outcome
                r.outcome_resolved_at = now
                r.outcome_reason = reason
                r.exit_price = r.last_checked_price
                resolved += 1
                logger.info(
                    "PreNewsValidation: %s resolved as %s (reason: %s) mfe=%.1f%% mae=%.1f%%",
                    r.ticker, outcome, reason,
                    r.mfe_pct or 0, r.mae_pct or 0,
                )

        if resolved:
            self._persist()
        return resolved

    def _determine_outcome(self, r: PreNewsValidationRecord, now: datetime) -> tuple[Optional[str], str]:
        """
        Determine if this record should be resolved now.
        Returns (outcome_label, reason) or (None, "") if still open.
        """
        age = r.age_hours(now)

        # CANCELLED: candidate was removed / deactivated (handled externally)
        # Caller should call resolve_cancelled() explicitly.

        # WIN: target hit before stop/invalidation
        if r.target_hit and not r.stop_hit and not r.invalidation_hit:
            return "WIN", f"Target hit at {r.target_hit_at.isoformat()}"

        # LOSS: stop or invalidation hit before target
        if (r.stop_hit or r.invalidation_hit) and not r.target_hit:
            hit = "stop" if r.stop_hit else "invalidation"
            return "LOSS", f"{hit} hit"

        # If both target AND stop hit, whichever came first wins
        if r.target_hit and (r.stop_hit or r.invalidation_hit):
            t_hit = r.target_hit_at or now
            s_hit = r.stop_hit_at or r.invalidation_hit_at or now
            if t_hit <= s_hit:
                return "WIN", "Target hit before stop"
            else:
                return "LOSS", "Stop hit before target"

        # A record only has real price history if update_prices ran at least
        # once (which always sets peak_price). Without that, last_checked_price
        # is just the handoff snapshot == entry_price, so the BREAKEVEN branch
        # below would fire at a fake 0.0% and inject meaningless "flat" outcomes
        # into the win-rate stats — making the categorisation impossible to
        # evaluate honestly. Treat never-tracked records as no-data EXPIRED.
        price_tracked = r.peak_price is not None

        # BREAKEVEN: after 4h, genuinely flat (within ±2%), no hits
        if price_tracked and age >= BREAKEVEN_WINDOW_HOURS:
            if r.entry_price and r.last_checked_price:
                pct = (r.last_checked_price - r.entry_price) / r.entry_price * 100
                if abs(pct) <= BREAKEVEN_PCT:
                    return "BREAKEVEN", f"Flat after {age:.1f}h ({pct:+.1f}%)"

        # EXPIRED: 24h window closed without resolution
        if age >= TRACKING_WINDOW_HOURS:
            if not price_tracked:
                return "EXPIRED", f"No price data captured in {age:.1f}h window"
            return "EXPIRED", f"Tracking window closed after {age:.1f}h"

        return None, ""

    def resolve_cancelled(self, ticker: str, reason: str = "candidate deactivated"):
        """Mark a candidate as cancelled (e.g. orchestrator deactivated it)."""
        for r in reversed(self._records):
            if r.ticker == ticker and r.is_open():
                r.outcome_label = "CANCELLED"
                r.outcome_resolved_at = datetime.now(timezone.utc)
                r.outcome_reason = reason
                r.exit_price = r.last_checked_price
                self._persist()
                logger.info("PreNewsValidation: %s CANCELLED (%s)", ticker, reason)
                return

    # ── Weekly Report ───────────────────────────────────────────────────────

    def generate_weekly_report(self, week_key: Optional[str] = None) -> WeeklyReport:
        """Generate a WeeklyReport for the specified week (or current week)."""
        _ensure_dirs()
        if week_key is None:
            week_key = _week_key(datetime.now(timezone.utc))

        records = [r for r in self._records if r.week_key == week_key]

        # Counts
        total = len(records)
        alerted = [r for r in records if r.telegram_alert_sent]
        non_alerted = [r for r in records if not r.telegram_alert_sent]
        wins = [r for r in records if r.outcome_label == "WIN"]
        losses = [r for r in records if r.outcome_label == "LOSS"]
        breakevens = [r for r in records if r.outcome_label == "BREAKEVEN"]
        expired = [r for r in records if r.outcome_label == "EXPIRED"]
        cancelled = [r for r in records if r.outcome_label == "CANCELLED"]
        open_records = [r for r in records if r.outcome_label == "OPEN"]

        # Rates
        win_rate = len(wins) / (len(wins) + len(losses)) * 100 if (len(wins) + len(losses)) > 0 else None
        false_alert_rate = len(losses) / len(alerted) * 100 if alerted else None
        alert_rate = len(alerted) / total * 100 if total > 0 else None

        # Performance
        def _avg_mfe(recs):
            vals = [r.mfe_pct for r in recs if r.mfe_pct is not None]
            return sum(vals) / len(vals) if vals else None

        def _avg_mae(recs):
            vals = [r.mae_pct for r in recs if r.mae_pct is not None]
            return sum(vals) / len(vals) if vals else None

        avg_mfe = _avg_mfe(records)
        avg_mae = _avg_mae(records)
        avg_mfe_alerted = _avg_mfe(alerted)
        avg_mfe_non_alerted = _avg_mfe(non_alerted)

        # By anomaly type
        by_type = defaultdict(lambda: {"count": 0, "wins": 0, "losses": 0, "avg_mfe": []})
        for r in records:
            bt = by_type[r.anomaly_type]
            bt["count"] += 1
            if r.outcome_label == "WIN":
                bt["wins"] += 1
            elif r.outcome_label == "LOSS":
                bt["losses"] += 1
            if r.mfe_pct is not None:
                bt["avg_mfe"].append(r.mfe_pct)

        # By timing stage
        by_stage = defaultdict(lambda: {"count": 0, "wins": 0, "losses": 0, "avg_mfe": []})
        for r in records:
            bs = by_stage[r.timing_stage]
            bs["count"] += 1
            if r.outcome_label == "WIN":
                bs["wins"] += 1
            elif r.outcome_label == "LOSS":
                bs["losses"] += 1
            if r.mfe_pct is not None:
                bs["avg_mfe"].append(r.mfe_pct)

        # By move type
        by_move = defaultdict(lambda: {"count": 0, "wins": 0, "losses": 0})
        for r in records:
            bm = by_move[r.move_type_prediction]
            bm["count"] += 1
            if r.outcome_label == "WIN":
                bm["wins"] += 1
            elif r.outcome_label == "LOSS":
                bm["losses"] += 1

        # Compute averages for nested dicts
        for d in (by_type, by_stage):
            for k, v in d.items():
                if v["avg_mfe"]:
                    v["avg_mfe"] = round(sum(v["avg_mfe"]) / len(v["avg_mfe"]), 2)

        # Missed runners: not alerted but MFE > 10%
        missed_runners = [
            {
                "ticker": r.ticker,
                "mfe_pct": round(r.mfe_pct, 1),
                "anomaly_type": r.anomaly_type,
                "smart_money": r.smart_money_score,
                "reason": "Not alerted but moved >10%",
            }
            for r in records
            if not r.telegram_alert_sent and r.mfe_pct and r.mfe_pct > 10
        ]

        # Blocked but ran: alertable=False but MFE > 5%
        blocked_but_ran = [
            {
                "ticker": r.ticker,
                "mfe_pct": round(r.mfe_pct, 1),
                "anomaly_type": r.anomaly_type,
                "smart_money": r.smart_money_score,
                "reason": "Blocked by rules but moved >5%",
            }
            for r in records
            if not r.agentic_alertable and r.mfe_pct and r.mfe_pct > 5
        ]

        # News conversion
        news_records = [r for r in records if r.news_appeared]
        news_rate = len(news_records) / total * 100 if total > 0 else None
        avg_ttn = (
            sum(r.time_to_news_minutes for r in news_records if r.time_to_news_minutes is not None) / len([r for r in news_records if r.time_to_news_minutes is not None])
            if news_records else None
        )

        # Smart money distribution
        sm_scores = [r.smart_money_score for r in records]
        avg_sm = sum(sm_scores) / len(sm_scores) if sm_scores else None
        avg_sm_winners = sum(r.smart_money_score for r in wins) / len(wins) if wins else None
        avg_sm_losers = sum(r.smart_money_score for r in losses) / len(losses) if losses else None

        # Build summary text
        summary_lines = [
            f"Pre-News V2 Validation Week {week_key}",
            f"  Handoffs: {total}  |  Alerted: {len(alerted)}  |  Open: {len(open_records)}",
        ]
        if win_rate is not None:
            summary_lines.append(f"  Win Rate: {win_rate:.1f}% ({len(wins)}W / {len(losses)}L)")
        if false_alert_rate is not None:
            summary_lines.append(f"  False Alert Rate: {false_alert_rate:.1f}%")
        if avg_mfe is not None and avg_mae is not None:
            summary_lines.append(f"  Avg MFE: {avg_mfe:.1f}%  |  Avg MAE: {avg_mae:.1f}%")
        elif avg_mfe is not None:
            summary_lines.append(f"  Avg MFE: {avg_mfe:.1f}%")
        if missed_runners:
            summary_lines.append(f"  Missed Runners: {len(missed_runners)}")
        if blocked_but_ran:
            summary_lines.append(f"  Blocked-but-Ran: {len(blocked_but_ran)}")

        report = WeeklyReport(
            week_key=week_key,
            total_handoffs=total,
            alerted_count=len(alerted),
            non_alerted_count=len(non_alerted),
            win_count=len(wins),
            loss_count=len(losses),
            breakeven_count=len(breakevens),
            expired_count=len(expired),
            cancelled_count=len(cancelled),
            still_open_count=len(open_records),
            win_rate_pct=round(win_rate, 1) if win_rate is not None else None,
            false_alert_rate_pct=round(false_alert_rate, 1) if false_alert_rate is not None else None,
            alert_rate_pct=round(alert_rate, 1) if alert_rate is not None else None,
            avg_mfe_pct=round(avg_mfe, 2) if avg_mfe is not None else None,
            avg_mae_pct=round(avg_mae, 2) if avg_mae is not None else None,
            avg_mfe_alerted=round(avg_mfe_alerted, 2) if avg_mfe_alerted is not None else None,
            avg_mfe_non_alerted=round(avg_mfe_non_alerted, 2) if avg_mfe_non_alerted is not None else None,
            by_anomaly_type=dict(by_type),
            by_timing_stage=dict(by_stage),
            by_move_type=dict(by_move),
            missed_runners=missed_runners,
            blocked_but_ran=blocked_but_ran,
            news_appeared_count=len(news_records),
            news_appeared_rate_pct=round(news_rate, 1) if news_rate is not None else None,
            avg_time_to_news_minutes=round(avg_ttn, 1) if avg_ttn is not None else None,
            avg_smart_money_score=round(avg_sm, 1) if avg_sm is not None else None,
            avg_smart_money_winners=round(avg_sm_winners, 1) if avg_sm_winners is not None else None,
            avg_smart_money_losers=round(avg_sm_losers, 1) if avg_sm_losers is not None else None,
            summary="\n".join(summary_lines),
        )

        # Persist report
        report_path = WEEKLY_REPORTS_DIR / f"weekly_report_{week_key}.json"
        save_json_file(report_path, report.model_dump(mode="json"))
        logger.info("PreNewsValidation: weekly report generated for %s", week_key)
        return report

    def get_all_reports(self) -> list[WeeklyReport]:
        """Load all persisted weekly reports."""
        reports = []
        for p in sorted(WEEKLY_REPORTS_DIR.glob("weekly_report_*.json")):
            try:
                reports.append(WeeklyReport(**json.loads(p.read_text())))
            except Exception:
                continue
        return reports

    def get_open_records(self) -> list[PreNewsValidationRecord]:
        return [r for r in self._records if r.is_open()]

    def get_records_for_ticker(self, ticker: str) -> list[PreNewsValidationRecord]:
        return [r for r in self._records if r.ticker.upper() == ticker.upper()]

    # ── Persistence ──────────────────────────────────────────────────────────

    def _persist(self):
        data = [r.model_dump(mode="json") for r in self._records]
        save_json_file(VALIDATION_FILE, data)

    def _load(self):
        raw = load_json_file(VALIDATION_FILE, default=None)
        if raw is None:
            self._records = []
            return
        try:
            self._records = [PreNewsValidationRecord(**item) for item in raw]
            logger.info(
                "PreNewsValidation: loaded %d records (%d open)",
                len(self._records), len(self.get_open_records()),
            )
        except Exception as e:
            logger.warning("PreNewsValidation load failed: %s", e)
            self._records = []
