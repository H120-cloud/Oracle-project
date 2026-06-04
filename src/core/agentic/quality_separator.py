"""Winner vs Loser Quality Separator Engine — V13"""
from __future__ import annotations
import json, logging, math, os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from src.core.agentic.models import AgenticCandidate

logger = logging.getLogger(__name__)
DATA_DIR = Path(os.environ.get("AGENTIC_DATA_DIR", "data/agentic"))

MIN_TOTAL_OUTCOMES = 100
MIN_PER_CATALYST = 30
MIN_PER_TIME_BUCKET = 30
MAX_ADJUSTMENT = 15.0
WINNER_CLASSES = {"clean_expansion", "second_leg_continuation", "clean_continuation", "partial"}
LOSER_CLASSES = {"failed_catalyst", "trap_move", "sell_the_news", "failed", "dead"}


class QualityDecision(str, Enum):
    BOOST = "boost"
    ALLOW = "allow"
    DOWNGRADE = "downgrade"
    BLOCK = "block"
    ALLOW_NEUTRAL = "allow_neutral"


@dataclass
class FeatureContribution:
    feature_name: str
    winner_score: float = 0.0
    loser_score: float = 0.0
    net_contribution: float = 0.0
    sample_size: int = 0
    confidence: str = "low"


@dataclass
class QualitySeparatorResult:
    quality_separator_score: float = 50.0
    winner_similarity_score: float = 50.0
    loser_similarity_score: float = 50.0
    quality_decision: QualityDecision = QualityDecision.ALLOW_NEUTRAL
    base_probability: float = 0.0
    quality_adjustment: float = 0.0
    final_probability_after_quality: float = 0.0
    quality_reasons: list[str] = field(default_factory=list)
    quality_warnings: list[str] = field(default_factory=list)
    feature_contributions: list[FeatureContribution] = field(default_factory=list)
    data_sufficient: bool = False
    total_historical_outcomes: int = 0


class QualitySeparatorEngine:
    def __init__(self, data_dir: str | Path = DATA_DIR):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._outcomes: list[dict] = []
        self._winner_profiles: dict = {}
        self._loser_profiles: dict = {}
        self._profiles_built = False
        self._load_and_build()

    def _load_and_build(self):
        outcomes_path = self.data_dir / "agentic_outcomes.json"
        if outcomes_path.exists():
            try:
                with open(outcomes_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self._outcomes.extend(data if isinstance(data, list) else [data])
            except Exception as e:
                logger.warning("Failed to load outcomes: %s", e)

        events_path = self.data_dir / "historical_catalyst_events.json"
        if events_path.exists():
            try:
                with open(events_path, "r", encoding="utf-8") as f:
                    events_data = json.load(f)
                    for e in (events_data if isinstance(events_data, list) else [events_data]):
                        if e.get("outcome"):
                            self._outcomes.append(self._normalize_event(e))
            except Exception as e:
                logger.warning("Failed to load events: %s", e)

        if len(self._outcomes) >= MIN_TOTAL_OUTCOMES:
            self._build_profiles()
        else:
            logger.info("Insufficient outcomes: %d/%d", len(self._outcomes), MIN_TOTAL_OUTCOMES)

    def _normalize_event(self, event: dict) -> dict:
        oc = event.get("outcome", {})
        fs = event.get("feature_snapshot", {}) or {}
        return {
            "outcome_class": oc.get("outcome_class", "no_reaction"),
            "catalyst_type": event.get("catalyst_type", "other"),
            "float_category": fs.get("float_bucket", "normal"),
            "time_of_day": event.get("time_of_day_bucket", "midday"),
            "momentum_state": fs.get("momentum_state", "initial_spike"),
            "trap_risk": fs.get("trap_risk_score", 0),
            "volume_persistence": fs.get("volume_persistence_pct", 0),
            "vwap_reclaimed": fs.get("vwap_reclaimed", False),
            "catalyst_strength": fs.get("catalyst_strength", 50),
            "mfe_pct": oc.get("max_favorable_excursion_pct", 0),
            "mae_pct": oc.get("max_adverse_excursion_pct", 0),
        }

    def _build_profiles(self):
        winners = [o for o in self._outcomes if o.get("outcome_class") in WINNER_CLASSES]
        losers = [o for o in self._outcomes if o.get("outcome_class") in LOSER_CLASSES]
        if len(winners) < 10 or len(losers) < 10:
            logger.warning("Too few winners (%d) or losers (%d)", len(winners), len(losers))
            return
        self._winner_profiles = self._compute_dist(winners)
        self._loser_profiles = self._compute_dist(losers)
        self._profiles_built = True
        logger.info("Profiles built: %d winners, %d losers", len(winners), len(losers))

    def _compute_dist(self, outcomes: list[dict]) -> dict:
        dist = {}
        numerical = ["trap_risk", "volume_persistence", "catalyst_strength", "mfe_pct", "mae_pct"]
        for feat in numerical:
            vals = [o.get(feat, 0) for o in outcomes if o.get(feat) is not None]
            if vals:
                mean = sum(vals) / len(vals)
                std = math.sqrt(sum((v - mean) ** 2 for v in vals) / len(vals)) if len(vals) > 1 else 1.0
                dist[feat] = {"mean": mean, "std": max(std, 0.01), "count": len(vals)}
        categorical = ["catalyst_type", "float_category", "time_of_day", "momentum_state"]
        for feat in categorical:
            counts = {}
            for o in outcomes:
                val = o.get(feat, "unknown")
                counts[val] = counts.get(val, 0) + 1
            total = sum(counts.values())
            dist[feat] = {"distribution": {k: v / total for k, v in counts.items()}, "count": total}
        for feat in ["vwap_reclaimed"]:
            total = len(outcomes)
            dist[feat] = {"true_rate": sum(1 for o in outcomes if o.get(feat)) / total if total else 0.5, "count": total}
        return dist

    def _feature_score(self, name: str, value: Any, w_dist: dict, l_dist: dict) -> FeatureContribution:
        fc = FeatureContribution(feature_name=name)
        if name not in w_dist or name not in l_dist:
            return fc
        w = w_dist[name]
        l = l_dist[name]
        fc.sample_size = min(w.get("count", 0), l.get("count", 0))
        if fc.sample_size < 10:
            return fc
        if "mean" in w:
            val = float(value or 0)
            w_d = abs(val - w["mean"]) / w["std"]
            l_d = abs(val - l["mean"]) / l["std"]
            fc.winner_score = max(0, min(100, 100 - w_d * 25))
            fc.loser_score = max(0, min(100, 100 - l_d * 25))
        elif "distribution" in w:
            val = str(value or "unknown")
            fc.winner_score = w["distribution"].get(val, 0) * 100
            fc.loser_score = l["distribution"].get(val, 0) * 100
        elif "true_rate" in w:
            val = bool(value)
            fc.winner_score = (w["true_rate"] if val else 1 - w["true_rate"]) * 100
            fc.loser_score = (l["true_rate"] if val else 1 - l["true_rate"]) * 100
        fc.net_contribution = fc.winner_score - fc.loser_score
        fc.confidence = "high" if fc.sample_size >= 50 else "medium" if fc.sample_size >= 20 else "low"
        return fc

    def evaluate(self, candidate: AgenticCandidate, base_probability: float) -> QualitySeparatorResult:
        result = QualitySeparatorResult(base_probability=base_probability)
        result.total_historical_outcomes = len(self._outcomes)

        if not self._profiles_built or len(self._outcomes) < MIN_TOTAL_OUTCOMES:
            result.quality_decision = QualityDecision.ALLOW_NEUTRAL
            result.quality_reasons.append(f"Insufficient data ({len(self._outcomes)}/{MIN_TOTAL_OUTCOMES}). Pass-through.")
            result.final_probability_after_quality = base_probability
            return result

        result.data_sufficient = True
        ct = candidate.catalyst.catalyst_type.value
        ct_count = sum(1 for o in self._outcomes if o.get("catalyst_type") == ct)
        if ct_count < MIN_PER_CATALYST:
            result.quality_warnings.append(f"Only {ct_count} {ct} samples (need {MIN_PER_CATALYST}).")

        tod = candidate.time_of_day.session.value
        tod_count = sum(1 for o in self._outcomes if o.get("time_of_day") == tod)
        if tod_count < MIN_PER_TIME_BUCKET:
            result.quality_warnings.append(f"Only {tod_count} {tod} samples (need {MIN_PER_TIME_BUCKET}).")

        features = {
            "catalyst_type": ct,
            "catalyst_strength": candidate.catalyst.strength_score,
            "float_category": candidate.float_intel.float_category.value,
            "time_of_day": tod,
            "momentum_state": candidate.momentum.state.value,
            "trap_risk": candidate.trap.trap_risk_score,
            "volume_persistence": candidate.momentum.volume_persistence_pct,
            "vwap_reclaimed": candidate.momentum.vwap_reclaimed,
        }
        weights = {
            "catalyst_type": 0.15, "catalyst_strength": 0.10, "float_category": 0.10,
            "time_of_day": 0.10, "momentum_state": 0.15, "trap_risk": 0.15,
            "volume_persistence": 0.10, "vwap_reclaimed": 0.10,
        }
        reasons, warnings = [], []
        weighted_winner, weighted_loser, total_weight = 0.0, 0.0, 0.0

        for feat_name, val in features.items():
            fc = self._feature_score(feat_name, val, self._winner_profiles, self._loser_profiles)
            result.feature_contributions.append(fc)
            weight = weights.get(feat_name, 0.05)
            total_weight += weight
            weighted_winner += fc.winner_score * weight
            weighted_loser += fc.loser_score * weight
            if fc.confidence in ("medium", "high"):
                if fc.net_contribution > 30:
                    reasons.append(f"{feat_name}: winner-like ({fc.winner_score:.0f}% vs {fc.loser_score:.0f}%)")
                elif fc.net_contribution < -30:
                    warnings.append(f"{feat_name}: loser-like ({fc.loser_score:.0f}% vs {fc.winner_score:.0f}%)")
                elif fc.net_contribution > 10:
                    reasons.append(f"{feat_name}: mild winner")
                elif fc.net_contribution < -10:
                    warnings.append(f"{feat_name}: mild loser")

        if total_weight > 0:
            weighted_winner /= total_weight
            weighted_loser /= total_weight

        result.winner_similarity_score = round(weighted_winner, 1)
        result.loser_similarity_score = round(weighted_loser, 1)
        result.quality_reasons = reasons
        result.quality_warnings = warnings
        result.quality_separator_score = round(max(0, min(100, 50 + (weighted_winner - weighted_loser) * 0.5)), 1)

        adjustment = 0.0
        decision = QualityDecision.ALLOW
        q = result.quality_separator_score
        w, l = result.winner_similarity_score, result.loser_similarity_score

        if q >= 75 and w >= 70 and base_probability >= 60:
            adjustment = min(MAX_ADJUSTMENT, (q - 50) * 0.4)
            decision = QualityDecision.BOOST
            result.quality_reasons.append(f"Q={q:.0f} strongly winner-like. Boost +{adjustment:.1f}.")
        elif q <= 35 and l >= 65:
            adjustment = -min(MAX_ADJUSTMENT, (50 - q) * 0.5)
            decision = QualityDecision.DOWNGRADE if base_probability >= 50 else QualityDecision.BLOCK
            result.quality_warnings.append(f"Q={q:.0f} strongly loser-like. Adjust {adjustment:.1f}.")
        elif q <= 45 and l >= 55:
            adjustment = -min(MAX_ADJUSTMENT * 0.5, (50 - q) * 0.3)
            decision = QualityDecision.DOWNGRADE
            result.quality_warnings.append(f"Q={q:.0f} mildly loser-like. Downgrade {adjustment:.1f}.")
        elif q >= 65 and w >= 60 and 55 <= base_probability <= 85:
            adjustment = min(MAX_ADJUSTMENT * 0.5, (q - 50) * 0.3)
            decision = QualityDecision.BOOST
            result.quality_reasons.append(f"Q={q:.0f} mildly winner-like. Boost +{adjustment:.1f}.")

        if candidate.trap.trap_risk_score > 60 and l > 60:
            decision = QualityDecision.BLOCK
            adjustment = -MAX_ADJUSTMENT
            result.quality_warnings.append(f"Trap risk {candidate.trap.trap_risk_score:.0f}% + loser sim {l:.0f}% = BLOCK")

        result.quality_adjustment = round(adjustment, 1)
        result.final_probability_after_quality = round(max(0, min(100, base_probability + adjustment)), 1)
        result.quality_decision = decision

        # Confidence level based on quality score
        fp = result.final_probability_after_quality
        if fp >= 80:
            result.quality_confidence = "very_high"
        elif fp >= 65:
            result.quality_confidence = "high"
        elif fp >= 50:
            result.quality_confidence = "medium"
        else:
            result.quality_confidence = "low"

        return result

    def get_profiles_summary(self) -> dict:
        if not self._profiles_built:
            return {"status": "insufficient_data", "total_outcomes": len(self._outcomes)}
        return {
            "status": "ready",
            "total_outcomes": len(self._outcomes),
            "winner_features": {k: {"count": v.get("count", 0)} for k, v in self._winner_profiles.items()},
            "loser_features": {k: {"count": v.get("count", 0)} for k, v in self._loser_profiles.items()},
        }

    def get_feature_report(self) -> dict:
        """Return a report of which features most distinguish winners from losers."""
        if not self._profiles_built:
            return {"status": "insufficient_data"}
        report = []
        for feat_name in self._winner_profiles:
            if feat_name not in self._loser_profiles:
                continue
            w = self._winner_profiles[feat_name]
            l = self._loser_profiles[feat_name]
            if "mean" in w and "mean" in l:
                diff = abs(w["mean"] - l["mean"])
                report.append({
                    "feature": feat_name,
                    "winner_mean": round(w["mean"], 2),
                    "loser_mean": round(l["mean"], 2),
                    "difference": round(diff, 2),
                    "winner_count": w.get("count", 0),
                    "loser_count": l.get("count", 0),
                })
            elif "distribution" in w:
                # Find most divergent category
                max_div = 0
                max_cat = ""
                for cat in set(list(w["distribution"].keys()) + list(l["distribution"].keys())):
                    div = abs(w["distribution"].get(cat, 0) - l["distribution"].get(cat, 0))
                    if div > max_div:
                        max_div = div
                        max_cat = cat
                report.append({
                    "feature": feat_name,
                    "most_divergent_category": max_cat,
                    "divergence": round(max_div, 3),
                    "winner_count": w.get("count", 0),
                    "loser_count": l.get("count", 0),
                })
        report.sort(key=lambda x: x.get("difference", x.get("divergence", 0)), reverse=True)
        return {"status": "ready", "features": report}
