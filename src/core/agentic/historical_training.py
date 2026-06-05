"""Historical Catalyst Training Controller"""
from __future__ import annotations
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.utils.atomic_json import save_json_file

from src.core.agentic.historical_dataset_builder import HistoricalDatasetBuilder
from src.core.agentic.historical_features import LookbackFeatureExtractor
from src.core.agentic.historical_outcomes import OutcomeLabeler
from src.core.agentic.historical_pattern_discovery import PatternDiscoveryEngine
from src.core.agentic.historical_calibration import CalibrationEngine
from src.core.agentic.historical_models import TrainingMode, HistoricalOutcome

logger = logging.getLogger(__name__)
from src.utils.data_paths import agentic_data_dir as _agentic_data_dir
DATA_DIR = str(_agentic_data_dir())

class HistoricalTrainingController:
    def __init__(self, data_dir: str = DATA_DIR):
        self.data_dir = data_dir
        os.makedirs(self.data_dir, exist_ok=True)
        self.dataset_builder = HistoricalDatasetBuilder(data_dir=data_dir)
        self.pattern_engine = PatternDiscoveryEngine()
        self.calibration_engine = CalibrationEngine(data_dir=data_dir)
        self._last_run_report: Optional[Dict[str, Any]] = None

    def run_training(self, mode: TrainingMode = TrainingMode.RECOMMEND_ONLY,
                     approved_features: Optional[List[str]] = None,
                     dry_run: bool = False) -> Dict[str, Any]:
        start_time = datetime.now(timezone.utc)
        logger.info("Starting historical training run (mode=%s)", mode.value)
        events = self.dataset_builder.get_events(limit=5000)
        total_events = len(events)
        for event in events:
            if not event.feature_snapshot:
                features = LookbackFeatureExtractor.extract(event)
                self.dataset_builder.update_event(event.id, feature_snapshot=features)
        events = self.dataset_builder.get_events(limit=5000)
        resolved_events = [e for e in events if e.outcome is not None]
        buckets = self.pattern_engine.analyze(resolved_events)
        insights = self.pattern_engine.get_insights()
        recommendations = self.calibration_engine.generate_recommendations(
            buckets=buckets, insights=insights, total_events=len(resolved_events))
        apply_result = self.calibration_engine.apply_recommendations(
            mode=mode, approvals=approved_features)
        report = {
            "run_id": f"run_{start_time.strftime('%Y%m%d_%H%M%S')}",
            "mode": mode.value, "timestamp": start_time.isoformat(),
            "total_events": total_events,
            "resolved_events": len(resolved_events),
            "pattern_buckets": len(buckets),
            "insights": len(insights),
            "recommendations": len(recommendations),
            "recommendation_details": [r.model_dump(mode="json") for r in recommendations],
            "apply_result": apply_result,
            "current_weights": self.calibration_engine.get_current_weights().model_dump(mode="json"),
        }
        self._save_report(report)
        self._last_run_report = report
        return report

    def label_event(self, event_id: str,
                    price_path: Optional[List[Dict[str, Any]]] = None) -> Optional[HistoricalOutcome]:
        event = self.dataset_builder.get_event(event_id)
        if not event:
            return None
        outcome = OutcomeLabeler.label(event, price_path)
        self.dataset_builder.update_event(event_id, outcome=outcome.model_dump(mode="json"))
        return outcome

    def get_status(self) -> Dict[str, Any]:
        stats = self.dataset_builder.stats()
        weights = self.calibration_engine.get_current_weights()
        pending = self.calibration_engine.get_pending_weights()
        return {
            "dataset": stats,
            "current_weights": weights.model_dump(mode="json"),
            "pending_weights": pending.model_dump(mode="json") if pending else None,
            "pending_recommendations": len(self.calibration_engine.get_recommendations()),
            "last_run_report": self._last_run_report,
        }

    def get_insights(self) -> Dict[str, Any]:
        return {
            "insights": [i.model_dump(mode="json") for i in self.pattern_engine.get_insights()],
            "top_patterns": [b.model_dump(mode="json") for b in self.pattern_engine.find_best_patterns()],
            "worst_patterns": [b.model_dump(mode="json") for b in self.pattern_engine.find_worst_patterns()],
        }

    def get_recommendations(self) -> List[Dict[str, Any]]:
        return [r.model_dump(mode="json") for r in self.calibration_engine.get_recommendations()]

    def apply_approved(self, approved_features: List[str]) -> Dict[str, Any]:
        return self.calibration_engine.apply_recommendations(
            mode=TrainingMode.APPROVED_APPLY, approvals=approved_features)

    def rollback(self) -> bool:
        return self.calibration_engine.rollback()

    def _report_path(self, run_id: str) -> str:
        return os.path.join(self.data_dir, f"training_report_{run_id}.json")

    def _save_report(self, report: Dict[str, Any]) -> None:
        save_json_file(self._report_path(report["run_id"]), report)

    def get_report(self, run_id: str) -> Optional[Dict[str, Any]]:
        try:
            with open(self._report_path(run_id), "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None

    def analyze_missed_opportunities(self, missed: list[dict]) -> list[dict]:
        """
        Cross-reference missed runners against historical winning patterns.

        For each missed ticker, check if its profile matches historical
        clean-expansion or second-leg patterns and generate fix recommendations.
        """
        results = []
        events = self.dataset_builder.get_events(limit=5000)
        resolved = [e for e in events if e.outcome is not None]
        if len(resolved) < 10:
            return []

        # Compute historical win rate by float bucket + catalyst type
        win_profiles = {}
        for e in resolved:
            fs = e.feature_snapshot or {}
            key = (e.catalyst_type.value, fs.get("float_bucket", "unknown"))
            if key not in win_profiles:
                win_profiles[key] = {"total": 0, "wins": 0, "mfe_sum": 0.0}
            win_profiles[key]["total"] += 1
            oc = e.outcome.get("outcome_class", "") if isinstance(e.outcome, dict) else getattr(e.outcome, "outcome_class", "")
            if oc in ("clean_expansion", "second_leg_continuation"):
                win_profiles[key]["wins"] += 1
            mfe = e.outcome.get("max_favorable_excursion_pct", 0) if isinstance(e.outcome, dict) else getattr(e.outcome, "max_favorable_excursion_pct", 0) or 0
            win_profiles[key]["mfe_sum"] += mfe

        for m in missed:
            ticker = m.get("ticker", "")
            move_pct = m.get("move_pct", 0)
            prob = m.get("candidate_probability_at_time")
            rejection = m.get("rejection_reason", "")
            classification = m.get("classification", "")

            # Try to find the closest historical profile
            best_match = None
            best_rate = 0.0
            for key, stats in win_profiles.items():
                rate = stats["wins"] / stats["total"] if stats["total"] > 0 else 0
                if rate > best_rate and stats["total"] >= 5:
                    best_rate = rate
                    best_match = (key, stats)

            insight = {
                "ticker": ticker,
                "move_pct": move_pct,
                "classification": classification,
                "was_rejected": classification == "rejected_wrong",
                "was_not_discovered": classification == "not_discovered",
                "was_low_score": classification == "low_score",
                "probability_at_time": prob,
                "rejection_reason": rejection,
            }

            if best_match and best_rate >= 0.4:
                (cat, fb), stats = best_match
                avg_mfe = round(stats["mfe_sum"] / stats["total"], 1)
                insight["historical_profile_match"] = f"{cat} / {fb}"
                insight["historical_win_rate"] = round(best_rate * 100, 1)
                insight["historical_avg_mfe"] = avg_mfe
                insight["matches_winners"] = True

                # Generate specific fix recommendation
                if classification == "rejected_wrong":
                    insight["recommended_fix"] = (
                        f"Missed runner had same profile as {round(best_rate * 100)}% "
                        f"of historical clean expansions ({cat}, {fb}). "
                        f"Consider loosening rejection criteria for this catalyst/float combination."
                    )
                elif classification == "not_discovered":
                    insight["recommended_fix"] = (
                        f"Not discovered but profile matches {round(best_rate * 100)}% "
                        f"historical winners. Consider expanding scanner sources for {cat} catalysts."
                    )
                elif classification == "low_score":
                    insight["recommended_fix"] = (
                        f"Scored low ({prob}%) but profile matches {round(best_rate * 100)}% "
                        f"historical winners. Review sub-score weighting for {cat} / {fb}."
                    )
                else:
                    insight["recommended_fix"] = "Historical data suggests this profile has strong precedent."
            else:
                insight["matches_winners"] = False
                insight["recommended_fix"] = "Insufficient historical data for this profile."

            results.append(insight)

        # Sort by historical win rate descending
        results.sort(key=lambda x: x.get("historical_win_rate", 0), reverse=True)
        return results
