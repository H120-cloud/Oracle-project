"""Pattern Discovery Engine

Analyzes historical catalyst events to discover patterns that correlate
with outcomes. Generates insights for model calibration.
"""
from __future__ import annotations

import logging
import statistics
from typing import Dict, List, Optional, Any
from collections import defaultdict

from src.core.agentic.historical_models import (
    HistoricalCatalystEvent,
    HistoricalOutcomeClass,
    PatternBucket,
    PatternInsight,
)

logger = logging.getLogger(__name__)


class PatternDiscoveryEngine:
    """Discovers patterns in historical catalyst data."""

    MIN_SAMPLE_SIZE = 5
    HIGH_CONFIDENCE_MIN = 15

    def __init__(self):
        self._buckets: List[PatternBucket] = []
        self._insights: List[PatternInsight] = []

    def analyze(self, events: List[HistoricalCatalystEvent]) -> List[PatternBucket]:
        """Run full pattern analysis on resolved events."""
        resolved = [e for e in events if e.outcome is not None]
        if len(resolved) < self.MIN_SAMPLE_SIZE:
            logger.warning("Not enough resolved events (%s) for pattern analysis", len(resolved))
            return []

        self._buckets = []
        self._insights = []

        # Build buckets by different feature combinations
        self._bucket_by_catalyst_type(resolved)
        self._bucket_by_float_and_catalyst(resolved)
        self._bucket_by_time_of_day(resolved)
        self._bucket_by_rvol_threshold(resolved)
        self._bucket_by_volume_acceleration(resolved)

        # Generate insights from buckets
        self._generate_insights()

        logger.info("Pattern analysis complete: %s buckets, %s insights", len(self._buckets), len(self._insights))
        return self._buckets

    def get_insights(self) -> List[PatternInsight]:
        return self._insights

    def _bucket_by_catalyst_type(self, events: List[HistoricalCatalystEvent]) -> None:
        by_type = defaultdict(list)
        for e in events:
            by_type[e.catalyst_type.value].append(e)

        for cat_type, evts in by_type.items():
            self._add_bucket(f"catalyst_type={cat_type}", evts)

    def _bucket_by_float_and_catalyst(self, events: List[HistoricalCatalystEvent]) -> None:
        by_combo = defaultdict(list)
        for e in events:
            float_bucket = self._get_float_bucket(e)
            if float_bucket:
                key = f"float={float_bucket},catalyst={e.catalyst_type.value}"
                by_combo[key].append(e)

        for combo, evts in by_combo.items():
            self._add_bucket(combo, evts)

    def _bucket_by_time_of_day(self, events: List[HistoricalCatalystEvent]) -> None:
        by_time = defaultdict(list)
        for e in events:
            bucket = e.time_of_day_bucket or "unknown"
            by_time[bucket].append(e)

        for time_bucket, evts in by_time.items():
            self._add_bucket(f"time_of_day={time_bucket}", evts)

    def _bucket_by_rvol_threshold(self, events: List[HistoricalCatalystEvent]) -> None:
        high_rvol = [e for e in events if e.feature_snapshot and e.feature_snapshot.get("rvol_30m", 0) > 2.0]
        low_rvol = [e for e in events if e.feature_snapshot and e.feature_snapshot.get("rvol_30m", 0) <= 2.0]
        self._add_bucket("rvol_30m>2.0", high_rvol)
        self._add_bucket("rvol_30m<=2.0", low_rvol)

    def _bucket_by_volume_acceleration(self, events: List[HistoricalCatalystEvent]) -> None:
        acc = [e for e in events if e.feature_snapshot and e.feature_snapshot.get("volume_acceleration", 0) > 1.5]
        no_acc = [e for e in events if e.feature_snapshot and e.feature_snapshot.get("volume_acceleration", 0) <= 1.5]
        self._add_bucket("vol_accel>1.5", acc)
        self._add_bucket("vol_accel<=1.5", no_acc)

    def _add_bucket(self, name: str, events: List[HistoricalCatalystEvent]) -> None:
        if len(events) < self.MIN_SAMPLE_SIZE:
            return

        outcomes = [e.outcome for e in events if e.outcome]
        if not outcomes:
            return

        total = len(outcomes)

        def _get_outcome_class(o):
            if isinstance(o, dict):
                return o.get("outcome_class", "")
            return getattr(o, "outcome_class", "")

        def _get_mfe(o):
            if isinstance(o, dict):
                return o.get("max_favorable_excursion_pct")
            return getattr(o, "max_favorable_excursion_pct", None)

        def _get_mae(o):
            if isinstance(o, dict):
                return o.get("max_adverse_excursion_pct")
            return getattr(o, "max_adverse_excursion_pct", None)

        def _get_move(o):
            if isinstance(o, dict):
                return o.get("move_after_news_pct", 0.0)
            return getattr(o, "move_after_news_pct", 0.0)

        def count_class(cls: HistoricalOutcomeClass) -> int:
            return sum(1 for o in outcomes if _get_outcome_class(o) == cls)

        clean = count_class(HistoricalOutcomeClass.CLEAN_EXPANSION)
        second = count_class(HistoricalOutcomeClass.SECOND_LEG_CONTINUATION)
        partial = count_class(HistoricalOutcomeClass.PARTIAL_MOVE)
        failed = count_class(HistoricalOutcomeClass.FAILED_CATALYST)
        trap = count_class(HistoricalOutcomeClass.TRAP_MOVE)
        faded = count_class(HistoricalOutcomeClass.FADED_MOVE)
        sell = count_class(HistoricalOutcomeClass.SELL_THE_NEWS)

        mfe_vals = [_get_mfe(o) for o in outcomes if _get_mfe(o) is not None]
        mae_vals = [_get_mae(o) for o in outcomes if _get_mae(o) is not None]
        move_vals = [_get_move(o) for o in outcomes]

        bucket = PatternBucket(
            bucket_name=name,
            filter_description=name,
            count=total,
            clean_expansion_pct=round(clean / total * 100, 1),
            second_leg_pct=round(second / total * 100, 1),
            partial_pct=round((partial + faded) / total * 100, 1),
            failed_pct=round((failed + sell) / total * 100, 1),
            trap_pct=round(trap / total * 100, 1),
            avg_mfe=round(statistics.mean(mfe_vals), 2) if mfe_vals else 0.0,
            avg_mae=round(statistics.mean(mae_vals), 2) if mae_vals else 0.0,
            avg_move_pct=round(statistics.mean(move_vals), 2) if move_vals else 0.0,
            confidence="high" if total >= self.HIGH_CONFIDENCE_MIN else "medium",
            sample_size=total,
        )
        self._buckets.append(bucket)

    def _generate_insights(self) -> None:
        """Generate insights from pattern buckets."""
        for bucket in self._buckets:
            # Success pattern: high clean expansion rate
            if bucket.clean_expansion_pct >= 40 and bucket.sample_size >= self.MIN_SAMPLE_SIZE:
                self._insights.append(PatternInsight(
                    insight_type="success_pattern",
                    description=f"{bucket.bucket_name} shows {bucket.clean_expansion_pct}% clean expansion rate",
                    pattern_filter={"bucket": bucket.bucket_name},
                    evidence=f"{bucket.count} samples, avg MFE {bucket.avg_mfe}%",
                    sample_size=bucket.count,
                    confidence=bucket.confidence,
                    expected_impact="increase_pre_news_suspicion_score",
                ))

            # Second leg pattern
            if bucket.second_leg_pct >= 25 and bucket.sample_size >= self.MIN_SAMPLE_SIZE:
                self._insights.append(PatternInsight(
                    insight_type="continuation_pattern",
                    description=f"{bucket.bucket_name} shows {bucket.second_leg_pct}% second leg continuation",
                    pattern_filter={"bucket": bucket.bucket_name},
                    evidence=f"{bucket.count} samples, avg move {bucket.avg_move_pct}%",
                    sample_size=bucket.count,
                    confidence=bucket.confidence,
                    expected_impact="increase_second_leg_probability",
                ))

            # Failure pattern: high trap/failed rate
            if (bucket.trap_pct + bucket.failed_pct) >= 40 and bucket.sample_size >= self.MIN_SAMPLE_SIZE:
                self._insights.append(PatternInsight(
                    insight_type="failure_pattern",
                    description=f"{bucket.bucket_name} shows {bucket.trap_pct + bucket.failed_pct}% trap/failure rate",
                    pattern_filter={"bucket": bucket.bucket_name},
                    evidence=f"{bucket.count} samples, trap {bucket.trap_pct}%",
                    sample_size=bucket.count,
                    confidence=bucket.confidence,
                    expected_impact="raise_trap_detection_sensitivity",
                ))

            # Correlation: high volume acceleration success
            if "vol_accel" in bucket.bucket_name and bucket.clean_expansion_pct > 30:
                self._insights.append(PatternInsight(
                    insight_type="correlation",
                    description=f"Volume acceleration in {bucket.bucket_name} correlates with clean moves",
                    pattern_filter={"bucket": bucket.bucket_name},
                    evidence=f"{bucket.count} samples, {bucket.clean_expansion_pct}% clean",
                    sample_size=bucket.count,
                    confidence=bucket.confidence,
                    expected_impact="increase_volume_acceleration_weight",
                ))

    def _get_float_bucket(self, event: HistoricalCatalystEvent) -> Optional[str]:
        if event.float_category is not None:
            return event.float_category.value
        if event.float_shares is None:
            return None
        if event.float_shares < 5_000_000:
            return "ultra_low"
        if event.float_shares < 20_000_000:
            return "low"
        return "normal"

    def find_best_patterns(self, min_sample_size: int = 10) -> List[PatternBucket]:
        """Return patterns with highest clean expansion rates."""
        filtered = [b for b in self._buckets if b.sample_size >= min_sample_size]
        return sorted(filtered, key=lambda x: x.clean_expansion_pct, reverse=True)[:10]

    def find_worst_patterns(self, min_sample_size: int = 10) -> List[PatternBucket]:
        """Return patterns with highest trap/failure rates."""
        filtered = [b for b in self._buckets if b.sample_size >= min_sample_size]
        return sorted(filtered, key=lambda x: x.trap_pct + x.failed_pct, reverse=True)[:10]
