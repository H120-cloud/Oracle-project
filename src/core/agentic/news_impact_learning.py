"""
News Catalyst Impact Engine — Learning Loop (V20)

Tracks post-detection price evolution for every catalyst evaluated by the
NewsImpactEngine, then aggregates statistics so the engine can be calibrated
over time.

Persistence:
    data/agentic/news_impact_outcomes.json    — list of NewsImpactOutcome dicts
    data/agentic/news_impact_stats.json       — last-computed aggregate stats

The learning loop is *advisory* — it never auto-changes scoring weights.
It produces calibration suggestions for human review.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median
from typing import Optional

from src.utils.atomic_json import save_json_file, load_json_file

logger = logging.getLogger(__name__)

from src.utils.data_paths import AGENTIC_DATA_DIR as DATA_DIR
OUTCOMES_PATH = DATA_DIR / "news_impact_outcomes.json"
STATS_PATH = DATA_DIR / "news_impact_stats.json"

MIN_OUTCOMES_FOR_CALIBRATION = 100


@dataclass
class NewsImpactOutcome:
    """One tracked outcome for a news catalyst."""
    ticker: str
    headline: str
    catalyst_type: str
    detected_at: str
    price_at_detection: Optional[float] = None
    news_impact_score: float = 0.0
    news_decision: str = "IGNORE"
    estimated_bullish_move_pct: float = 0.0
    pre_news_accumulation_detected: bool = False
    is_dilution: bool = False
    is_parabolic: bool = False

    # Snapshot prices
    price_15m: Optional[float] = None
    price_1h: Optional[float] = None
    price_4h: Optional[float] = None
    price_next_day: Optional[float] = None

    # Performance metrics
    mfe_pct: Optional[float] = None  # max favourable excursion
    mae_pct: Optional[float] = None  # max adverse excursion

    # Behaviour flags
    continuation_quality: str = "unknown"  # clean / partial / failed / dead / trap
    trap_behavior: bool = False
    vwap_reclaimed: bool = False
    abcd_confirmed: bool = False

    recorded_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def is_complete(self) -> bool:
        """True once we have enough price snapshots for a usable outcome."""
        return self.price_4h is not None or self.price_next_day is not None


@dataclass
class CatalystStats:
    """Aggregate statistics for a single catalyst type."""
    catalyst_type: str
    sample_size: int = 0
    avg_move_pct: float = 0.0
    median_move_pct: float = 0.0
    avg_mfe_pct: float = 0.0
    avg_mae_pct: float = 0.0
    trap_rate: float = 0.0  # % that ended badly despite high score
    win_rate: float = 0.0   # % with positive bullish_move continuation


class NewsImpactLearningEngine:
    """Persists, aggregates and reports on news-catalyst outcomes."""

    def __init__(self):
        self.outcomes: list[NewsImpactOutcome] = []
        self._load()

    # ── Persistence ─────────────────────────────────────────────────────

    def _load(self):
        data = load_json_file(OUTCOMES_PATH, default=None)
        if data is not None:
            try:
                self.outcomes = [NewsImpactOutcome(**d) for d in data]
                logger.info("NewsImpactLearning: loaded %d outcomes", len(self.outcomes))
            except Exception as exc:
                logger.warning("NewsImpactLearning load failed: %s", exc)
                self.outcomes = []
        else:
            self.outcomes = []

    def _persist(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        data = [asdict(o) for o in self.outcomes]
        save_json_file(OUTCOMES_PATH, data)

    # ── Public API ──────────────────────────────────────────────────────

    def record(self, result, price_at_detection: Optional[float] = None) -> NewsImpactOutcome:
        """Create and persist an outcome row from a NewsImpactResult."""
        from src.core.agentic.news_impact_engine import NewsImpactResult  # local import to avoid cycles

        # Accept either NewsImpactResult or a plain dict
        if isinstance(result, NewsImpactResult):
            outcome = NewsImpactOutcome(
                ticker=result.ticker,
                headline=result.headline,
                catalyst_type=result.catalyst_type.value,
                detected_at=result.detected_at.isoformat(),
                price_at_detection=price_at_detection or result.price_at_detection,
                news_impact_score=result.news_impact_score,
                news_decision=result.news_decision.value,
                estimated_bullish_move_pct=result.estimated_move_range.bullish_move_pct,
                pre_news_accumulation_detected=result.pre_news_accumulation_detected,
                is_dilution=result.is_dilution,
                is_parabolic=result.is_parabolic,
            )
        else:  # dict path (used by API endpoint)
            outcome = NewsImpactOutcome(
                ticker=result.get("ticker", ""),
                headline=result.get("headline", ""),
                catalyst_type=result.get("catalyst_type", "other"),
                detected_at=result.get("detected_at", datetime.now(timezone.utc).isoformat()),
                price_at_detection=price_at_detection or result.get("price_at_detection"),
                news_impact_score=result.get("news_impact_score", 0.0),
                news_decision=result.get("news_decision", "IGNORE"),
                estimated_bullish_move_pct=(
                    result.get("estimated_move_range", {}).get("bullish_move_pct", 0.0)
                ),
                pre_news_accumulation_detected=result.get("pre_news_accumulation_detected", False),
                is_dilution=result.get("is_dilution", False),
                is_parabolic=result.get("is_parabolic", False),
            )

        self.outcomes.append(outcome)
        self._persist()
        return outcome

    def update_price_snapshot(self, ticker: str, detected_at: str, *,
                              price_15m: Optional[float] = None,
                              price_1h: Optional[float] = None,
                              price_4h: Optional[float] = None,
                              price_next_day: Optional[float] = None,
                              mfe_pct: Optional[float] = None,
                              mae_pct: Optional[float] = None,
                              continuation_quality: Optional[str] = None,
                              trap_behavior: Optional[bool] = None,
                              vwap_reclaimed: Optional[bool] = None,
                              abcd_confirmed: Optional[bool] = None) -> Optional[NewsImpactOutcome]:
        """Update an existing outcome row with later price/quality data."""
        for o in self.outcomes:
            if o.ticker == ticker and o.detected_at == detected_at:
                if price_15m is not None: o.price_15m = price_15m
                if price_1h is not None: o.price_1h = price_1h
                if price_4h is not None: o.price_4h = price_4h
                if price_next_day is not None: o.price_next_day = price_next_day
                if mfe_pct is not None: o.mfe_pct = mfe_pct
                if mae_pct is not None: o.mae_pct = mae_pct
                if continuation_quality is not None: o.continuation_quality = continuation_quality
                if trap_behavior is not None: o.trap_behavior = trap_behavior
                if vwap_reclaimed is not None: o.vwap_reclaimed = vwap_reclaimed
                if abcd_confirmed is not None: o.abcd_confirmed = abcd_confirmed
                self._persist()
                return o
        return None

    # ── Stats ──────────────────────────────────────────────────────────

    def stats_by_catalyst(self) -> dict[str, CatalystStats]:
        """Aggregate stats grouped by catalyst type."""
        groups: dict[str, list[NewsImpactOutcome]] = {}
        for o in self.outcomes:
            groups.setdefault(o.catalyst_type, []).append(o)

        result: dict[str, CatalystStats] = {}
        for cat, items in groups.items():
            mfe_values = [o.mfe_pct for o in items if o.mfe_pct is not None]
            mae_values = [o.mae_pct for o in items if o.mae_pct is not None]
            move_values = []
            for o in items:
                if o.price_at_detection and o.price_4h:
                    move_values.append((o.price_4h - o.price_at_detection) / o.price_at_detection * 100)
                elif o.price_at_detection and o.price_next_day:
                    move_values.append((o.price_next_day - o.price_at_detection) / o.price_at_detection * 100)

            traps = sum(1 for o in items if o.trap_behavior)
            wins = sum(1 for o in items if o.continuation_quality in ("clean", "partial"))

            result[cat] = CatalystStats(
                catalyst_type=cat,
                sample_size=len(items),
                avg_move_pct=mean(move_values) if move_values else 0.0,
                median_move_pct=median(move_values) if move_values else 0.0,
                avg_mfe_pct=mean(mfe_values) if mfe_values else 0.0,
                avg_mae_pct=mean(mae_values) if mae_values else 0.0,
                trap_rate=(traps / len(items) * 100) if items else 0.0,
                win_rate=(wins / len(items) * 100) if items else 0.0,
            )
        return result

    def overall_summary(self) -> dict:
        """Top-level dashboard summary."""
        completed = [o for o in self.outcomes if o.is_complete()]
        by_cat = self.stats_by_catalyst()

        # Best / worst catalysts by avg move (require at least 5 samples)
        ranked = sorted(
            [s for s in by_cat.values() if s.sample_size >= 5],
            key=lambda s: s.avg_move_pct,
            reverse=True,
        )
        best = [asdict(s) for s in ranked[:5]]
        worst = [asdict(s) for s in ranked[-5:][::-1]]

        return {
            "total_outcomes": len(self.outcomes),
            "completed_outcomes": len(completed),
            "ready_for_calibration": len(completed) >= MIN_OUTCOMES_FOR_CALIBRATION,
            "min_required": MIN_OUTCOMES_FOR_CALIBRATION,
            "stats_by_catalyst": {k: asdict(v) for k, v in by_cat.items()},
            "best_catalysts": best,
            "worst_catalysts": worst,
        }

    def calibration_recommendations(self) -> list[dict]:
        """Suggest scoring tweaks once we have enough data.

        Output is human-readable: each entry has catalyst_type + delta +
        rationale. Never auto-applied.
        """
        completed = [o for o in self.outcomes if o.is_complete()]
        if len(completed) < MIN_OUTCOMES_FOR_CALIBRATION:
            return []

        suggestions: list[dict] = []
        for cat, stats in self.stats_by_catalyst().items():
            if stats.sample_size < 10:
                continue
            # If trap rate is high — recommend reducing materiality
            if stats.trap_rate >= 40 and stats.avg_move_pct < 0:
                suggestions.append({
                    "catalyst_type": cat,
                    "suggested_delta": -10,
                    "rationale": f"High trap rate ({stats.trap_rate:.0f}%) with avg move {stats.avg_move_pct:.1f}% — reduce materiality.",
                })
            # If consistently strong continuation — recommend increasing
            elif stats.win_rate >= 65 and stats.avg_move_pct >= 20:
                suggestions.append({
                    "catalyst_type": cat,
                    "suggested_delta": +5,
                    "rationale": f"Strong win rate ({stats.win_rate:.0f}%) avg +{stats.avg_move_pct:.1f}% — boost materiality.",
                })

        # Persist last-computed snapshot
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        save_json_file(STATS_PATH, {
            "computed_at": datetime.now(timezone.utc).isoformat(),
            "summary": self.overall_summary(),
            "suggestions": suggestions,
        })

        return suggestions


__all__ = [
    "NewsImpactOutcome",
    "CatalystStats",
    "NewsImpactLearningEngine",
    "MIN_OUTCOMES_FOR_CALIBRATION",
]
