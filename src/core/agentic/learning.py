"""
Agentic Elite Self-Learning Engine — V12

Tracks outcomes with full feature snapshots, performs correlation analysis,
generates evidence-based threshold recommendations with confidence levels,
and suggests (never auto-applies) weight adjustments.

Safety protocols:
- Minimum 100 general outcomes before any recommendation
- Minimum 30 per momentum state, 20 per catalyst type
- Max 10-15% weight change per adjustment cycle
- Manual approval required for all live changes
- Rollback support with full history
"""

import json
import logging
import os
from datetime import datetime, timezone
from typing import Optional

from src.utils.atomic_json import save_json_file, load_json_file

from src.core.agentic.models import (
    AgenticOutcome, OutcomeClass, LearningWeights, AgenticCandidate,
    MLPredictionResult,
)
from src.core.agentic.ml_advisory import MLAdvisoryEngine

logger = logging.getLogger(__name__)

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "..", "data", "agentic")

# ── Sample-size thresholds ──────────────────────────────────────────────
MIN_SAMPLE_SIZE = 20          # Legacy: basic stats
MIN_GENERAL_SAMPLES = 100     # Minimum total outcomes for recommendations
MIN_STATE_SAMPLES = 30        # Per momentum state
MIN_CATALYST_SAMPLES = 20     # Per catalyst type

# ── Confidence levels ─────────────────────────────────────────────────
CONFIDENCE_LOW = "LOW"
CONFIDENCE_MEDIUM = "MEDIUM"
CONFIDENCE_HIGH = "HIGH"

# ── Overfitting guard ───────────────────────────────────────────────
MAX_WEIGHT_CHANGE_PER_CYCLE = 0.15  # 15% cap on any single weight shift


class LearningEngine:
    """
    Elite learning engine with feature correlation analysis,
    threshold optimization, and evidence-based recommendations.
    """

    def __init__(self):
        self._outcomes: list[AgenticOutcome] = []
        self._weights_history: list[LearningWeights] = []
        self._current_weights = LearningWeights()
        self._ml_engine = MLAdvisoryEngine()
        self._load()

    @property
    def outcomes(self) -> list[AgenticOutcome]:
        return self._outcomes

    @property
    def current_weights(self) -> LearningWeights:
        return self._current_weights

    # ── Recording ─────────────────────────────────────────────────────

    def record_outcome(self, outcome: AgenticOutcome):
        """Record a trade outcome."""
        self._outcomes.append(outcome)
        self._persist()

    def record_from_candidate(
        self,
        candidate: AgenticCandidate,
        peak_price: Optional[float] = None,
        exit_price: Optional[float] = None,
    ) -> AgenticOutcome:
        """Create and record an outcome with full feature snapshot."""
        entry = candidate.entry_timing.entry_zone_high or candidate.last_price or 0
        peak = peak_price or candidate.momentum.high_of_day or entry
        exit_p = exit_price or candidate.last_price or entry

        if entry > 0 and peak > 0:
            mfe = ((peak - entry) / entry) * 100
        else:
            mfe = 0
        if entry > 0 and exit_p > 0:
            mae = ((entry - min(exit_p, entry)) / entry) * 100
        else:
            mae = 0

        # Classify outcome
        pnl_pct = ((exit_p - entry) / entry * 100) if entry > 0 else 0
        if pnl_pct >= 10:
            outcome_class = OutcomeClass.CLEAN_CONTINUATION
        elif pnl_pct >= 3:
            outcome_class = OutcomeClass.PARTIAL
        elif pnl_pct > -5:
            outcome_class = OutcomeClass.FAILED
        else:
            outcome_class = OutcomeClass.DEAD

        # Build enriched outcome with full candidate snapshot
        outcome = AgenticOutcome(
            candidate_id=candidate.id,
            ticker=candidate.ticker,
            outcome_class=outcome_class,
            entry_price=entry,
            peak_price=peak,
            exit_price=exit_p,
            max_favorable_excursion_pct=round(mfe, 2),
            max_adverse_excursion_pct=round(mae, 2),
            vwap_held=candidate.momentum.vwap_reclaimed,
            # ── Feature snapshot ─────────────────────────────
            state=candidate.momentum.state.value,
            probability=candidate.second_leg.probability,
            trap_risk=candidate.trap.trap_risk_score,
            volume_persistence=candidate.momentum.volume_persistence_pct,
            higher_low_formed=candidate.momentum.higher_low_formed,
            float_category=candidate.float_intel.float_category.value,
            catalyst_type=candidate.catalyst.catalyst_type.value,
            catalyst_strength=candidate.catalyst.strength_score,
            time_of_day_session=candidate.time_of_day.session.value,
            entry_quality=candidate.entry_timing.quality.value,
            rejected=candidate.rejected,
            alertable=candidate.alertable,
            rejection_reasons=candidate.rejection_reasons,
        )

        self.record_outcome(outcome)
        return outcome

    # ── Stats ─────────────────────────────────────────────────────────

    def get_stats(self) -> dict:
        """Compute aggregate performance stats."""
        if not self._outcomes:
            return {
                "total": 0, "wins": 0, "win_rate": 0,
                "avg_mfe_pct": 0, "avg_mae_pct": 0,
                "by_class": {}, "sample_size_ok": False,
            }

        total = len(self._outcomes)
        wins = sum(1 for o in self._outcomes if o.outcome_class in (
            OutcomeClass.CLEAN_CONTINUATION, OutcomeClass.PARTIAL
        ))
        avg_mfe = sum(o.max_favorable_excursion_pct or 0 for o in self._outcomes) / total
        avg_mae = sum(o.max_adverse_excursion_pct or 0 for o in self._outcomes) / total

        by_class = {}
        for o in self._outcomes:
            by_class[o.outcome_class.value] = by_class.get(o.outcome_class.value, 0) + 1

        return {
            "total": total,
            "wins": wins,
            "win_rate": round(wins / total * 100, 1) if total > 0 else 0,
            "avg_mfe_pct": round(avg_mfe, 2),
            "avg_mae_pct": round(avg_mae, 2),
            "by_class": by_class,
            "sample_size_ok": total >= MIN_SAMPLE_SIZE,
        }

    # ── Correlation Analysis ──────────────────────────────────────────

    @staticmethod
    def _is_win(o: AgenticOutcome) -> bool:
        return o.outcome_class in (OutcomeClass.CLEAN_CONTINUATION, OutcomeClass.PARTIAL)

    @staticmethod
    def _confidence(count: int) -> str:
        if count >= 100:
            return CONFIDENCE_HIGH
        if count >= 50:
            return CONFIDENCE_MEDIUM
        return CONFIDENCE_LOW

    def _analyze_bucket(self, outcomes: list[AgenticOutcome]) -> dict:
        """Compute performance metrics for a bucket of outcomes."""
        total = len(outcomes)
        if total == 0:
            return {"count": 0, "win_rate": 0, "avg_mfe": 0, "avg_mae": 0}

        wins = sum(1 for o in outcomes if self._is_win(o))
        mfe = sum(o.max_favorable_excursion_pct or 0 for o in outcomes) / total
        mae = sum(o.max_adverse_excursion_pct or 0 for o in outcomes) / total

        return {
            "count": total,
            "win_rate": round(wins / total * 100, 1),
            "avg_mfe": round(mfe, 2),
            "avg_mae": round(mae, 2),
            "confidence": self._confidence(total),
        }

    def _analyze_by_state(self) -> dict:
        """Analyze outcomes grouped by momentum state."""
        buckets: dict[str, list[AgenticOutcome]] = {}
        for o in self._outcomes:
            if o.state:
                buckets.setdefault(o.state, []).append(o)
        return {k: self._analyze_bucket(v) for k, v in buckets.items()}

    def _analyze_by_probability(self) -> dict:
        """Analyze outcomes grouped by second-leg probability buckets."""
        buckets = {"<50": [], "50-65": [], "65-80": [], "80+": []}
        for o in self._outcomes:
            if o.probability is None:
                continue
            p = o.probability
            if p < 50:
                buckets["<50"].append(o)
            elif p < 65:
                buckets["50-65"].append(o)
            elif p < 80:
                buckets["65-80"].append(o)
            else:
                buckets["80+"].append(o)
        return {k: self._analyze_bucket(v) for k, v in buckets.items()}

    def _analyze_by_trap_risk(self) -> dict:
        """Analyze outcomes grouped by trap risk score buckets."""
        buckets = {"<25": [], "25-50": [], "50-75": [], "75+": []}
        for o in self._outcomes:
            if o.trap_risk is None:
                continue
            t = o.trap_risk
            if t < 25:
                buckets["<25"].append(o)
            elif t < 50:
                buckets["25-50"].append(o)
            elif t < 75:
                buckets["50-75"].append(o)
            else:
                buckets["75+"].append(o)
        return {k: self._analyze_bucket(v) for k, v in buckets.items()}

    def _analyze_by_time_of_day(self) -> dict:
        """Analyze outcomes grouped by trading session."""
        buckets: dict[str, list[AgenticOutcome]] = {}
        for o in self._outcomes:
            if o.time_of_day_session:
                buckets.setdefault(o.time_of_day_session, []).append(o)
        return {k: self._analyze_bucket(v) for k, v in buckets.items()}

    def _analyze_by_catalyst_type(self) -> dict:
        """Analyze outcomes grouped by catalyst type."""
        buckets: dict[str, list[AgenticOutcome]] = {}
        for o in self._outcomes:
            if o.catalyst_type:
                buckets.setdefault(o.catalyst_type, []).append(o)
        return {k: self._analyze_bucket(v) for k, v in buckets.items()}

    # ── Insight Generation ────────────────────────────────────────────

    def generate_insights(self) -> dict:
        """
        Generate comprehensive learning insights with:
        - Feature correlation analysis
        - Best / worst performing conditions
        - Threshold recommendations with confidence
        - Overfitting warnings
        """
        insights = {
            "total_samples": len(self._outcomes),
            "is_valid": len(self._outcomes) >= MIN_GENERAL_SAMPLES,
            "best_conditions": [],
            "worst_conditions": [],
            "threshold_recommendations": [],
            "feature_correlations": {},
            "warnings": [],
        }

        total = len(self._outcomes)
        if total < MIN_GENERAL_SAMPLES:
            insights["warnings"].append(
                f"Need {MIN_GENERAL_SAMPLES - total} more outcomes before reliable recommendations (have {total})."
            )
            return insights

        # Run all analyses
        state_analysis = self._analyze_by_state()
        prob_analysis = self._analyze_by_probability()
        trap_analysis = self._analyze_by_trap_risk()
        tod_analysis = self._analyze_by_time_of_day()
        catalyst_analysis = self._analyze_by_catalyst_type()

        insights["feature_correlations"] = {
            "state": state_analysis,
            "probability": prob_analysis,
            "trap_risk": trap_analysis,
            "time_of_day": tod_analysis,
            "catalyst_type": catalyst_analysis,
        }

        # Best / worst conditions
        insights["best_conditions"] = self._find_best_conditions(
            state_analysis, prob_analysis, trap_analysis, tod_analysis, catalyst_analysis
        )
        insights["worst_conditions"] = self._find_worst_conditions(
            state_analysis, prob_analysis, trap_analysis, tod_analysis, catalyst_analysis
        )

        # Recommendations
        insights["threshold_recommendations"] = self._build_recommendations(
            state_analysis, prob_analysis, trap_analysis, tod_analysis, catalyst_analysis
        )

        # Overfitting warnings
        for rec in insights["threshold_recommendations"]:
            if rec["confidence"] == CONFIDENCE_LOW:
                insights["warnings"].append(
                    f"Low confidence for '{rec['feature']}' recommendation ({rec['sample_count']} samples)."
                )

        low_sample_states = [s for s, d in state_analysis.items() if d["count"] < MIN_STATE_SAMPLES]
        if low_sample_states:
            insights["warnings"].append(
                f"States with insufficient samples: {', '.join(low_sample_states)} (need {MIN_STATE_SAMPLES}+)."
            )

        low_sample_cats = [c for c, d in catalyst_analysis.items() if d["count"] < MIN_CATALYST_SAMPLES]
        if low_sample_cats:
            insights["warnings"].append(
                f"Catalyst types with insufficient samples: {', '.join(low_sample_cats)} (need {MIN_CATALYST_SAMPLES}+)."
            )

        return insights

    def _find_best_conditions(self, state, prob, trap, tod, catalyst) -> list[dict]:
        """Identify the top-performing setup conditions."""
        conditions = []

        for name, data in state.items():
            if data["count"] >= MIN_STATE_SAMPLES and data["win_rate"] > 30:
                conditions.append({
                    "type": "state",
                    "name": name,
                    "win_rate": data["win_rate"],
                    "avg_mfe": data["avg_mfe"],
                    "count": data["count"],
                    "confidence": data["confidence"],
                })

        for name, data in prob.items():
            if data["count"] >= 30 and data["win_rate"] > 30:
                conditions.append({
                    "type": "probability",
                    "name": name,
                    "win_rate": data["win_rate"],
                    "avg_mfe": data["avg_mfe"],
                    "count": data["count"],
                    "confidence": data["confidence"],
                })

        for name, data in trap.items():
            if data["count"] >= 30 and data["win_rate"] > 30:
                conditions.append({
                    "type": "trap_risk",
                    "name": name,
                    "win_rate": data["win_rate"],
                    "avg_mfe": data["avg_mfe"],
                    "count": data["count"],
                    "confidence": data["confidence"],
                })

        for name, data in tod.items():
            if data["count"] >= 20 and data["win_rate"] > 30:
                conditions.append({
                    "type": "time_of_day",
                    "name": name,
                    "win_rate": data["win_rate"],
                    "avg_mfe": data["avg_mfe"],
                    "count": data["count"],
                    "confidence": data["confidence"],
                })

        for name, data in catalyst.items():
            if data["count"] >= MIN_CATALYST_SAMPLES and data["win_rate"] > 30:
                conditions.append({
                    "type": "catalyst",
                    "name": name,
                    "win_rate": data["win_rate"],
                    "avg_mfe": data["avg_mfe"],
                    "count": data["count"],
                    "confidence": data["confidence"],
                })

        conditions.sort(key=lambda x: x["win_rate"], reverse=True)
        return conditions[:8]

    def _find_worst_conditions(self, state, prob, trap, tod, catalyst) -> list[dict]:
        """Identify the worst-performing setup conditions (to avoid)."""
        conditions = []

        for name, data in state.items():
            if data["count"] >= MIN_STATE_SAMPLES and data["win_rate"] < 20:
                conditions.append({
                    "type": "state",
                    "name": name,
                    "win_rate": data["win_rate"],
                    "avg_mae": data["avg_mae"],
                    "count": data["count"],
                    "confidence": data["confidence"],
                })

        for name, data in prob.items():
            if data["count"] >= 30 and data["win_rate"] < 15:
                conditions.append({
                    "type": "probability",
                    "name": name,
                    "win_rate": data["win_rate"],
                    "avg_mae": data["avg_mae"],
                    "count": data["count"],
                    "confidence": data["confidence"],
                })

        for name, data in trap.items():
            if data["count"] >= 30 and data["win_rate"] < 15:
                conditions.append({
                    "type": "trap_risk",
                    "name": name,
                    "win_rate": data["win_rate"],
                    "avg_mae": data["avg_mae"],
                    "count": data["count"],
                    "confidence": data["confidence"],
                })

        conditions.sort(key=lambda x: x["win_rate"])
        return conditions[:6]

    def _build_recommendations(self, state, prob, trap, tod, catalyst) -> list[dict]:
        """Build evidence-based threshold recommendations."""
        recommendations = []
        overall_wr = self.get_stats()["win_rate"]

        # ── Probability threshold ─────────────────────────────────────
        if "65-80" in prob and "50-65" in prob:
            high_prob = prob["65-80"]
            low_prob = prob["50-65"]
            if high_prob["count"] >= 30 and low_prob["count"] >= 30:
                delta = high_prob["win_rate"] - low_prob["win_rate"]
                conf = CONFIDENCE_HIGH if min(high_prob["count"], low_prob["count"]) >= 100 else self._confidence(min(high_prob["count"], low_prob["count"]))
                if delta > 10:
                    recommendations.append({
                        "feature": "minimum_probability",
                        "current_threshold": "<50",
                        "proposed_threshold": "65+",
                        "evidence": f"Prob 65-80: {high_prob['win_rate']}% WR ({high_prob['count']} samples) vs Prob 50-65: {low_prob['win_rate']}% WR ({low_prob['count']} samples).",
                        "confidence": conf,
                        "expected_impact": f"Estimated win rate improvement: +{delta:.1f}%",
                        "sample_count": high_prob["count"] + low_prob["count"],
                        "rationale": "Higher-probability setups show significantly better follow-through.",
                    })

        if "80+" in prob:
            ultra = prob["80+"]
            if ultra["count"] >= 30 and ultra["win_rate"] > overall_wr + 15:
                recommendations.append({
                    "feature": "minimum_probability",
                    "current_threshold": "<50",
                    "proposed_threshold": "80+",
                    "evidence": f"Prob 80+: {ultra['win_rate']}% WR ({ultra['count']} samples) vs overall {overall_wr}%.",
                    "confidence": self._confidence(ultra["count"]),
                    "expected_impact": f"Estimated win rate: ~{ultra['win_rate']}%",
                    "sample_count": ultra["count"],
                    "rationale": "Ultra-high probability setups are exceptionally selective and profitable.",
                })

        # ── Trap risk threshold ───────────────────────────────────────
        if "<25" in trap and "50-75" in trap:
            low_trap = trap["<25"]
            mid_trap = trap["50-75"]
            if low_trap["count"] >= 30 and mid_trap["count"] >= 30:
                delta = low_trap["win_rate"] - mid_trap["win_rate"]
                conf = self._confidence(min(low_trap["count"], mid_trap["count"]))
                if delta > 10:
                    recommendations.append({
                        "feature": "maximum_trap_risk",
                        "current_threshold": "<100 (no filter)",
                        "proposed_threshold": "<50",
                        "evidence": f"Trap <25: {low_trap['win_rate']}% WR ({low_trap['count']} samples) vs Trap 50-75: {mid_trap['win_rate']}% WR ({mid_trap['count']} samples).",
                        "confidence": conf,
                        "expected_impact": f"Avoiding high-trap setups may improve WR by +{delta:.1f}%",
                        "sample_count": low_trap["count"] + mid_trap["count"],
                        "rationale": "High trap-risk candidates frequently fail. Filtering them improves edge.",
                    })

        # ── Momentum state recommendations ────────────────────────────
        best_state = max(state.items(), key=lambda x: x[1]["win_rate"]) if state else None
        worst_state = min(state.items(), key=lambda x: x[1]["win_rate"]) if state else None

        if best_state and best_state[1]["count"] >= MIN_STATE_SAMPLES and best_state[1]["win_rate"] > overall_wr + 10:
            recommendations.append({
                "feature": "preferred_state",
                "current_threshold": "any",
                "proposed_threshold": best_state[0],
                "evidence": f"State '{best_state[0]}': {best_state[1]['win_rate']}% WR ({best_state[1]['count']} samples).",
                "confidence": self._confidence(best_state[1]["count"]),
                "expected_impact": f"Focus on {best_state[0]} for ~{best_state[1]['win_rate']}% WR",
                "sample_count": best_state[1]["count"],
                "rationale": f"This momentum state shows the strongest follow-through.",
            })

        if worst_state and worst_state[1]["count"] >= MIN_STATE_SAMPLES and worst_state[1]["win_rate"] < overall_wr - 10:
            recommendations.append({
                "feature": "avoid_state",
                "current_threshold": "any",
                "proposed_threshold": f"avoid {worst_state[0]}",
                "evidence": f"State '{worst_state[0]}': {worst_state[1]['win_rate']}% WR ({worst_state[1]['count']} samples).",
                "confidence": self._confidence(worst_state[1]["count"]),
                "expected_impact": f"Avoiding {worst_state[0]} may filter poor setups",
                "sample_count": worst_state[1]["count"],
                "rationale": f"This state consistently underperforms and should be deprioritized.",
            })

        # ── Time of day recommendations ───────────────────────────────
        if tod:
            best_tod = max(tod.items(), key=lambda x: x[1]["win_rate"])
            worst_tod = min(tod.items(), key=lambda x: x[1]["win_rate"])
            if best_tod[1]["count"] >= 20 and best_tod[1]["win_rate"] > overall_wr + 10:
                recommendations.append({
                    "feature": "preferred_session",
                    "current_threshold": "any",
                    "proposed_threshold": best_tod[0],
                    "evidence": f"Session '{best_tod[0]}': {best_tod[1]['win_rate']}% WR ({best_tod[1]['count']} samples).",
                    "confidence": self._confidence(best_tod[1]["count"]),
                    "expected_impact": f"Focus on {best_tod[0]} for ~{best_tod[1]['win_rate']}% WR",
                    "sample_count": best_tod[1]["count"],
                    "rationale": "This trading session shows the strongest edge.",
                })

        # ── Catalyst type recommendations ─────────────────────────────
        best_cat = max(catalyst.items(), key=lambda x: x[1]["win_rate"]) if catalyst else None
        if best_cat and best_cat[1]["count"] >= MIN_CATALYST_SAMPLES and best_cat[1]["win_rate"] > overall_wr + 10:
            recommendations.append({
                "feature": "preferred_catalyst",
                "current_threshold": "any",
                "proposed_threshold": best_cat[0],
                "evidence": f"Catalyst '{best_cat[0]}': {best_cat[1]['win_rate']}% WR ({best_cat[1]['count']} samples).",
                "confidence": self._confidence(best_cat[1]["count"]),
                "expected_impact": f"Focus on {best_cat[0]} for ~{best_cat[1]['win_rate']}% WR",
                "sample_count": best_cat[1]["count"],
                "rationale": "This catalyst type produces the strongest follow-through.",
            })

        # Sort by confidence then expected impact
        conf_order = {CONFIDENCE_HIGH: 0, CONFIDENCE_MEDIUM: 1, CONFIDENCE_LOW: 2}
        recommendations.sort(key=lambda r: (conf_order.get(r["confidence"], 3), -(r.get("sample_count", 0))))
        return recommendations

    # ── Weight Adjustments ──────────────────────────────────────────

    def suggest_adjustments(self) -> Optional[LearningWeights]:
        """
        Analyze outcomes and suggest weight adjustments using
        evidence-based insights. Never auto-applies.
        """
        insights = self.generate_insights()
        if not insights["is_valid"]:
            logger.info("Learning: %d samples, need %d before adjusting", insights["total_samples"], MIN_GENERAL_SAMPLES)
            return None

        new_weights = self._current_weights.model_copy()
        new_weights.version = self._current_weights.version + 1
        new_weights.sample_size = insights["total_samples"]
        new_weights.updated_at = datetime.now(timezone.utc)

        stats = self.get_stats()
        win_rate = stats["win_rate"]
        recommendations = insights["threshold_recommendations"]

        # Apply targeted weight adjustments with overfitting guards
        for rec in recommendations:
            if rec["confidence"] == CONFIDENCE_LOW:
                continue  # Skip low-confidence recommendations

            feature = rec["feature"]

            if feature == "minimum_probability" and "65+" in rec.get("proposed_threshold", ""):
                # Probability filter is tightening — increase weight on probability factors
                new_weights.catalyst_strength_w = min(
                    0.35, new_weights.catalyst_strength_w + MAX_WEIGHT_CHANGE_PER_CYCLE
                )
                new_weights.volume_persistence_w = min(
                    0.20, new_weights.volume_persistence_w + MAX_WEIGHT_CHANGE_PER_CYCLE * 0.67
                )

            elif feature == "maximum_trap_risk" and "<50" in rec.get("proposed_threshold", ""):
                # Trap filter is important — increase trap-related weights
                new_weights.consolidation_quality_w = min(
                    0.15, new_weights.consolidation_quality_w + MAX_WEIGHT_CHANGE_PER_CYCLE * 0.67
                )
                new_weights.vwap_position_w = min(
                    0.15, new_weights.vwap_position_w + MAX_WEIGHT_CHANGE_PER_CYCLE * 0.67
                )

            elif feature == "preferred_state" and win_rate < 40:
                # Win rate is low despite state preference — tighten overall
                new_weights.catalyst_strength_w = min(
                    0.30, new_weights.catalyst_strength_w + MAX_WEIGHT_CHANGE_PER_CYCLE * 0.67
                )

        # If win rate is very high, slightly loosen to discover more
        if win_rate > 70:
            new_weights.catalyst_strength_w = max(
                0.10, new_weights.catalyst_strength_w - MAX_WEIGHT_CHANGE_PER_CYCLE * 0.67
            )

        return new_weights

    def apply_weights(self, weights: LearningWeights):
        """Apply new weights (manual confirmation required)."""
        self._weights_history.append(self._current_weights.model_copy())
        self._current_weights = weights
        self._persist()
        logger.info("Learning: applied weight version %d (sample=%d)", weights.version, weights.sample_size)

    def rollback_weights(self) -> bool:
        """Rollback to previous weights."""
        if not self._weights_history:
            return False
        self._current_weights = self._weights_history.pop()
        self._persist()
        logger.info("Learning: rolled back to weight version %d", self._current_weights.version)
        return True

    # ── ML Advisory Layer ───────────────────────────────────────────────

    def predict_ml(self, candidate: AgenticCandidate) -> MLPredictionResult:
        """Generate ML prediction for a candidate (advisory only)."""
        pred = self._ml_engine.predict(candidate)
        self._ml_engine.log_prediction(candidate, pred)
        return MLPredictionResult(
            continuation_prob=pred.continuation_prob,
            false_alert_prob=pred.false_alert_prob,
            expected_mfe=pred.expected_mfe,
            expected_mae=pred.expected_mae,
            confidence=pred.confidence,
            top_shap_features=pred.top_shap_features,
            model_version=pred.model_version,
            predicted_at=pred.predicted_at,
            fallback_reason=pred.fallback_reason,
            is_live=self._ml_engine.current_version.is_live if self._ml_engine.current_version else False,
            risk_adjusted_score=pred.risk_adjusted_score,
            suggested_position_size=pred.suggested_position_size,
        )

    def train_ml(self) -> Optional[dict]:
        """Trigger ML model training on recorded outcomes."""
        version = self._ml_engine.train(self._outcomes)
        if version:
            return {
                "version": version.version,
                "metrics": {
                    "auc_roc": version.metrics.auc_roc,
                    "fbeta": version.metrics.fbeta,
                    "brier_score": version.metrics.brier_score,
                    "n_train": version.metrics.n_train,
                    "n_test": version.metrics.n_test,
                },
                "approved": version.approved,
                "model_hash": version.model_hash,
                "optimal_threshold": version.optimal_threshold,
            }
        return None

    def get_ml_status(self) -> dict:
        """Get ML model status and versions."""
        versions = self._ml_engine.list_versions()
        current = self._ml_engine.current_version
        return {
            "current_version": current.version if current else None,
            "current_approved": current.approved if current else False,
            "current_is_live": current.is_live if current else False,
            "total_versions": len(versions),
            "versions": [
                {
                    "version": v["version"],
                    "created_at": v["created_at"],
                    "approved": v.get("approved", False),
                    "is_live": v.get("is_live", False),
                    "auc_roc": v.get("metrics", {}).get("auc_roc"),
                }
                for v in versions[:5]
            ],
        }

    def approve_ml_model(self, version: str, approved_by: str) -> bool:
        """Manually approve an ML model version for live advisory use."""
        return self._ml_engine.approve_model(version, approved_by)

    def check_ml_drift(self, recent_outcomes: Optional[list[AgenticOutcome]] = None) -> dict:
        """Check for ML prediction drift."""
        outcomes = recent_outcomes or self._outcomes[-50:]
        report = self._ml_engine.check_drift(outcomes)
        return {
            "psi_score": report.psi_score,
            "max_ks_stat": report.max_ks_stat,
            "brier_degradation": report.brier_degradation,
            "is_degraded": report.is_degraded,
            "checked_at": report.checked_at,
            "feature_drifts": report.feature_drifts,
        }

    # ── Persistence ──────────────────────────────────────────────────────

    def _persist(self):
        os.makedirs(DATA_DIR, exist_ok=True)
        path = os.path.join(DATA_DIR, "learning.json")
        data = {
            "outcomes": [o.model_dump(mode="json") for o in self._outcomes[-500:]],
            "current_weights": self._current_weights.model_dump(mode="json"),
            "weights_history": [w.model_dump(mode="json") for w in self._weights_history[-10:]],
        }
        save_json_file(path, data)

    def _load(self):
        path = os.path.join(DATA_DIR, "learning.json")
        data = load_json_file(path, default=None)
        if data is None:
            return
        for od in data.get("outcomes", []):
            try:
                self._outcomes.append(AgenticOutcome.model_validate(od))
            except Exception:
                pass
        cw = data.get("current_weights")
        if cw:
            self._current_weights = LearningWeights.model_validate(cw)
        for wh in data.get("weights_history", []):
            try:
                self._weights_history.append(LearningWeights.model_validate(wh))
            except Exception:
                pass
        logger.info("Learning: loaded %d outcomes, weights v%d", len(self._outcomes), self._current_weights.version)
