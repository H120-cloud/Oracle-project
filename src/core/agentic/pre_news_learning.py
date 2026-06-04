"""
Pre-News Volume Anomaly Detector — Learning Engine

Tracks anomaly outcomes, computes statistics, and generates
threshold/calibration recommendations. Does NOT auto-change
live rules — recommendations only.

Minimum samples required before any calibration:
  - 100 anomalies
  - 30 confirmed post-news matches
"""

import json
import logging
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

from src.utils.atomic_json import save_json_file, load_json_file

import yfinance as yf

from src.core.agentic.pre_news_models import (
    AnomalyType,
    MissedAnomalyClass,
    MoveType,
    NewsStatus,
    PreNewsAnomaly,
    PreNewsMissedReview,
    PreNewsOutcome,
    PriceBehaviour,
    SessionQuality,
    TimingStage,
)

logger = logging.getLogger(__name__)

DATA_DIR = Path("data/agentic")
OUTCOMES_FILE = DATA_DIR / "pre_news_outcomes.json"
MISSED_FILE = DATA_DIR / "pre_news_missed.json"

MIN_ANOMALIES_FOR_CALIBRATION = 100
MIN_NEWS_MATCHES_FOR_CALIBRATION = 30


def _ensure_dir():
    DATA_DIR.mkdir(parents=True, exist_ok=True)


class PreNewsLearningEngine:
    """
    Outcome tracking and recommendation engine for pre-news anomalies.

    Tracks:
      - anomaly → news conversion rate
      - anomaly → real move rate
      - anomaly → false pump rate
      - MFE / MAE after anomaly
      - Best RVOL thresholds
      - Best time-of-day windows
      - Best price behaviour types
    """

    def __init__(self):
        self.outcomes: list[PreNewsOutcome] = []
        self.missed_reviews: list[PreNewsMissedReview] = []
        _ensure_dir()
        self._load()

    # ── Record Outcome ────────────────────────────────────────────────────

    def record_outcome(
        self,
        anomaly: PreNewsAnomaly,
        peak_price: Optional[float] = None,
        exit_price: Optional[float] = None,
        time_to_peak_minutes: Optional[float] = None,
    ) -> PreNewsOutcome:
        """Record outcome for a completed anomaly (V2: captures full feature snapshot)."""
        entry = anomaly.price
        mfe = ((peak_price - entry) / entry * 100) if peak_price and entry > 0 else None
        mae = ((entry - exit_price) / entry * 100) if exit_price and entry > 0 else None

        # Did it turn into a real move?
        was_real = (mfe or 0) >= 5  # 5%+ move
        was_pump = (
            anomaly.anomaly_type == AnomalyType.SUSPICIOUS_PUMP_RISK
            or anomaly.move_type_prediction == MoveType.PUMP_AND_DUMP
            or ((mfe or 0) > 10 and (mae or 0) > 8)  # pumped then dumped
        )
        was_false = not was_real and not was_pump

        news_appeared = anomaly.news_status in (
            NewsStatus.NEWS_LAG_CONFIRMED,
            NewsStatus.NEWS_ALREADY_VISIBLE,
        )

        # V2 — classify actual move type retrospectively
        if was_pump:
            move_actual = MoveType.PUMP_AND_DUMP
        elif news_appeared and was_real:
            move_actual = MoveType.NEWS_BREAKOUT
        elif was_real and (mfe or 0) >= 15:
            move_actual = MoveType.LOW_FLOAT_SQUEEZE if (anomaly.float_shares or 1e12) < 20_000_000 else MoveType.MOMENTUM_CONTINUATION
        elif was_real:
            move_actual = MoveType.GRADUAL_ACCUMULATION
        else:
            move_actual = MoveType.UNKNOWN

        # V2 — failure vs continuation
        if was_real:
            foc = "continuation"
        elif was_false:
            foc = "failure"
        else:
            foc = "neutral"

        # V2 — news type classification (heuristic from headline)
        news_type = None
        headline = (anomaly.first_news_headline or "").lower()
        if headline:
            if any(k in headline for k in ("earnings", "eps", "revenue", "q1", "q2", "q3", "q4")):
                news_type = "earnings"
            elif any(k in headline for k in ("fda", "approval", "trial", "phase", "clinical")):
                news_type = "fda"
            elif any(k in headline for k in ("contract", "deal", "partnership", "agreement")):
                news_type = "contract"
            elif any(k in headline for k in ("sec", "8-k", "10-k", "10-q", "filing")):
                news_type = "sec_filing"
            elif any(k in headline for k in ("offering", "dilut", "s-3", "s-1")):
                news_type = "dilution"
            else:
                news_type = "other"

        outcome = PreNewsOutcome(
            anomaly_id=anomaly.id,
            ticker=anomaly.ticker,
            anomaly_type=anomaly.anomaly_type,
            suspicion_score=anomaly.pre_news_suspicion_score,
            price_behaviour=anomaly.price_behaviour.behaviour,
            news_status=anomaly.news_status,
            news_appeared=news_appeared,
            news_appeared_minutes_after=anomaly.time_gap_minutes,
            entry_price=entry,
            peak_price=peak_price,
            exit_price=exit_price,
            max_favorable_excursion_pct=round(mfe, 2) if mfe else None,
            max_adverse_excursion_pct=round(mae, 2) if mae else None,
            was_real_move=was_real,
            was_pump=was_pump,
            was_false_alarm=was_false,
            # V2 fields
            time_to_peak_minutes=time_to_peak_minutes,
            move_type_actual=move_actual,
            news_type_classification=news_type,
            failure_or_continuation=foc,
            smart_money_score_at_detection=anomaly.smart_money_score,
            buy_pressure_score_at_detection=anomaly.buy_pressure_score,
            float_pressure_score_at_detection=anomaly.float_pressure_score,
            timing_stage_at_detection=anomaly.timing_stage,
            rvol_at_detection=anomaly.volume_metrics.rvol_current,
            float_shares_at_detection=anomaly.float_shares,
            session_at_detection=anomaly.session,
        )
        self.outcomes.append(outcome)
        self._save()
        return outcome

    # ── Missed Opportunity Review ─────────────────────────────────────────

    def review_missed(
        self,
        anomalies: dict[str, PreNewsAnomaly],
    ) -> list[PreNewsMissedReview]:
        """
        EOD review: check today's big movers against detected anomalies.
        Uses Finviz top gainers to find what we may have missed.
        """
        from src.core.agentic.finviz_universe import fetch_finviz_top_gainers_snapshot

        reviews = []
        try:
            gainers = fetch_finviz_top_gainers_snapshot(max_results=30)
        except Exception as e:
            logger.warning("PreNewsLearning: missed review scan failed: %s", e)
            return []

        for stock in gainers:
            ticker = stock.ticker
            change_pct = stock.change_percent or 0
            rvol = stock.rvol

            if abs(change_pct) < 10:
                continue  # Only review big movers

            flagged = ticker in anomalies
            existing = anomalies.get(ticker)

            if flagged and existing:
                lead_time = None
                if existing.detected_at:
                    lead_time = round(
                        (datetime.now(timezone.utc) - existing.detected_at).total_seconds() / 60, 1
                    )
                classification = (
                    MissedAnomalyClass.CAUGHT_EARLY
                    if (lead_time or 0) > 30
                    else MissedAnomalyClass.CAUGHT_LATE
                )
                reason = f"Flagged with score {existing.pre_news_suspicion_score:.0f}, lead {lead_time:.0f}m"
            else:
                # Not flagged — why?
                if (rvol or 0) < 2:
                    classification = MissedAnomalyClass.MISSED_NO_VOLUME_SIGNAL
                    reason = f"RVOL only {rvol:.1f}x — below threshold"
                else:
                    classification = MissedAnomalyClass.MISSED_NOT_IN_UNIVERSE
                    reason = "Ticker not in scan universe"

            review = PreNewsMissedReview(
                ticker=ticker,
                change_pct=change_pct,
                rvol=rvol,
                classification=classification,
                flagged_by_detector=flagged,
                flag_lead_time_minutes=(
                    round((datetime.now(timezone.utc) - existing.detected_at).total_seconds() / 60, 1)
                    if flagged and existing and existing.detected_at
                    else None
                ),
                reason=reason,
            )
            reviews.append(review)

        self.missed_reviews.extend(reviews)
        self._save()
        return reviews

    # ── Statistics ────────────────────────────────────────────────────────

    def get_stats(self) -> dict:
        """Compute learning statistics from all recorded outcomes."""
        total = len(self.outcomes)
        if total == 0:
            return {
                "total_outcomes": 0,
                "message": "No outcomes recorded yet",
                "calibration_ready": False,
            }

        news_confirmed = sum(1 for o in self.outcomes if o.news_appeared)
        real_moves = sum(1 for o in self.outcomes if o.was_real_move)
        pumps = sum(1 for o in self.outcomes if o.was_pump)
        false_alarms = sum(1 for o in self.outcomes if o.was_false_alarm)

        mfe_vals = [o.max_favorable_excursion_pct for o in self.outcomes if o.max_favorable_excursion_pct is not None]
        mae_vals = [o.max_adverse_excursion_pct for o in self.outcomes if o.max_adverse_excursion_pct is not None]
        news_gaps = [o.news_appeared_minutes_after for o in self.outcomes if o.news_appeared_minutes_after is not None]

        # By anomaly type
        by_type = defaultdict(lambda: {"count": 0, "real": 0, "pump": 0})
        for o in self.outcomes:
            by_type[o.anomaly_type.value]["count"] += 1
            if o.was_real_move:
                by_type[o.anomaly_type.value]["real"] += 1
            if o.was_pump:
                by_type[o.anomaly_type.value]["pump"] += 1

        # By price behaviour
        by_behaviour = defaultdict(lambda: {"count": 0, "real": 0})
        for o in self.outcomes:
            by_behaviour[o.price_behaviour.value]["count"] += 1
            if o.was_real_move:
                by_behaviour[o.price_behaviour.value]["real"] += 1

        calibration_ready = (
            total >= MIN_ANOMALIES_FOR_CALIBRATION
            and news_confirmed >= MIN_NEWS_MATCHES_FOR_CALIBRATION
        )

        # V2 — additional breakdowns
        by_move_type = defaultdict(lambda: {"count": 0, "real": 0, "pump": 0})
        for o in self.outcomes:
            mt = o.move_type_actual.value
            by_move_type[mt]["count"] += 1
            if o.was_real_move:
                by_move_type[mt]["real"] += 1
            if o.was_pump:
                by_move_type[mt]["pump"] += 1

        by_timing = defaultdict(lambda: {"count": 0, "real": 0})
        for o in self.outcomes:
            if o.timing_stage_at_detection is not None:
                ts = o.timing_stage_at_detection.value
                by_timing[ts]["count"] += 1
                if o.was_real_move:
                    by_timing[ts]["real"] += 1

        by_session = defaultdict(lambda: {"count": 0, "real": 0})
        for o in self.outcomes:
            if o.session_at_detection is not None:
                s = o.session_at_detection.value
                by_session[s]["count"] += 1
                if o.was_real_move:
                    by_session[s]["real"] += 1

        ttp_vals = [o.time_to_peak_minutes for o in self.outcomes if o.time_to_peak_minutes is not None]

        return {
            "total_outcomes": total,
            "news_conversion_rate": round(news_confirmed / total * 100, 1) if total else 0,
            "real_move_rate": round(real_moves / total * 100, 1) if total else 0,
            "pump_rate": round(pumps / total * 100, 1) if total else 0,
            "false_alarm_rate": round(false_alarms / total * 100, 1) if total else 0,
            "avg_mfe_pct": round(sum(mfe_vals) / len(mfe_vals), 2) if mfe_vals else None,
            "avg_mae_pct": round(sum(mae_vals) / len(mae_vals), 2) if mae_vals else None,
            "avg_news_gap_minutes": round(sum(news_gaps) / len(news_gaps), 1) if news_gaps else None,
            "by_anomaly_type": dict(by_type),
            "by_price_behaviour": dict(by_behaviour),
            # V2 breakdowns
            "by_move_type": dict(by_move_type),
            "by_timing_stage": dict(by_timing),
            "by_session": dict(by_session),
            "avg_time_to_peak_minutes": round(sum(ttp_vals) / len(ttp_vals), 1) if ttp_vals else None,
            "calibration_ready": calibration_ready,
            "samples_needed": max(0, MIN_ANOMALIES_FOR_CALIBRATION - total),
            "news_matches_needed": max(0, MIN_NEWS_MATCHES_FOR_CALIBRATION - news_confirmed),
        }

    def get_recommendations(self) -> list[str]:
        """
        Generate calibration recommendations from outcome data.
        Only available when calibration_ready is True.
        """
        stats = self.get_stats()
        if not stats.get("calibration_ready"):
            remaining = stats.get("samples_needed", "?")
            news_remaining = stats.get("news_matches_needed", "?")
            return [
                f"Need {remaining} more anomalies and {news_remaining} more news matches before calibration."
            ]

        recs = []

        # Compare anomaly types
        by_type = stats.get("by_anomaly_type", {})
        for atype, data in by_type.items():
            ct = data["count"]
            real = data["real"]
            pump = data["pump"]
            if ct >= 10:
                rate = real / ct * 100
                pump_rate = pump / ct * 100
                if rate < 20:
                    recs.append(f"{atype} has low real-move rate ({rate:.0f}%) — consider raising threshold")
                if pump_rate > 30:
                    recs.append(f"{atype} has high pump rate ({pump_rate:.0f}%) — add extra safety filters")
                if rate > 60:
                    recs.append(f"{atype} has strong signal ({rate:.0f}% real moves) — can lower threshold")

        # Compare price behaviours
        by_behaviour = stats.get("by_price_behaviour", {})
        for btype, data in by_behaviour.items():
            ct = data["count"]
            real = data["real"]
            if ct >= 10:
                rate = real / ct * 100
                if rate > 50:
                    recs.append(f"'{btype}' outperforms ({rate:.0f}% success) — prioritize this pattern")
                if rate < 15:
                    recs.append(f"'{btype}' underperforms ({rate:.0f}% success) — downweight or filter out")

        # MFE / MAE comparison
        avg_mfe = stats.get("avg_mfe_pct")
        avg_mae = stats.get("avg_mae_pct")
        if avg_mfe is not None and avg_mae is not None:
            if avg_mae > avg_mfe:
                recs.append("Average drawdown exceeds average gain — tighten entry criteria")
            if avg_mfe > 10:
                recs.append(f"Average MFE is {avg_mfe:.1f}% — entries are finding real moves")

        # News gap
        avg_gap = stats.get("avg_news_gap_minutes")
        if avg_gap is not None:
            recs.append(f"Average time before news: {avg_gap:.0f} minutes")

        if not recs:
            recs.append("Insufficient divergence in data for specific recommendations yet.")

        return recs

    # ── Persistence ───────────────────────────────────────────────────────

    def _save(self):
        _ensure_dir()
        data = {
            "outcomes": [o.model_dump(mode="json") for o in self.outcomes],
            "missed": [m.model_dump(mode="json") for m in self.missed_reviews],
        }
        save_json_file(OUTCOMES_FILE, data)

    def _load(self):
        raw = load_json_file(OUTCOMES_FILE, default=None)
        if raw is None:
            return
        try:
            self.outcomes = [PreNewsOutcome(**o) for o in raw.get("outcomes", [])]
            self.missed_reviews = [PreNewsMissedReview(**m) for m in raw.get("missed", [])]
            logger.info(
                "PreNewsLearning: loaded %d outcomes, %d missed reviews",
                len(self.outcomes), len(self.missed_reviews),
            )
        except Exception as e:
            logger.warning("PreNewsLearning load failed: %s", e)
