"""
News Momentum Catalyst Learning Engine (V22)

Automatically learns from historical outcomes to identify:
- best/worst catalyst types
- best sectors, floats, market caps
- best time-of-day setups
- highest trap catalysts
- best multi-day continuation catalysts
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional

from src.core.agentic.news_momentum_models import (
    CatalystLearningStats,
    CatalystSubType,
    CatalystCategory,
    SessionType,
)
from src.utils.atomic_json import save_json_file, load_json_file

logger = logging.getLogger(__name__)

from src.utils.data_paths import AGENTIC_DATA_DIR as DATA_DIR
CATALYST_STATS_FILE = DATA_DIR / "news_momentum_catalyst_stats.json"
OUTCOMES_FILE = DATA_DIR / "news_momentum_outcomes.json"

MIN_SAMPLES_FOR_STATS = 20


def _ensure_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


class NewsMomentumOutcome:
    """Lightweight outcome record for learning."""
    def __init__(self, data: dict):
        self.ticker = data.get("ticker", "")
        self.catalyst_type = data.get("catalyst_type", "")
        self.catalyst_category = data.get("catalyst_category", "")
        self.session = data.get("session", "")
        self.time_of_day = data.get("time_of_day", "")
        self.price_at_news = data.get("price_at_news", 0.0)
        self.max_move_pct = data.get("max_move_pct", 0.0)
        self.mae_pct = data.get("mae_pct", 0.0)
        self.continued = data.get("continued", False)
        self.faded = data.get("faded", False)
        self.trapped = data.get("trapped", False)
        self.multi_day = data.get("multi_day", False)
        self.gap_up_next = data.get("gap_up_next", False)
        self.float_category = data.get("float_category", "")
        self.market_cap_category = data.get("market_cap_category", "")
        self.price_bucket = data.get("price_bucket", "")


class CatalystLearningEngine:
    """Learns from historical catalyst outcomes."""

    def __init__(self):
        _ensure_dir()
        self._outcomes: List[NewsMomentumOutcome] = []
        self._load()

    # ── Persistence ───────────────────────────────────────────────────────────

    def _load(self) -> None:
        raw = load_json_file(OUTCOMES_FILE, default=None)
        if raw is None:
            return
        for item in raw:
            try:
                self._outcomes.append(NewsMomentumOutcome(item))
            except Exception:
                pass
        logger.info("CatalystLearning: loaded %d outcomes", len(self._outcomes))

    def _save(self) -> None:
        data = [self._outcome_to_dict(o) for o in self._outcomes]
        save_json_file(OUTCOMES_FILE, data)

    def _outcome_to_dict(self, o: NewsMomentumOutcome) -> dict:
        return {
            "ticker": o.ticker,
            "catalyst_type": o.catalyst_type,
            "catalyst_category": o.catalyst_category,
            "session": o.session,
            "time_of_day": o.time_of_day,
            "price_at_news": o.price_at_news,
            "max_move_pct": o.max_move_pct,
            "mae_pct": o.mae_pct,
            "continued": o.continued,
            "faded": o.faded,
            "trapped": o.trapped,
            "multi_day": o.multi_day,
            "gap_up_next": o.gap_up_next,
            "float_category": o.float_category,
            "market_cap_category": o.market_cap_category,
            "price_bucket": o.price_bucket,
        }

    # ── Recording ─────────────────────────────────────────────────────────────

    def record_outcome(self, outcome: NewsMomentumOutcome) -> None:
        self._outcomes.append(outcome)
        self._save()

    # ── Statistics ────────────────────────────────────────────────────────────

    def get_catalyst_type_stats(self) -> Dict[str, CatalystLearningStats]:
        """Get stats for each catalyst type."""
        by_type = defaultdict(list)
        for o in self._outcomes:
            by_type[o.catalyst_type].append(o)

        result = {}
        for cat_type, outcomes in by_type.items():
            if len(outcomes) < MIN_SAMPLES_FOR_STATS:
                continue
            stats = self._compute_stats(cat_type, outcomes)
            result[cat_type] = stats
        return result

    def _compute_stats(self, cat_type: str, outcomes: List[NewsMomentumOutcome]) -> CatalystLearningStats:
        stats = CatalystLearningStats(catalyst_type=cat_type, total_occurrences=len(outcomes))

        continued = sum(1 for o in outcomes if o.continued)
        faded = sum(1 for o in outcomes if o.faded)
        trapped = sum(1 for o in outcomes if o.trapped)
        multi_day = sum(1 for o in outcomes if o.multi_day)

        stats.continuation_rate = round(continued / len(outcomes) * 100, 1)
        stats.fade_rate = round(faded / len(outcomes) * 100, 1)
        stats.trap_rate = round(trapped / len(outcomes) * 100, 1)

        moves = [o.max_move_pct for o in outcomes if o.max_move_pct is not None]
        if moves:
            stats.avg_move_pct = round(sum(moves) / len(moves), 2)
            stats.avg_mfe_pct = stats.avg_move_pct

        # Best time of day
        by_tod = defaultdict(list)
        for o in outcomes:
            by_tod[o.time_of_day].append(o.max_move_pct)
        if by_tod:
            best_tod = max(by_tod, key=lambda k: sum(by_tod[k]) / len(by_tod[k]))
            stats.best_time_of_day = best_tod

        # Best session
        by_session = defaultdict(list)
        for o in outcomes:
            by_session[o.session].append(o.max_move_pct)
        if by_session:
            best_session = max(by_session, key=lambda k: sum(by_session[k]) / len(by_session[k]))
            stats.best_session = best_session

        return stats

    def get_category_stats(self) -> Dict[str, Dict]:
        """Get stats grouped by catalyst category."""
        by_cat = defaultdict(list)
        for o in self._outcomes:
            by_cat[o.catalyst_category].append(o)

        result = {}
        for cat, outcomes in by_cat.items():
            if len(outcomes) < MIN_SAMPLES_FOR_STATS:
                continue
            continued = sum(1 for o in outcomes if o.continued)
            faded = sum(1 for o in outcomes if o.faded)
            moves = [o.max_move_pct for o in outcomes]
            result[cat] = {
                "total": len(outcomes),
                "continuation_rate": round(continued / len(outcomes) * 100, 1),
                "fade_rate": round(faded / len(outcomes) * 100, 1),
                "avg_move_pct": round(sum(moves) / len(moves), 2) if moves else None,
            }
        return result

    def get_float_stats(self) -> Dict[str, Dict]:
        """Get stats by float category."""
        by_float = defaultdict(list)
        for o in self._outcomes:
            by_float[o.float_category].append(o)

        result = {}
        for fc, outcomes in by_float.items():
            if len(outcomes) < MIN_SAMPLES_FOR_STATS:
                continue
            continued = sum(1 for o in outcomes if o.continued)
            moves = [o.max_move_pct for o in outcomes]
            result[fc] = {
                "total": len(outcomes),
                "continuation_rate": round(continued / len(outcomes) * 100, 1),
                "avg_move_pct": round(sum(moves) / len(moves), 2) if moves else None,
            }
        return result

    def get_time_of_day_stats(self) -> Dict[str, Dict]:
        """Get stats by time of day."""
        by_tod = defaultdict(list)
        for o in self._outcomes:
            by_tod[o.time_of_day].append(o)

        result = {}
        for tod, outcomes in by_tod.items():
            if len(outcomes) < MIN_SAMPLES_FOR_STATS:
                continue
            continued = sum(1 for o in outcomes if o.continued)
            moves = [o.max_move_pct for o in outcomes]
            result[tod] = {
                "total": len(outcomes),
                "continuation_rate": round(continued / len(outcomes) * 100, 1),
                "avg_move_pct": round(sum(moves) / len(moves), 2) if moves else None,
            }
        return result

    def get_recommendations(self) -> List[Dict]:
        """Generate adaptive recommendations based on learning."""
        recommendations = []
        stats = self.get_catalyst_type_stats()

        if not stats:
            recommendations.append({
                "type": "insufficient_data",
                "message": f"Need at least {MIN_SAMPLES_FOR_STATS} outcomes per catalyst type for recommendations.",
            })
            return recommendations

        # Best catalysts
        sorted_by_cont = sorted(stats.items(), key=lambda x: x[1].continuation_rate or 0, reverse=True)
        if sorted_by_cont:
            best = sorted_by_cont[0]
            recommendations.append({
                "type": "best_catalyst",
                "catalyst": best[0],
                "continuation_rate": best[1].continuation_rate,
                "message": f"{best[0]} shows the highest continuation rate at {best[1].continuation_rate}%.",
            })

        # Worst catalysts
        worst = sorted_by_cont[-1]
        recommendations.append({
            "type": "worst_catalyst",
            "catalyst": worst[0],
            "continuation_rate": worst[1].continuation_rate,
            "message": f"{worst[0]} shows the lowest continuation rate at {worst[1].continuation_rate}%.",
        })

        # Best time of day
        tod_stats = self.get_time_of_day_stats()
        if tod_stats:
            best_tod = max(tod_stats.items(), key=lambda x: x[1]["continuation_rate"])
            recommendations.append({
                "type": "best_time",
                "time_of_day": best_tod[0],
                "continuation_rate": best_tod[1]["continuation_rate"],
                "message": f"Best time of day: {best_tod[0]} with {best_tod[1]['continuation_rate']}% continuation rate.",
            })

        # Float insights
        float_stats = self.get_float_stats()
        if float_stats:
            best_float = max(float_stats.items(), key=lambda x: x[1]["continuation_rate"])
            recommendations.append({
                "type": "best_float",
                "float_category": best_float[0],
                "continuation_rate": best_float[1]["continuation_rate"],
                "message": f"{best_float[0]} floats show {best_float[1]['continuation_rate']}% continuation rate.",
            })

        return recommendations

    def get_all_stats(self) -> Dict:
        """Return comprehensive stats for all dimensions."""
        return {
            "by_catalyst_type": {k: v.model_dump() for k, v in self.get_catalyst_type_stats().items()},
            "by_category": self.get_category_stats(),
            "by_float": self.get_float_stats(),
            "by_time_of_day": self.get_time_of_day_stats(),
            "total_outcomes": len(self._outcomes),
            "recommendations": self.get_recommendations(),
        }
