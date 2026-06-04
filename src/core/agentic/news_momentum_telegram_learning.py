"""
News Momentum Adaptive Telegram Learning System (V22)

Tracks every Telegram alert outcome and adapts alert thresholds
based on historical performance.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional

from src.core.agentic.news_momentum_models import (
    TelegramAlertRecord,
    TelegramAlertQuality,
    AlertOutcome,
    CatalystSubType,
    SessionType,
)
from src.utils.atomic_json import save_json_file, load_json_file

logger = logging.getLogger(__name__)

DATA_DIR = Path("data/agentic")
ALERTS_FILE = DATA_DIR / "news_momentum_telegram_alerts.json"

MIN_ALERTS_FOR_ADAPTATION = 100
MIN_PER_CATALYST = 30


def _ensure_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


class AdaptiveTelegramLearning:
    """Tracks and learns from Telegram alert outcomes."""

    def __init__(self):
        _ensure_dir()
        self._alerts: List[TelegramAlertRecord] = []
        self._by_catalyst: Dict[str, List[TelegramAlertRecord]] = defaultdict(list)
        self._load()

    # ── Persistence ───────────────────────────────────────────────────────────

    def _load(self) -> None:
        raw = load_json_file(ALERTS_FILE, default=None)
        if raw is None:
            return
        for item in raw:
            try:
                rec = TelegramAlertRecord(**item)
                self._alerts.append(rec)
                self._by_catalyst[rec.catalyst_type.value].append(rec)
            except Exception:
                pass
        logger.info("TelegramLearning: loaded %d alert records", len(self._alerts))

    def _save(self) -> None:
        data = [a.model_dump(mode="json") for a in self._alerts]
        save_json_file(ALERTS_FILE, data)

    # ── Recording ─────────────────────────────────────────────────────────────

    def record_alert(self, record: TelegramAlertRecord) -> None:
        self._alerts.append(record)
        self._by_catalyst[record.catalyst_type.value].append(record)
        self._save()

    def resolve_outcome(
        self,
        alert_id: str,
        price_15m: Optional[float] = None,
        price_1h: Optional[float] = None,
        price_4h: Optional[float] = None,
        next_day_open: Optional[float] = None,
        next_day_high: Optional[float] = None,
        next_day_close: Optional[float] = None,
        two_day_high: Optional[float] = None,
        five_day_high: Optional[float] = None,
    ) -> None:
        """Fill in outcome data for an alert."""
        for alert in self._alerts:
            if alert.alert_id == alert_id:
                alert.price_15m_later = price_15m
                alert.price_1h_later = price_1h
                alert.price_4h_later = price_4h
                alert.next_day_open = next_day_open
                alert.next_day_high = next_day_high
                alert.next_day_close = next_day_close
                alert.two_day_high = two_day_high
                alert.five_day_high = five_day_high
                alert.resolved_at = datetime.now(timezone.utc)

                # Compute MFE / MAE
                if alert.price_at_alert > 0:
                    highs = [h for h in [price_15m, price_1h, price_4h, next_day_high, two_day_high, five_day_high] if h]
                    lows = [l for l in [price_15m, price_1h, price_4h, next_day_close] if l]
                    if highs:
                        alert.mfe_pct = round(((max(highs) - alert.price_at_alert) / alert.price_at_alert) * 100, 2)
                    if lows:
                        alert.mae_pct = round(((alert.price_at_alert - min(lows)) / alert.price_at_alert) * 100, 2)

                # Classify outcome
                alert.outcome = self._classify_outcome(alert)
                self._save()
                logger.info("TelegramLearning: resolved alert %s as %s", alert_id, alert.outcome.value)
                return

    def _classify_outcome(self, alert: TelegramAlertRecord) -> AlertOutcome:
        # Calibrated to realistic news momentum behaviour. Premarket / open
        # session catalysts often deliver 5-15% before fading; treating any
        # <5% move as "no follow through" was too punishing and produced a
        # 10/100 quality score that crushed adaptive thresholds.
        mfe = alert.mfe_pct or 0.0
        mae = alert.mae_pct or 0.0
        move_pct = mfe

        if move_pct > 25:
            return AlertOutcome.GREAT_ALERT
        if move_pct > 10:
            return AlertOutcome.GOOD_ALERT
        if move_pct < 2 and mae > 8:
            return AlertOutcome.TRAP_ALERT
        if move_pct < 2:
            return AlertOutcome.NO_FOLLOW_THROUGH
        if mae > 15:
            return AlertOutcome.TRAP_ALERT
        return AlertOutcome.LATE_ALERT

    # ── Quality Metrics ─────────────────────────────────────────────────────

    def get_overall_quality(self) -> TelegramAlertQuality:
        """Compute overall alert quality statistics."""
        q = TelegramAlertQuality()
        resolved = [a for a in self._alerts if a.outcome is not None]
        if not resolved:
            return q

        q.total_alerts = len(resolved)
        counts = defaultdict(int)
        mfe_values = []
        mae_values = []

        for a in resolved:
            counts[a.outcome.value] += 1
            if a.mfe_pct is not None:
                mfe_values.append(a.mfe_pct)
            if a.mae_pct is not None:
                mae_values.append(a.mae_pct)

        q.great_alerts = counts.get(AlertOutcome.GREAT_ALERT.value, 0)
        q.good_alerts = counts.get(AlertOutcome.GOOD_ALERT.value, 0)
        q.late_alerts = counts.get(AlertOutcome.LATE_ALERT.value, 0)
        q.trap_alerts = counts.get(AlertOutcome.TRAP_ALERT.value, 0)
        q.no_follow_through = counts.get(AlertOutcome.NO_FOLLOW_THROUGH.value, 0)
        q.missed_runners = counts.get(AlertOutcome.MISSED_RUNNER.value, 0)

        if mfe_values:
            q.avg_mfe_pct = round(sum(mfe_values) / len(mfe_values), 2)
        if mae_values:
            q.avg_mae_pct = round(sum(mae_values) / len(mae_values), 2)

        # Quality score: weighted success rate
        great_weight = 2.0
        good_weight = 1.0
        late_weight = 0.0
        trap_weight = -2.0
        noft_weight = -1.0

        score = (
            q.great_alerts * great_weight +
            q.good_alerts * good_weight +
            q.late_alerts * late_weight +
            q.trap_alerts * trap_weight +
            q.no_follow_through * noft_weight
        )
        max_possible = q.total_alerts * great_weight
        if max_possible > 0:
            q.quality_score = round(max(0.0, (score / max_possible) * 100 + 50), 1)
        else:
            q.quality_score = 50.0

        return q

    def get_catalyst_quality(self, catalyst_type: CatalystSubType) -> Dict:
        """Get quality metrics for a specific catalyst type."""
        alerts = self._by_catalyst.get(catalyst_type.value, [])
        resolved = [a for a in alerts if a.outcome is not None]
        if len(resolved) < MIN_PER_CATALYST:
            return {"sample_size": len(resolved), "insufficient": True}

        counts = defaultdict(int)
        mfe_values = []
        for a in resolved:
            counts[a.outcome.value] += 1
            if a.mfe_pct:
                mfe_values.append(a.mfe_pct)

        total = len(resolved)
        return {
            "sample_size": total,
            "insufficient": False,
            "great_rate": round(counts[AlertOutcome.GREAT_ALERT.value] / total * 100, 1),
            "good_rate": round(counts[AlertOutcome.GOOD_ALERT.value] / total * 100, 1),
            "trap_rate": round(counts[AlertOutcome.TRAP_ALERT.value] / total * 100, 1),
            "noft_rate": round(counts[AlertOutcome.NO_FOLLOW_THROUGH.value] / total * 100, 1),
            "avg_mfe_pct": round(sum(mfe_values) / len(mfe_values), 2) if mfe_values else None,
            "quality_score": self._compute_quality_score(counts, total),
        }

    def _compute_quality_score(self, counts: Dict, total: int) -> float:
        score = (
            counts[AlertOutcome.GREAT_ALERT.value] * 2.0 +
            counts[AlertOutcome.GOOD_ALERT.value] * 1.0 +
            counts[AlertOutcome.LATE_ALERT.value] * 0.0 +
            counts[AlertOutcome.TRAP_ALERT.value] * -2.0 +
            counts[AlertOutcome.NO_FOLLOW_THROUGH.value] * -1.0
        )
        max_p = total * 2.0
        return round(max(0.0, (score / max_p) * 100 + 50), 1) if max_p > 0 else 50.0

    def get_adaptive_thresholds(self) -> Dict:
        """Return adjusted score thresholds based on historical performance."""
        base = {
            "news_impact": 70.0,
            "expected_return": 75.0,
            "continuation": 70.0,
            "multi_day": 70.0,
        }

        quality = self.get_overall_quality()
        if quality.total_alerts < MIN_ALERTS_FOR_ADAPTATION:
            return {**base, "adapted": False, "reason": "insufficient samples"}

        # If quality is high, can be more lenient; if low, be stricter
        quality_factor = (quality.quality_score - 50) / 50  # -1 to +1

        adapted = {
            "news_impact": round(max(50.0, min(85.0, base["news_impact"] - quality_factor * 10)), 1),
            "expected_return": round(max(55.0, min(90.0, base["expected_return"] - quality_factor * 10)), 1),
            "continuation": round(max(50.0, min(85.0, base["continuation"] - quality_factor * 10)), 1),
            "multi_day": round(max(50.0, min(85.0, base["multi_day"] - quality_factor * 10)), 1),
            "adapted": True,
            "quality_score": quality.quality_score,
        }
        return adapted

    def get_all_catalyst_stats(self) -> Dict[str, Dict]:
        """Return stats for all catalyst types with sufficient samples."""
        result = {}
        for cat_type in CatalystSubType:
            stats = self.get_catalyst_quality(cat_type)
            if not stats.get("insufficient", True):
                result[cat_type.value] = stats
        return result
