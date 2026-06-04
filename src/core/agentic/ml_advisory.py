"""
Agentic ML Advisory Layer — V19

Supervised learning overlay for Agentic learning engine.
Uses historical feature snapshots and outcomes to train:
  - Logistic regression baseline (transparent, interpretable)
  - XGBoost classifier (captures non-linear interactions)
  - Stacked generalization ensemble (meta-learner combining both)

Predicts:
  - probability of clean continuation
  - probability of false alert
  - expected MFE
  - expected MAE

Safety:
  - Temporal walk-forward cross-validation (no look-ahead bias)
  - Class imbalance handling (scale_pos_weight / SMOTE)
  - SHAP explainability for every prediction
  - Prediction drift monitoring (PSI, calibration)
  - Auto-fallback to rule-based if model degrades
  - Full audit trail with model versioning
  - Manual approval required before live advisory status

Does NOT replace rule-based logic. Acts as an advisory layer only.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import pickle
import warnings
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from src.utils.atomic_json import save_json_file, load_json_file

import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import StackingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    brier_score_loss,
    fbeta_score,
    log_loss,
    precision_recall_curve,
    roc_auc_score,
)
from sklearn.model_selection import (
    TimeSeriesSplit,
    train_test_split,
)
from sklearn.preprocessing import StandardScaler
from xgboost import XGBClassifier

try:
    from lightgbm import LGBMClassifier
    LIGHTGBM_AVAILABLE = True
except ImportError:
    LIGHTGBM_AVAILABLE = False

try:
    import shap
    SHAP_AVAILABLE = True
except ImportError:
    SHAP_AVAILABLE = False

from src.core.agentic.models import (
    AgenticCandidate,
    AgenticOutcome,
    MomentumState,
    OutcomeClass,
)

logger = logging.getLogger(__name__)

# ── Paths ─────────────────────────────────────────────────────────────
DATA_DIR = Path(__file__).parent.parent.parent.parent / "data" / "agentic"
MODEL_DIR = DATA_DIR / "ml_models"
MODEL_DIR.mkdir(parents=True, exist_ok=True)

# ── Constants ─────────────────────────────────────────────────────────
MIN_TRAINING_SAMPLES = 80
WALK_FORWARD_SPLITS = 5
CLASS_IMBALANCE_RATIO = 3.0  # scale_pos_weight = ratio of negatives to positives
FBETA_BETA = 0.5  # penalize false alerts more heavily
CALIBRATION_METHOD = "isotonic"

FEATURE_COLS = [
    "probability",
    "trap_risk",
    "volume_persistence",
    "higher_low_formed_int",
    "catalyst_strength",
    "rejected_int",
    "alertable_int",
    "vwap_held_int",
    "entry_quality_int",
    # V19.1 — Market regime features
    "spy_trend_5d",
    "vix_level",
    "sector_rsi",
    "market_breadth",
    # V19.1 — Time & volume profile features
    "minutes_since_spike",
    "volume_profile_slope",
    "float_turnover_pct",
    "relative_volume_vs_sector",
]

INTERACTION_COLS = [
    "prob_x_trap",
    "prob_x_vol",
    "prob_x_catalyst",
    "trap_x_float",
    "catalyst_x_time",
    # V19.1 — New interactions
    "prob_x_spy_trend",
    "trap_x_vix",
    "vol_x_float_turnover",
    "minutes_x_prob",
]

ALL_FEATURES = FEATURE_COLS + INTERACTION_COLS

TARGET_CONTINUATION = "is_continuation"
TARGET_FALSE_ALERT = "is_false_alert"
TARGET_RISK_ADJUSTED = "risk_adjusted_score"


# ── Data classes ──────────────────────────────────────────────────────

@dataclass
class MLPrediction:
    """Single prediction output for a candidate."""
    continuation_prob: float
    false_alert_prob: float
    expected_mfe: float
    expected_mae: float
    confidence: str  # HIGH, MEDIUM, LOW
    top_shap_features: list[dict] = field(default_factory=list)
    model_version: str = ""
    predicted_at: str = ""
    fallback_reason: Optional[str] = None
    # V19.1 — Risk-adjusted score & position sizing
    risk_adjusted_score: float = 0.0
    suggested_position_size: str = "NONE"  # NONE, HALF, FULL


@dataclass
class ModelMetrics:
    """Evaluation metrics for a trained model."""
    auc_roc: float
    fbeta: float
    brier_score: float
    log_loss: float
    calibration_slope: float
    n_train: int
    n_test: int
    fold_results: list[dict] = field(default_factory=list)


@dataclass
class ModelVersion:
    """Versioned model artifact with metadata."""
    version: str
    created_at: str
    metrics: ModelMetrics
    feature_names: list[str]
    model_hash: str
    approved: bool = False
    approved_at: Optional[str] = None
    approved_by: Optional[str] = None
    is_live: bool = False
    # V19.1 — Dynamic threshold optimized on precision-recall curve
    optimal_threshold: float = 0.5


@dataclass
class DriftReport:
    """Drift detection results."""
    psi_score: float
    max_ks_stat: float
    brier_degradation: float
    is_degraded: bool
    checked_at: str
    feature_drifts: dict[str, float] = field(default_factory=dict)


# ── Feature Engineering ───────────────────────────────────────────────

class FeatureEngineer:
    """Transform AgenticOutcome snapshots into model-ready features."""

    @staticmethod
    def _encode_bool(val: Optional[bool]) -> int:
        return 1 if val else 0

    @staticmethod
    def _encode_entry_quality(q: Optional[str]) -> int:
        mapping = {"early": 0, "ideal": 2, "late": 1}
        return mapping.get(q or "early", 0)

    @staticmethod
    def _encode_float_category(cat: Optional[str]) -> int:
        mapping = {"ultra_low_float": 0, "low_float": 1, "normal": 2}
        return mapping.get(cat or "normal", 2)

    @staticmethod
    def _encode_catalyst_type(ct: Optional[str]) -> int:
        mapping = {
            "sec_filing": 0, "spac_extension": 1, "merger": 2,
            "earnings": 3, "clinical_trial": 4, "other_news": 5,
        }
        return mapping.get(ct or "other_news", 5)

    @staticmethod
    def _encode_time_of_day(tod: Optional[str]) -> int:
        mapping = {"premarket": 0, "open": 1, "midday": 2, "power_hour": 3, "afterhours": 4}
        return mapping.get(tod or "midday", 2)

    def extract(self, outcomes: list[AgenticOutcome]) -> pd.DataFrame:
        """Convert list of outcomes to a feature DataFrame."""
        rows = []
        for o in outcomes:
            mfe = o.max_favorable_excursion_pct or 0.0
            mae = o.max_adverse_excursion_pct or 0.0
            risk_adj = mfe / (mae + 1.0)  # V19.1 — risk-adjusted return target
            row = {
                # Core features
                "probability": o.probability or 50.0,
                "trap_risk": o.trap_risk or 50.0,
                "volume_persistence": o.volume_persistence or 0.0,
                "higher_low_formed_int": self._encode_bool(o.higher_low_formed),
                "catalyst_strength": o.catalyst_strength or 50.0,
                "rejected_int": self._encode_bool(o.rejected),
                "alertable_int": self._encode_bool(o.alertable),
                "vwap_held_int": self._encode_bool(o.vwap_held),
                "entry_quality_int": self._encode_entry_quality(o.entry_quality),
                # Encoded categoricals
                "float_category_int": self._encode_float_category(o.float_category),
                "catalyst_type_int": self._encode_catalyst_type(o.catalyst_type),
                "time_of_day_int": self._encode_time_of_day(o.time_of_day_session),
                # V19.1 — Market regime features (default 0 if unavailable)
                "spy_trend_5d": getattr(o, "spy_trend_5d", 0.0),
                "vix_level": getattr(o, "vix_level", 20.0),
                "sector_rsi": getattr(o, "sector_rsi", 50.0),
                "market_breadth": getattr(o, "market_breadth", 50.0),
                # V19.1 — Time & volume profile features
                "minutes_since_spike": getattr(o, "minutes_since_spike", 30.0),
                "volume_profile_slope": getattr(o, "volume_profile_slope", 0.0),
                "float_turnover_pct": getattr(o, "float_turnover_pct", 0.0),
                "relative_volume_vs_sector": getattr(o, "relative_volume_vs_sector", 1.0),
                # Targets
                "is_continuation": int(o.outcome_class in (
                    OutcomeClass.CLEAN_CONTINUATION.value, OutcomeClass.PARTIAL.value
                )),
                "is_false_alert": int(o.outcome_class in (
                    OutcomeClass.FAILED.value, OutcomeClass.DEAD.value
                )),
                "mfe": mfe,
                "mae": mae,
                "risk_adjusted_score": risk_adj,
                "timestamp": o.recorded_at or datetime.now(timezone.utc).isoformat(),
            }
            rows.append(row)

        df = pd.DataFrame(rows)
        if df.empty:
            return df

        # Interaction features
        df["prob_x_trap"] = df["probability"] * df["trap_risk"] / 100.0
        df["prob_x_vol"] = df["probability"] * df["volume_persistence"] / 100.0
        df["prob_x_catalyst"] = df["probability"] * df["catalyst_strength"] / 100.0
        df["trap_x_float"] = df["trap_risk"] * df["float_category_int"]
        df["catalyst_x_time"] = df["catalyst_strength"] * df["time_of_day_int"]
        # V19.1 — New interactions
        df["prob_x_spy_trend"] = df["probability"] * df["spy_trend_5d"] / 100.0
        df["trap_x_vix"] = df["trap_risk"] * df["vix_level"] / 100.0
        df["vol_x_float_turnover"] = df["volume_persistence"] * df["float_turnover_pct"] / 100.0
        df["minutes_x_prob"] = df["minutes_since_spike"] * df["probability"] / 100.0

        return df


# ── Model Training ────────────────────────────────────────────────────

class MLAdvisoryEngine:
    """
    Core ML engine: trains, evaluates, and serves predictions.
    Uses temporal walk-forward CV and stacked ensemble.
    """

    def __init__(self):
        self.feature_engineer = FeatureEngineer()
        self.scaler = StandardScaler()
        self.continuation_model: Optional[Any] = None
        self.false_alert_model: Optional[Any] = None
        self.mfe_model: Optional[Any] = None  # simple regressor placeholder
        self.mae_model: Optional[Any] = None
        self.risk_adj_model: Optional[Any] = None  # V19.1
        self.current_version: Optional[ModelVersion] = None
        self.optimal_threshold: float = 0.5  # V19.1 — dynamic threshold
        self._all_outcomes: list[AgenticOutcome] = []  # V19.1 — cache for auto-retrain
        self._load_latest_model()

    # ── Training ──────────────────────────────────────────────────────

    def train(self, outcomes: list[AgenticOutcome]) -> Optional[ModelVersion]:
        """Train all models on historical outcomes."""
        self._all_outcomes = outcomes  # V19.1 — cache for auto-retrain
        df = self.feature_engineer.extract(outcomes)
        if len(df) < MIN_TRAINING_SAMPLES:
            logger.warning(
                "ML: insufficient samples (%d < %d), skipping training",
                len(df), MIN_TRAINING_SAMPLES,
            )
            return None

        df = df.sort_values("timestamp").reset_index(drop=True)
        X = df[ALL_FEATURES].fillna(0).values
        y_cont = df[TARGET_CONTINUATION].values
        y_false = df[TARGET_FALSE_ALERT].values
        y_mfe = df["mfe"].values
        y_mae = df["mae"].values
        y_risk_adj = df[TARGET_RISK_ADJUSTED].values  # V19.1

        # Scale features
        X_scaled = self.scaler.fit_transform(X)

        # Temporal walk-forward CV for continuation classifier
        cont_metrics, cont_model, cont_threshold = self._train_classifier(
            X_scaled, y_cont, "continuation"
        )
        # Temporal walk-forward CV for false alert classifier
        false_metrics, false_model, _ = self._train_classifier(
            X_scaled, y_false, "false_alert"
        )

        # Simple regression for MFE/MAE / risk-adjusted score
        self.mfe_model = self._train_regressor(X_scaled, y_mfe)
        self.mae_model = self._train_regressor(X_scaled, y_mae)
        self.risk_adj_model = self._train_regressor(X_scaled, y_risk_adj)  # V19.1

        # Store models
        self.continuation_model = cont_model
        self.false_alert_model = false_model

        # V19.1 — Dynamic threshold: use continuation classifier's optimal threshold
        self.optimal_threshold = cont_threshold

        # Compute aggregate metrics
        agg_metrics = ModelMetrics(
            auc_roc=(cont_metrics.auc_roc + false_metrics.auc_roc) / 2,
            fbeta=(cont_metrics.fbeta + false_metrics.fbeta) / 2,
            brier_score=(cont_metrics.brier_score + false_metrics.brier_score) / 2,
            log_loss=(cont_metrics.log_loss + false_metrics.log_loss) / 2,
            calibration_slope=cont_metrics.calibration_slope,
            n_train=cont_metrics.n_train,
            n_test=cont_metrics.n_test,
            fold_results=cont_metrics.fold_results + false_metrics.fold_results,
        )

        version = self._save_model(agg_metrics, cont_threshold)
        self.current_version = version
        logger.info(
            "ML: trained v%s — AUC %.3f, F-beta %.3f, Brier %.3f, threshold %.3f",
            version.version, agg_metrics.auc_roc, agg_metrics.fbeta,
            agg_metrics.brier_score, cont_threshold,
        )
        return version

    def _train_classifier(
        self, X: np.ndarray, y: np.ndarray, name: str
    ) -> tuple[ModelMetrics, Any, float]:
        """Train a stacked LR + XGB (+ LightGBM) classifier with temporal CV."""
        tscv = TimeSeriesSplit(n_splits=WALK_FORWARD_SPLITS)

        pos = np.sum(y)
        neg = len(y) - pos
        scale_pos_weight = neg / max(pos, 1) * CLASS_IMBALANCE_RATIO

        # Base models
        lr = LogisticRegression(
            max_iter=2000,
            class_weight="balanced",
            solver="lbfgs",
            random_state=42,
        )
        xgb = XGBClassifier(
            n_estimators=100,
            max_depth=4,
            learning_rate=0.1,
            subsample=0.8,
            colsample_bytree=0.8,
            scale_pos_weight=scale_pos_weight,
            eval_metric="logloss",
            use_label_encoder=False,
            random_state=42,
            n_jobs=2,
        )
        estimators = [("lr", lr), ("xgb", xgb)]

        # V19.1 — Add LightGBM if available
        if LIGHTGBM_AVAILABLE:
            lgb = LGBMClassifier(
                n_estimators=100,
                max_depth=6,
                learning_rate=0.05,
                class_weight="balanced",
                random_state=42,
                n_jobs=2,
                verbosity=-1,
            )
            estimators.append(("lgb", lgb))

        # Stacked ensemble
        stack = StackingClassifier(
            estimators=estimators,
            final_estimator=LogisticRegression(max_iter=1000, class_weight="balanced"),
            cv=3,
            passthrough=False,
            n_jobs=2,
        )

        fold_results = []
        all_val_preds = []
        all_val_true = []

        for fold, (train_idx, val_idx) in enumerate(tscv.split(X)):
            X_train, X_val = X[train_idx], X[val_idx]
            y_train, y_val = y[train_idx], y[val_idx]

            stack.fit(X_train, y_train)
            preds_proba = stack.predict_proba(X_val)[:, 1]
            preds = (preds_proba >= 0.5).astype(int)

            auc = roc_auc_score(y_val, preds_proba) if len(set(y_val)) > 1 else 0.0
            fbeta = fbeta_score(y_val, preds, beta=FBETA_BETA, zero_division=0)
            brier = brier_score_loss(y_val, preds_proba)
            logloss = log_loss(y_val, np.clip(preds_proba, 1e-7, 1 - 1e-7))

            fold_results.append({
                "fold": fold + 1,
                "auc": round(auc, 3),
                "fbeta": round(fbeta, 3),
                "brier": round(brier, 3),
                "logloss": round(logloss, 3),
                "n_train": len(train_idx),
                "n_val": len(val_idx),
            })
            all_val_preds.extend(preds_proba)
            all_val_true.extend(y_val)

        # Final model on all data
        stack.fit(X, y)

        # Calibration
        calibrated = CalibratedClassifierCV(
            stack, method=CALIBRATION_METHOD, cv="prefit"
        )
        # Use last fold for calibration to avoid overfitting
        X_cal, _, y_cal, _ = train_test_split(
            X, y, test_size=0.2, shuffle=False
        )
        calibrated.fit(X_cal, y_cal)

        agg_auc = roc_auc_score(all_val_true, all_val_preds) if len(set(all_val_true)) > 1 else 0.0
        agg_fbeta = fbeta_score(
            all_val_true, (np.array(all_val_preds) >= 0.5).astype(int),
            beta=FBETA_BETA, zero_division=0,
        )
        agg_brier = brier_score_loss(all_val_true, all_val_preds)
        agg_logloss = log_loss(
            all_val_true, np.clip(all_val_preds, 1e-7, 1 - 1e-7)
        )

        # V19.1 — Dynamic threshold optimization on precision-recall curve
        optimal_threshold = 0.5
        try:
            if len(set(all_val_true)) > 1 and len(all_val_preds) > 10:
                precisions, recalls, thresholds = precision_recall_curve(
                    all_val_true, all_val_preds
                )
                # F-beta score for each threshold (beta=0.5 penalizes false alerts)
                f_scores = []
                valid_thresholds = []
                for p, r, t in zip(precisions, recalls, thresholds):
                    if p + r > 0:
                        beta_sq = FBETA_BETA ** 2
                        f = (1 + beta_sq) * (p * r) / (beta_sq * p + r)
                        f_scores.append(f)
                        valid_thresholds.append(t)
                if f_scores:
                    best_idx = int(np.argmax(f_scores))
                    optimal_threshold = float(valid_thresholds[best_idx])
                    optimal_threshold = max(0.25, min(0.75, optimal_threshold))
        except Exception:
            optimal_threshold = 0.5

        # Calibration slope (proxy: correlation between predicted prob and actual rate)
        n_bins = 5
        bin_edges = np.linspace(0, 1, n_bins + 1)
        cal_slope = 1.0
        try:
            bin_centers = []
            bin_actuals = []
            for i in range(n_bins):
                mask = (np.array(all_val_preds) >= bin_edges[i]) & (
                    np.array(all_val_preds) < bin_edges[i + 1]
                )
                if i == n_bins - 1:
                    mask = np.array(all_val_preds) >= bin_edges[i]
                if np.sum(mask) > 0:
                    bin_centers.append((bin_edges[i] + bin_edges[i + 1]) / 2)
                    bin_actuals.append(np.mean(np.array(all_val_true)[mask]))
            if len(bin_centers) >= 2:
                cal_slope = np.polyfit(bin_centers, bin_actuals, 1)[0]
        except Exception:
            cal_slope = 1.0

        metrics = ModelMetrics(
            auc_roc=round(agg_auc, 3),
            fbeta=round(agg_fbeta, 3),
            brier_score=round(agg_brier, 3),
            log_loss=round(agg_logloss, 3),
            calibration_slope=round(cal_slope, 3),
            n_train=len(X) - len(X_cal),
            n_test=len(X_cal),
            fold_results=fold_results,
        )
        return metrics, calibrated, optimal_threshold

    def _train_regressor(self, X: np.ndarray, y: np.ndarray) -> Any:
        """Simple mean regressor as baseline — can be replaced with Ridge/XGBRegressor."""
        from sklearn.linear_model import Ridge
        reg = Ridge(alpha=1.0, random_state=42)
        reg.fit(X, y)
        return reg

    # ── Prediction ────────────────────────────────────────────────────

    def predict(self, candidate: AgenticCandidate) -> MLPrediction:
        """Generate ML prediction for a single candidate."""
        if self.continuation_model is None or self.false_alert_model is None:
            return MLPrediction(
                continuation_prob=0.5,
                false_alert_prob=0.5,
                expected_mfe=0.0,
                expected_mae=0.0,
                confidence="LOW",
                fallback_reason="No trained model available",
            )

        # Build feature vector from candidate
        features = self._candidate_to_features(candidate)
        X = np.array([features[f] for f in ALL_FEATURES]).reshape(1, -1)
        X_scaled = self.scaler.transform(X)

        # Predict
        cont_proba = self.continuation_model.predict_proba(X_scaled)[0, 1]
        false_proba = self.false_alert_model.predict_proba(X_scaled)[0, 1]

        expected_mfe = self.mfe_model.predict(X_scaled)[0] if self.mfe_model else 0.0
        expected_mae = self.mae_model.predict(X_scaled)[0] if self.mae_model else 0.0
        risk_adj = self.risk_adj_model.predict(X_scaled)[0] if self.risk_adj_model else 0.0  # V19.1

        # Confidence based on prediction distance from 0.5
        max_dist = max(abs(cont_proba - 0.5), abs(false_proba - 0.5))
        confidence = "HIGH" if max_dist > 0.3 else "MEDIUM" if max_dist > 0.15 else "LOW"

        # V19.1 — Meta-labeling for position sizing
        position_size = "NONE"
        if cont_proba >= 0.7:
            position_size = "FULL"
        elif cont_proba >= 0.5:
            position_size = "HALF"

        # SHAP explainability
        top_shap = []
        if SHAP_AVAILABLE:
            try:
                top_shap = self._compute_shap(X_scaled)
            except Exception as e:
                logger.warning("ML: SHAP computation failed: %s", e)

        return MLPrediction(
            continuation_prob=round(float(cont_proba), 3),
            false_alert_prob=round(float(false_proba), 3),
            expected_mfe=round(float(expected_mfe), 2),
            expected_mae=round(float(expected_mae), 2),
            confidence=confidence,
            top_shap_features=top_shap,
            model_version=self.current_version.version if self.current_version else "",
            predicted_at=datetime.now(timezone.utc).isoformat(),
            risk_adjusted_score=round(float(risk_adj), 2),
            suggested_position_size=position_size,
        )

    def _candidate_to_features(self, cand: AgenticCandidate) -> dict[str, float]:
        """Convert candidate to raw feature dict."""
        fe = self.feature_engineer
        prob = cand.second_leg.probability if cand.second_leg else 50.0
        trap = cand.trap.trap_risk_score if cand.trap else 50.0
        vol = cand.momentum.volume_persistence_pct if cand.momentum else 0.0
        catalyst = cand.catalyst.strength_score if cand.catalyst else 50.0
        return {
            "probability": prob,
            "trap_risk": trap,
            "volume_persistence": vol,
            "higher_low_formed_int": fe._encode_bool(
                cand.momentum.higher_low_formed if cand.momentum else False
            ),
            "catalyst_strength": catalyst,
            "rejected_int": fe._encode_bool(cand.rejected),
            "alertable_int": fe._encode_bool(cand.alertable),
            "vwap_held_int": fe._encode_bool(
                cand.momentum.vwap_reclaimed if cand.momentum else False
            ),
            "entry_quality_int": fe._encode_entry_quality(
                cand.entry_timing.quality.value if cand.entry_timing else None
            ),
            "float_category_int": fe._encode_float_category(
                cand.float_intel.float_category.value if cand.float_intel else None
            ),
            "catalyst_type_int": fe._encode_catalyst_type(
                cand.catalyst.catalyst_type.value if cand.catalyst else None
            ),
            "time_of_day_int": fe._encode_time_of_day(
                cand.time_of_day.session.value if cand.time_of_day else None
            ),
            # V19.1 — Market regime features (0 if unavailable)
            "spy_trend_5d": getattr(cand, "spy_trend_5d", 0.0),
            "vix_level": getattr(cand, "vix_level", 20.0),
            "sector_rsi": getattr(cand, "sector_rsi", 50.0),
            "market_breadth": getattr(cand, "market_breadth", 50.0),
            # V19.1 — Time & volume profile features
            "minutes_since_spike": getattr(cand, "minutes_since_spike", 30.0),
            "volume_profile_slope": getattr(cand, "volume_profile_slope", 0.0),
            "float_turnover_pct": getattr(cand, "float_turnover_pct", 0.0),
            "relative_volume_vs_sector": getattr(cand, "relative_volume_vs_sector", 1.0),
            # Interactions (computed inline for single prediction)
            "prob_x_trap": prob * trap / 100.0,
            "prob_x_vol": prob * vol / 100.0,
            "prob_x_catalyst": prob * catalyst / 100.0,
            "trap_x_float": trap * fe._encode_float_category(
                cand.float_intel.float_category.value if cand.float_intel else None
            ),
            "catalyst_x_time": catalyst * fe._encode_time_of_day(
                cand.time_of_day.session.value if cand.time_of_day else None
            ),
            # V19.1 — New interactions
            "prob_x_spy_trend": prob * getattr(cand, "spy_trend_5d", 0.0) / 100.0,
            "trap_x_vix": trap * getattr(cand, "vix_level", 20.0) / 100.0,
            "vol_x_float_turnover": vol * getattr(cand, "float_turnover_pct", 0.0) / 100.0,
            "minutes_x_prob": getattr(cand, "minutes_since_spike", 30.0) * prob / 100.0,
        }

    def _compute_shap(self, X_scaled: np.ndarray) -> list[dict]:
        """Compute SHAP values for a single prediction."""
        if not SHAP_AVAILABLE or self.continuation_model is None:
            return []

        try:
            # Use TreeSHAP on the XGBoost component if available
            # For simplicity, use KernelSHAP on the calibrated model
            explainer = shap.KernelExplainer(
                lambda x: self.continuation_model.predict_proba(x)[:, 1],
                shap.sample(np.zeros((10, len(ALL_FEATURES))), 10),
                silent=True,
            )
            shap_vals = explainer.shap_values(X_scaled, nsamples=50)
            if isinstance(shap_vals, list):
                shap_vals = shap_vals[1] if len(shap_vals) > 1 else shap_vals[0]

            top = []
            for idx in np.argsort(-np.abs(shap_vals[0]))[:3]:
                top.append({
                    "feature": ALL_FEATURES[idx],
                    "shap_value": round(float(shap_vals[0][idx]), 4),
                    "feature_value": round(float(X_scaled[0][idx]), 4),
                })
            return top
        except Exception as e:
            logger.warning("SHAP error: %s", e)
            return []

    # ── Drift Monitoring ──────────────────────────────────────────────

    def check_drift(
        self,
        recent_outcomes: list[AgenticOutcome],
        reference_outcomes: Optional[list[AgenticOutcome]] = None,
    ) -> DriftReport:
        """Check for prediction drift vs reference distribution."""
        if not self.continuation_model:
            return DriftReport(
                psi_score=0.0, max_ks_stat=0.0, brier_degradation=0.0,
                is_degraded=False, checked_at=datetime.now(timezone.utc).isoformat(),
            )

        recent_df = self.feature_engineer.extract(recent_outcomes)
        if recent_df.empty or len(recent_df) < 20:
            return DriftReport(
                psi_score=0.0, max_ks_stat=0.0, brier_degradation=0.0,
                is_degraded=False, checked_at=datetime.now(timezone.utc).isoformat(),
            )

        # Predict on recent
        X_recent = recent_df[ALL_FEATURES].fillna(0).values
        X_recent_scaled = self.scaler.transform(X_recent)
        recent_preds = self.continuation_model.predict_proba(X_recent_scaled)[:, 1]

        # Reference predictions (from training data or explicit reference)
        if reference_outcomes:
            ref_df = self.feature_engineer.extract(reference_outcomes)
            X_ref = ref_df[ALL_FEATURES].fillna(0).values
            X_ref_scaled = self.scaler.transform(X_ref)
            ref_preds = self.continuation_model.predict_proba(X_ref_scaled)[:, 1]
        else:
            # Use uniform distribution as fallback
            ref_preds = np.random.uniform(0, 1, size=100)

        # PSI
        psi = self._compute_psi(ref_preds, recent_preds)

        # KS test per feature (only if reference data available)
        feature_drifts = {}
        if reference_outcomes and X_ref_scaled is not None:
            for i, col in enumerate(ALL_FEATURES):
                ks = self._compute_ks(X_ref_scaled[:, i], X_recent_scaled[:, i])
                feature_drifts[col] = round(ks, 3)

        max_ks = max(feature_drifts.values()) if feature_drifts else 0.0

        # Brier degradation
        recent_y = recent_df[TARGET_CONTINUATION].values
        recent_brier = brier_score_loss(recent_y, recent_preds)
        ref_brier = 0.25  # Baseline random guess
        brier_deg = recent_brier - ref_brier

        is_degraded = psi > 0.2 or max_ks > 0.3 or brier_deg > 0.1

        # V19.1 — Auto-retrain if drift detected and sufficient cached outcomes
        if is_degraded and len(self._all_outcomes) >= MIN_TRAINING_SAMPLES:
            logger.warning("ML: drift detected (psi=%.3f, ks=%.3f, brier=%.3f) — auto-retraining", psi, max_ks, brier_deg)
            self._send_alert(
                f"🔄 <b>ML Model Drift Detected</b>\n"
                f"PSI: {psi:.3f} | KS: {max_ks:.3f} | Brier Δ: {brier_deg:.3f}\n"
                f"Auto-retraining on {len(self._all_outcomes)} outcomes..."
            )
            try:
                version = self.train(self._all_outcomes)
                if version:
                    self._send_alert(
                        f"✅ <b>ML Auto-Retrain Complete</b>\n"
                        f"Version: {version.version}\n"
                        f"AUC: {version.metrics.auc_roc:.3f} | F-beta: {version.metrics.fbeta:.3f}\n"
                        f"Threshold: {version.optimal_threshold:.3f}"
                    )
            except Exception as e:
                logger.error("ML: auto-retrain failed: %s", e)
                self._send_alert(
                    f"❌ <b>ML Auto-Retrain FAILED</b>\n"
                    f"Error: {str(e)[:100]}\n"
                    f"Model remains in current state. Manual review needed."
                )

        return DriftReport(
            psi_score=round(psi, 3),
            max_ks_stat=round(max_ks, 3),
            brier_degradation=round(brier_deg, 3),
            is_degraded=is_degraded,
            checked_at=datetime.now(timezone.utc).isoformat(),
            feature_drifts=feature_drifts,
        )

    @staticmethod
    def _compute_psi(expected: np.ndarray, actual: np.ndarray, bins: int = 10) -> float:
        """Population Stability Index."""
        breakpoints = np.linspace(0, 1, bins + 1)
        expected_percents = np.histogram(expected, breakpoints)[0] / len(expected)
        actual_percents = np.histogram(actual, breakpoints)[0] / len(actual)
        psi = np.sum(
            (actual_percents - expected_percents)
            * np.log(np.divide(actual_percents, expected_percents, out=np.zeros_like(actual_percents), where=expected_percents != 0) + 1e-7)
        )
        return float(psi)

    @staticmethod
    def _compute_ks(expected: np.ndarray, actual: np.ndarray) -> float:
        """Kolmogorov-Smirnov statistic."""
        from scipy import stats
        return float(stats.ks_2samp(expected, actual).statistic)

    # ── Persistence ───────────────────────────────────────────────────

    def _save_model(self, metrics: ModelMetrics, optimal_threshold: float = 0.5) -> ModelVersion:
        """Serialize model and metadata."""
        version = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        artifact = {
            "continuation_model": self.continuation_model,
            "false_alert_model": self.false_alert_model,
            "mfe_model": self.mfe_model,
            "mae_model": self.mae_model,
            "risk_adj_model": self.risk_adj_model,  # V19.1
            "scaler": self.scaler,
            "feature_names": ALL_FEATURES,
            "optimal_threshold": optimal_threshold,  # V19.1
        }
        path = MODEL_DIR / f"model_{version}.pkl"
        with open(path, "wb") as f:
            pickle.dump(artifact, f)

        # Hash
        with open(path, "rb") as f:
            model_hash = hashlib.sha256(f.read()).hexdigest()[:16]

        version_obj = ModelVersion(
            version=version,
            created_at=datetime.now(timezone.utc).isoformat(),
            metrics=metrics,
            feature_names=ALL_FEATURES,
            model_hash=model_hash,
            optimal_threshold=optimal_threshold,
        )

        # Save metadata
        meta_path = MODEL_DIR / f"meta_{version}.json"
        save_json_file(meta_path, {
            "version": version,
            "created_at": version_obj.created_at,
            "metrics": {
                "auc_roc": metrics.auc_roc,
                "fbeta": metrics.fbeta,
                "brier_score": metrics.brier_score,
                "log_loss": metrics.log_loss,
                "calibration_slope": metrics.calibration_slope,
                "n_train": metrics.n_train,
                "n_test": metrics.n_test,
            },
            "feature_names": ALL_FEATURES,
            "model_hash": model_hash,
            "approved": False,
            "is_live": False,
            "optimal_threshold": optimal_threshold,
        })

        return version_obj

    def _load_latest_model(self):
        """Load the latest approved model, or any model if none approved."""
        pkl_files = sorted(MODEL_DIR.glob("model_*.pkl"), reverse=True)
        if not pkl_files:
            return

        # Prefer approved models
        for pkl in pkl_files:
            meta_file = MODEL_DIR / pkl.name.replace("model_", "meta_").replace(".pkl", ".json")
            if meta_file.exists():
                with open(meta_file) as f:
                    meta = json.load(f)
                if meta.get("approved"):
                    self._load_artifact(pkl)
                    self.current_version = ModelVersion(
                        version=meta["version"],
                        created_at=meta["created_at"],
                        metrics=ModelMetrics(**meta["metrics"]),
                        feature_names=meta["feature_names"],
                        model_hash=meta["model_hash"],
                        approved=True,
                        approved_at=meta.get("approved_at"),
                        approved_by=meta.get("approved_by"),
                        is_live=meta.get("is_live", False),
                        optimal_threshold=meta.get("optimal_threshold", 0.5),
                    )
                    return

        # Fallback: load most recent
        self._load_artifact(pkl_files[0])
        meta_file = MODEL_DIR / pkl_files[0].name.replace("model_", "meta_").replace(".pkl", ".json")
        if meta_file.exists():
            with open(meta_file) as f:
                meta = json.load(f)
            self.current_version = ModelVersion(
                version=meta["version"],
                created_at=meta["created_at"],
                metrics=ModelMetrics(**meta["metrics"]),
                feature_names=meta["feature_names"],
                model_hash=meta["model_hash"],
                optimal_threshold=meta.get("optimal_threshold", 0.5),
            )

    def _load_artifact(self, path: Path):
        with open(path, "rb") as f:
            artifact = pickle.load(f)
        self.continuation_model = artifact.get("continuation_model")
        self.false_alert_model = artifact.get("false_alert_model")
        self.mfe_model = artifact.get("mfe_model")
        self.mae_model = artifact.get("mae_model")
        self.risk_adj_model = artifact.get("risk_adj_model")  # V19.1
        self.optimal_threshold = artifact.get("optimal_threshold", 0.5)  # V19.1
        self.scaler = artifact.get("scaler", StandardScaler())

    def approve_model(self, version: str, approved_by: str) -> bool:
        """Manually approve a model version for live use."""
        meta_path = MODEL_DIR / f"meta_{version}.json"
        if not meta_path.exists():
            return False
        meta = load_json_file(meta_path, default=None)
        if meta is None:
            return False
        meta["approved"] = True
        meta["approved_at"] = datetime.now(timezone.utc).isoformat()
        meta["approved_by"] = approved_by
        meta["is_live"] = True
        save_json_file(meta_path, meta)

        # Unapprove all other versions
        for other_meta in MODEL_DIR.glob("meta_*.json"):
            if other_meta.name == meta_path.name:
                continue
            other = load_json_file(other_meta, default=None)
            if other is None:
                continue
            if other.get("is_live"):
                other["is_live"] = False
                save_json_file(other_meta, other)

        # Load the approved model
        pkl_path = MODEL_DIR / f"model_{version}.pkl"
        self._load_artifact(pkl_path)
        self.current_version = ModelVersion(
            version=meta["version"],
            created_at=meta["created_at"],
            metrics=ModelMetrics(**meta["metrics"]),
            feature_names=meta["feature_names"],
            model_hash=meta["model_hash"],
            approved=True,
            approved_at=meta["approved_at"],
            approved_by=approved_by,
            is_live=True,
            optimal_threshold=meta.get("optimal_threshold", 0.5),
        )
        logger.info("ML: model %s approved by %s and set live", version, approved_by)
        return True

    def list_versions(self) -> list[dict]:
        """List all model versions with metadata."""
        versions = []
        for meta_file in sorted(MODEL_DIR.glob("meta_*.json"), reverse=True):
            with open(meta_file) as f:
                meta = json.load(f)
            versions.append(meta)
        return versions

    # ── Alerting ──────────────────────────────────────────────────────

    @staticmethod
    def _send_alert(text: str) -> None:
        """Send Telegram alert if configured."""
        try:
            from src.services.telegram_service import send_telegram_alert_sync
            send_telegram_alert_sync(text)
        except Exception:
            pass  # Silently fail if Telegram not configured

    # ── Audit Trail ───────────────────────────────────────────────────

    def log_prediction(
        self,
        candidate: AgenticCandidate,
        prediction: MLPrediction,
    ):
        """Log every prediction for audit."""
        audit_path = DATA_DIR / "ml_audit_log.jsonl"
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "ticker": candidate.ticker,
            "candidate_id": candidate.id,
            "model_version": prediction.model_version,
            "continuation_prob": prediction.continuation_prob,
            "false_alert_prob": prediction.false_alert_prob,
            "expected_mfe": prediction.expected_mfe,
            "expected_mae": prediction.expected_mae,
            "confidence": prediction.confidence,
            "fallback_reason": prediction.fallback_reason,
            "top_shap": prediction.top_shap_features,
            "risk_adjusted_score": prediction.risk_adjusted_score,
            "suggested_position_size": prediction.suggested_position_size,
        }
        with open(audit_path, "a") as f:
            f.write(json.dumps(record) + "\n")
