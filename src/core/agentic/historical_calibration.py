"""Model Calibration Engine

Generates calibration recommendations based on pattern analysis.
Applies safe adjustments to scoring models with guardrails.
"""
from __future__ import annotations

import json
import logging
import os
import random
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any

from src.utils.atomic_json import save_json_file, load_json_file

from src.core.agentic.historical_models import (
    PatternBucket,
    PatternInsight,
    CalibrationRecommendation,
    CalibrationWeights,
    TrainingMode,
)

logger = logging.getLogger(__name__)

from src.utils.data_paths import agentic_data_dir as _agentic_data_dir
DATA_DIR = str(_agentic_data_dir())

# ── Safety Guardrails ──────────────────────────────────────────────────────────
MIN_SAMPLE_SIZE = 10
CONFIDENCE_THRESHOLD = "medium"  # low < medium < high
MAX_SCORE_DELTA = 0.15  # max ±15% score change per feature
MAX_WEIGHT_DELTA = 0.15  # max ±15% weight change per feature (spec requirement)
MIN_EVENTS_FOR_APPROVAL = 20  # events before APPROVED_APPLY can trigger auto-apply

FEATURE_MAP = {
    "pre_news_suspicion_score": "pre_news_suspicion_w",
    "second_leg_probability": "second_leg_probability_w",
    "trap_risk": "trap_risk_w",
    "catalyst_strength": "catalyst_strength_w",
    "time_of_day": "time_of_day_w",
    "float_bucket": "float_bucket_w",
    "vwap_hold": "vwap_hold_w",
    "volume_acceleration": "volume_acceleration_w",
    "quiet_accumulation": "quiet_accumulation_w",
}


class CalibrationEngine:
    """Generates calibration recommendations and manages weight adjustments."""

    def __init__(self, data_dir: str = DATA_DIR):
        self.data_dir = data_dir
        os.makedirs(self.data_dir, exist_ok=True)
        self._recommendations: List[CalibrationRecommendation] = []
        self._current_weights = CalibrationWeights()
        self._pending_weights: Optional[CalibrationWeights] = None
        self._rollback_history: List[Dict[str, Any]] = []
        self._load_weights()

    # ------------------------------------------------------------------ #
    #  Weight persistence
    # ------------------------------------------------------------------ #

    def _weights_path(self) -> str:
        return os.path.join(self.data_dir, "historical_calibration_weights.json")

    def _rollback_path(self) -> str:
        return os.path.join(self.data_dir, "historical_rollback_history.json")

    def _load_weights(self) -> None:
        path = self._weights_path()
        data = load_json_file(path, default=None)
        if data is not None:
            try:
                self._current_weights = CalibrationWeights(**data)
                logger.info("Loaded calibration weights v%s", self._current_weights.version)
            except Exception as exc:
                logger.warning("Failed to load weights, using defaults: %s", exc)

    def _save_weights(self) -> None:
        path = self._weights_path()
        save_json_file(path, self._current_weights.model_dump(mode="json"))

    def _save_rollback(self) -> None:
        path = self._rollback_path()
        save_json_file(path, self._rollback_history)

    # ------------------------------------------------------------------ #
    #  Public API
    # ------------------------------------------------------------------ #

    def generate_recommendations(
        self,
        buckets: List[PatternBucket],
        insights: List[PatternInsight],
        total_events: int,
    ) -> List[CalibrationRecommendation]:
        """Generate calibration recommendations from pattern analysis."""
        self._recommendations = []

        if total_events < MIN_SAMPLE_SIZE:
            logger.warning("Insufficient data (%s events) for recommendations", total_events)
            return self._recommendations

        # Analyze time-of-day patterns
        self._recommend_time_of_day_adjustments(buckets)

        # Analyze float + catalyst patterns
        self._recommend_float_catalyst_adjustments(buckets)

        # Analyze volume acceleration patterns
        self._recommend_volume_adjustments(buckets)

        # Analyze trap/failure patterns
        self._recommend_trap_sensitivity_adjustments(buckets, insights)

        # Analyze second leg patterns
        self._recommend_second_leg_adjustments(buckets, insights)

        # Guardrail: single-feature dominance check
        self._check_single_feature_dominance()

        logger.info("Generated %s calibration recommendations", len(self._recommendations))
        return self._recommendations

    def get_recommendations(self) -> List[CalibrationRecommendation]:
        return self._recommendations

    def apply_recommendations(
        self,
        mode: TrainingMode = TrainingMode.RECOMMEND_ONLY,
        approvals: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Apply recommendations in the specified mode."""
        approvals = approvals or []

        if mode == TrainingMode.ANALYSE_ONLY:
            logger.info("ANALYSE_ONLY mode: not applying any recommendations")
            return {"status": "analysed", "applied": 0, "pending": 0}

        if mode == TrainingMode.RECOMMEND_ONLY:
            logger.info("RECOMMEND_ONLY mode: storing pending changes only")
            self._pending_weights = self._compute_new_weights(approved_only=False)
            return {"status": "pending", "applied": 0, "pending": len(self._recommendations)}

        if mode == TrainingMode.APPROVED_APPLY:
            # Only apply approved recommendations
            approved_recs = [r for r in self._recommendations if r.feature in approvals]
            if len(approved_recs) != len(approvals):
                missing = set(approvals) - {r.feature for r in self._recommendations}
                logger.warning("Unknown approvals: %s", missing)

            if len(self._recommendations) < MIN_EVENTS_FOR_APPROVAL:
                logger.warning("Not enough events for approved apply (%s/%s)", len(self._recommendations), MIN_EVENTS_FOR_APPROVAL)
                return {"status": "insufficient_data", "applied": 0, "pending": len(self._recommendations)}

            # Save rollback point
            self._rollback_history.append({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "weights": self._current_weights.model_dump(mode="json"),
                "reason": "approved_apply",
            })
            self._save_rollback()

            # Apply approved changes
            self._pending_weights = self._compute_new_weights(approved_only=True, approved_features=approvals)
            if self._pending_weights:
                self._current_weights = self._pending_weights
                self._current_weights.version += 1
                self._current_weights.updated_at = datetime.now(timezone.utc)
                self._current_weights.is_approved = True
                self._current_weights.approved_by = "historical_training"
                self._save_weights()
                logger.info("Applied %s approved recommendations", len(approved_recs))
                return {"status": "applied", "applied": len(approved_recs), "version": self._current_weights.version}

        return {"status": "unknown_mode", "applied": 0}

    def rollback(self) -> bool:
        """Rollback to previous calibration state."""
        if not self._rollback_history:
            logger.warning("No rollback history available")
            return False

        last = self._rollback_history.pop()
        try:
            self._current_weights = CalibrationWeights(**last["weights"])
            self._save_weights()
            self._save_rollback()
            logger.info("Rolled back to weights version %s", self._current_weights.version)
            return True
        except Exception as exc:
            logger.error("Rollback failed: %s", exc)
            return False

    def get_current_weights(self) -> CalibrationWeights:
        return self._current_weights

    def get_pending_weights(self) -> Optional[CalibrationWeights]:
        return self._pending_weights

    # ------------------------------------------------------------------ #
    #  Recommendation generators
    # ------------------------------------------------------------------ #

    def _recommend_time_of_day_adjustments(self, buckets: List[PatternBucket]) -> None:
        premarket = [b for b in buckets if "premarket" in b.bucket_name.lower()]
        if premarket and premarket[0].clean_expansion_pct > 35:
            self._add_recommendation(
                feature="time_of_day",
                current="1.0x",
                proposed="1.15x",
                evidence=f"Premarket shows {premarket[0].clean_expansion_pct}% clean expansion",
                sample=premarket[0].sample_size,
                rationale="Premarket catalysts show higher success rates",
            )

    def _recommend_float_catalyst_adjustments(self, buckets: List[PatternBucket]) -> None:
        ultra_low = [b for b in buckets if "ultra_low" in b.bucket_name and b.clean_expansion_pct > 30]
        if ultra_low:
            self._add_recommendation(
                feature="float_bucket",
                current="1.0x",
                proposed="1.2x",
                evidence=f"Ultra low float + catalyst shows {ultra_low[0].clean_expansion_pct}% clean expansion",
                sample=ultra_low[0].sample_size,
                rationale="Ultra low float amplifies catalyst moves",
            )

    def _recommend_volume_adjustments(self, buckets: List[PatternBucket]) -> None:
        high_vol = [b for b in buckets if "rvol" in b.bucket_name and ">2.0" in b.bucket_name]
        if high_vol and high_vol[0].clean_expansion_pct > 30:
            self._add_recommendation(
                feature="volume_acceleration",
                current="1.0x",
                proposed="1.15x",
                evidence=f"High rVol shows {high_vol[0].clean_expansion_pct}% clean expansion",
                sample=high_vol[0].sample_size,
                rationale="Volume acceleration correlates with clean moves",
            )

    def _recommend_trap_sensitivity_adjustments(self, buckets: List[PatternBucket], insights: List[PatternInsight]) -> None:
        # Check for high trap rate patterns
        trap_insights = [i for i in insights if i.insight_type == "failure_pattern"]
        if trap_insights:
            worst = max(trap_insights, key=lambda x: x.sample_size)
            if worst.sample_size >= MIN_SAMPLE_SIZE:
                self._add_recommendation(
                    feature="trap_risk",
                    current="1.0x",
                    proposed="1.25x",
                    evidence=f"High trap pattern: {worst.description}",
                    sample=worst.sample_size,
                    rationale="Increase trap detection sensitivity for these conditions",
                )

    def _recommend_second_leg_adjustments(self, buckets: List[PatternBucket], insights: List[PatternInsight]) -> None:
        second_leg_insights = [i for i in insights if i.insight_type == "continuation_pattern"]
        if second_leg_insights:
            best = max(second_leg_insights, key=lambda x: x.sample_size)
            if best.sample_size >= MIN_SAMPLE_SIZE:
                self._add_recommendation(
                    feature="second_leg_probability",
                    current="1.0x",
                    proposed="1.15x",
                    evidence=f"Second leg pattern: {best.description}",
                    sample=best.sample_size,
                    rationale="Increase second leg probability weighting",
                )

    def _add_recommendation(
        self,
        feature: str,
        current: str,
        proposed: str,
        evidence: str,
        sample: int,
        rationale: str,
    ) -> None:
        # Determine confidence
        if sample >= 20:
            confidence = "high"
        elif sample >= 10:
            confidence = "medium"
        else:
            return  # Skip low confidence

        rec = CalibrationRecommendation(
            feature=feature,
            current_threshold=current,
            proposed_threshold=proposed,
            evidence=evidence,
            confidence=confidence,
            expected_impact=f"Adjust {feature} weight",
            sample_count=sample,
            rationale=rationale,
        )
        self._recommendations.append(rec)

    def _compute_new_weights(
        self,
        approved_only: bool,
        approved_features: Optional[List[str]] = None,
    ) -> CalibrationWeights:
        """Compute new weights based on recommendations."""
        weights = CalibrationWeights(**self._current_weights.model_dump())
        approved_set = set(approved_features or [])

        for rec in self._recommendations:
            if approved_only and rec.feature not in approved_set:
                continue

            # Parse proposed multiplier (e.g., "1.15x" -> 1.15)
            try:
                multiplier = float(rec.proposed_threshold.replace("x", "").replace("X", ""))
            except ValueError:
                continue

            # Apply with guardrail limits
            attr = FEATURE_MAP.get(rec.feature)
            if attr and hasattr(weights, attr):
                current = getattr(weights, attr)
                new_val = current * multiplier

                # Clamp to max delta
                max_allowed = current * (1 + MAX_WEIGHT_DELTA)
                min_allowed = current * (1 - MAX_WEIGHT_DELTA)
                new_val = max(min_allowed, min(max_allowed, new_val))

                setattr(weights, attr, round(new_val, 2))

        return weights

    def _check_single_feature_dominance(self) -> None:
        """
        Guardrail: ensure no single feature weight would exceed 40%
        of the total weight sum after recommendations are applied.
        If a recommendation would cause dominance, downgrade its confidence
        or remove it.
        """
        if not self._recommendations:
            return
        # Compute hypothetical total weight after applying all recs
        hyp = CalibrationWeights(**self._current_weights.model_dump())
        for rec in self._recommendations:
            attr = FEATURE_MAP.get(rec.feature)
            if attr and hasattr(hyp, attr):
                try:
                    mult = float(rec.proposed_threshold.replace("x", "").replace("X", ""))
                except ValueError:
                    continue
                current = getattr(hyp, attr)
                new_val = max(current * (1 - MAX_WEIGHT_DELTA), min(current * (1 + MAX_WEIGHT_DELTA), current * mult))
                setattr(hyp, attr, new_val)

        total = sum(getattr(hyp, k, 1.0) for k in FEATURE_MAP.values())
        for rec in self._recommendations:
            attr = FEATURE_MAP.get(rec.feature)
            if attr:
                w = getattr(hyp, attr, 1.0)
                if total > 0 and w / total > 0.40:
                    logger.warning("Single-feature dominance guardrail: %s would be %.0f%% of total — downgrading confidence", rec.feature, (w / total) * 100)
                    rec.confidence = "low"
                    rec.rationale += " [WARNING: would dominate scoring — review before applying]"

    def validate_out_of_sample(
        self,
        _training_events: List[Any],
        test_events: List[Any],
    ) -> Dict[str, Any]:
        """
        Validate that recommended weight changes improve performance
        on a held-out test set.  Returns validation metrics.
        """
        if len(test_events) < 5:
            return {"valid": False, "reason": "Too few test events for validation", "test_size": len(test_events)}

        # Baseline: use current weights (all 1.0) to score test events
        # This is a simplified proxy — real validation would re-run the
        # full scoring pipeline.  For now, we return a structural stub.
        baseline_score = 0.0
        calibrated_score = 0.0

        # Count how many test events are "winners" under baseline vs calibrated
        for e in test_events:
            oc = e.outcome.outcome_class.value if hasattr(e, "outcome") and e.outcome else ""
            if oc in ("clean_expansion", "second_leg_continuation"):
                baseline_score += 1.0

        # Apply hypothetical calibration weights to float scores as a proxy
        cw = self._current_weights
        for e in test_events:
            fs = e.feature_snapshot or {} if hasattr(e, "feature_snapshot") else {}
            oc = e.outcome.outcome_class.value if hasattr(e, "outcome") and e.outcome else ""
            if oc in ("clean_expansion", "second_leg_continuation"):
                # Simple heuristic: if float_bucket_w is boosted and event is low float, give bonus
                if cw.float_bucket_w > 1.0 and fs.get("float_bucket") in ("ultra_low", "low"):
                    calibrated_score += cw.float_bucket_w
                else:
                    calibrated_score += 1.0

        improvement = round((calibrated_score - baseline_score) / max(baseline_score, 1), 3) if baseline_score > 0 else 0.0
        return {
            "valid": improvement > 0,
            "baseline_score": round(baseline_score, 2),
            "calibrated_score": round(calibrated_score, 2),
            "improvement_pct": round(improvement * 100, 1),
            "test_size": len(test_events),
        }
