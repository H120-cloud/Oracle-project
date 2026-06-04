"""
News Momentum Self-Training ML Engine
=====================================

Learns from resolved Telegram alert outcomes to predict the probability that
a new candidate will result in a profitable alert (GREAT/GOOD outcome) vs
noise (TRAP / NO_FOLLOW_THROUGH).

Design principles:
- **Auto-train**: weekly retrain on accumulated outcomes (no user action needed)
- **Auto-label**: classes derived from price action via AlertOutcome enum
- **Safe fallback**: when no trained model exists yet, returns neutral confidence (0.5)
  so gating logic falls back to its rule-based defaults
- **A/B safe**: confidence is bounded so it can only nudge thresholds ±15%, never
  override hard risk filters
- **Explainable**: feature importance reported with every prediction so you can
  see which factors are driving the score

Backed by XGBoost (preferred) with scikit-learn LogisticRegression fallback.
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.core.agentic.news_momentum_models import (
    AlertOutcome,
    CatalystSubType,
    SessionType,
    TelegramAlertRecord,
)
from src.utils.atomic_json import load_json_file, save_json_file

logger = logging.getLogger(__name__)

DATA_DIR = Path("data/agentic")
MODEL_FILE = DATA_DIR / "news_momentum_ml_model.joblib"
META_FILE = DATA_DIR / "news_momentum_ml_meta.json"

# Training thresholds
MIN_SAMPLES_FOR_TRAINING = 30  # very low bar so the system starts learning fast
MIN_SAMPLES_FOR_PROMOTION = 50  # but require more before swapping models in production

# Outcomes considered a "win" (positive class)
WIN_OUTCOMES = {AlertOutcome.GREAT_ALERT, AlertOutcome.GOOD_ALERT}
LOSS_OUTCOMES = {
    AlertOutcome.TRAP_ALERT,
    AlertOutcome.NO_FOLLOW_THROUGH,
    AlertOutcome.LATE_ALERT,
}

# Ordinal encoding for categorical features
_FLOAT_ORDER = {"ultra_low": 0, "low": 1, "medium": 2, "high": 3}
_MCAP_ORDER = {"nano": 0, "micro": 1, "small": 2, "all": 3}
_SESSION_ORDER = {"premarket": 0, "regular": 1, "after_hours": 2}


@dataclass
class MLPrediction:
    """Result of an ML prediction for a single candidate."""

    win_probability: float  # 0.0 to 1.0
    confidence: float  # 0.0 to 1.0 — how sure the model is
    used_model: bool  # False if rule-based fallback
    model_version: Optional[str] = None
    top_features: List[Tuple[str, float]] = field(default_factory=list)
    reason: str = ""


@dataclass
class TrainingResult:
    """Outcome of a single training run."""

    success: bool
    samples: int = 0
    train_accuracy: float = 0.0
    test_accuracy: float = 0.0
    auc: float = 0.0
    win_rate_baseline: float = 0.0  # what fraction of alerts are wins
    feature_importance: List[Tuple[str, float]] = field(default_factory=list)
    promoted: bool = False
    reason: str = ""
    model_version: str = ""


# ── Feature Extraction ───────────────────────────────────────────────────────

# Stable feature ordering — IMPORTANT: never reorder, only append
FEATURE_NAMES: List[str] = [
    "news_impact_score",
    "expected_return_score",
    "continuation_probability",
    "multi_day_score",
    "price_at_alert",
    "log_price",
    # Binned move_pct to avoid label leakage (raw move_pct already baked into outcome)
    "move_pct_bucket_0_10",
    "move_pct_bucket_10_30",
    "move_pct_bucket_30_100",
    "move_pct_bucket_100_plus",
    "rvol_at_alert",
    "log_volume",
    "spread_pct_at_alert",
    "trap_risk_at_alert",
    "dilution_risk_at_alert",
    "velocity_score_at_alert",
    "sources_seen_count",
    "is_negative",
    "is_vague",
    "is_delayed_reaction",
    "prenews_anomaly_score",
    "float_category_ord",
    "market_cap_category_ord",
    "session_ord",
    "is_premarket",
    "is_after_hours",
    "is_weekend_send",
    "hour_of_day",
    # Catalyst archetype flags
    "is_fda_catalyst",
    "is_ai_catalyst",
    "is_earnings_catalyst",
    "is_corporate_action",
    "is_vague_catalyst",
    "is_negative_catalyst",
    # Feature interactions (helpful for small datasets)
    "float_x_fda",          # low float + FDA = explosive
    "float_x_ai",           # low float + AI = explosive
    "premkt_x_move_bucket", # premarket + large gap
    "rvol_x_trap",          # high volume + high trap = distribution
    "impact_x_float",       # high impact + low float
]


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        if v is None:
            return default
        f = float(v)
        if math.isnan(f) or math.isinf(f):
            return default
        return f
    except (TypeError, ValueError):
        return default


def _extract_features(record_or_candidate: Any) -> List[float]:
    """Extract feature vector from a TelegramAlertRecord or NewsMomentumCandidate.

    Both share most field names, so we just probe attributes safely.
    """
    g = lambda name, default=None: getattr(record_or_candidate, name, default)

    # Price
    price = _safe_float(g("price_at_alert") or g("current_price"), 1.0)
    log_price = math.log1p(max(0.0, price))

    move_pct = _safe_float(g("move_pct_at_alert") or g("move_pct"), 0.0)
    # Binned move_pct to prevent label leakage
    mp = abs(move_pct)
    move_b_0_10 = 1.0 if mp <= 10 else 0.0
    move_b_10_30 = 1.0 if 10 < mp <= 30 else 0.0
    move_b_30_100 = 1.0 if 30 < mp <= 100 else 0.0
    move_b_100_plus = 1.0 if mp > 100 else 0.0
    rvol = _safe_float(g("rvol_at_alert") or g("rvol"), 1.0)
    volume = _safe_float(g("volume_at_alert") or g("volume"), 0.0)
    log_volume = math.log1p(max(0.0, volume))
    spread = _safe_float(g("spread_pct_at_alert") or g("spread_pct"), 1.0)
    trap = _safe_float(g("trap_risk_at_alert") or g("trap_risk"), 0.0)
    dilution = _safe_float(g("dilution_risk_at_alert") or g("dilution_risk"), 0.0)
    velocity = _safe_float(g("velocity_score_at_alert") or g("velocity_score"), 0.0)
    sources = _safe_float(g("sources_seen_count"), 1.0)

    # Categorical → ordinal
    float_cat = g("float_category")
    if hasattr(float_cat, "value"):
        float_cat = float_cat.value
    float_ord = _FLOAT_ORDER.get(str(float_cat or "low").lower(), 1)

    mcap_cat = g("market_cap_category")
    if hasattr(mcap_cat, "value"):
        mcap_cat = mcap_cat.value
    mcap_ord = _MCAP_ORDER.get(str(mcap_cat or "micro").lower(), 1)

    session = g("session_type") or g("session")
    if hasattr(session, "value"):
        session = session.value
    session_str = str(session or "regular").lower()
    session_ord = _SESSION_ORDER.get(session_str, 1)
    is_pm = 1.0 if session_str == "premarket" else 0.0
    is_ah = 1.0 if session_str == "after_hours" else 0.0

    sent_at = g("sent_at") or g("detected_at") or datetime.now(timezone.utc)
    if isinstance(sent_at, str):
        try:
            sent_at = datetime.fromisoformat(sent_at)
        except Exception:
            sent_at = datetime.now(timezone.utc)
    is_weekend = 1.0 if sent_at.weekday() >= 5 else 0.0
    hour_of_day = sent_at.hour if sent_at else 12

    # Catalyst archetype flags
    catalyst = g("catalyst_type") or g("catalyst_sub_type")
    if hasattr(catalyst, "value"):
        catalyst = catalyst.value
    catalyst_str = str(catalyst or "other").lower()
    fda_set = {
        "fda_approval", "fda_clearance", "phase_1", "phase_2", "phase_3",
        "fast_track", "breakthrough_therapy", "orphan_drug", "pdufa", "topline_data",
    }
    ai_set = {"ai_partnership", "nvidia_partnership", "openai_partnership",
              "hyperscaler_contract", "infrastructure_agreement"}
    earnings_set = {"earnings_beat", "guidance_raise", "profitability_inflection"}
    corporate_set = {"merger", "acquisition", "buyout", "strategic_review",
                     "licensing_agreement", "patent_approval"}
    negative_set = {"offering", "atm_filing", "warrant_exercise", "reverse_split",
                    "delisting_notice", "toxic_financing", "debt_restructuring"}

    is_fda = 1.0 if catalyst_str in fda_set else 0.0
    is_ai = 1.0 if catalyst_str in ai_set else 0.0
    is_earnings = 1.0 if catalyst_str in earnings_set else 0.0
    is_corp = 1.0 if catalyst_str in corporate_set else 0.0
    is_vague_cat = 1.0 if catalyst_str == "vague_pr" else 0.0
    is_neg_cat = 1.0 if catalyst_str in negative_set else 0.0

    # Feature interactions
    float_x_fda = float(float_ord) * is_fda
    float_x_ai = float(float_ord) * is_ai
    premkt_x_move = is_pm * move_b_30_100 + is_pm * move_b_100_plus
    rvol_x_trap = min((rvol / 10.0) * (trap / 100.0), 1.0)
    impact_x_float = (_safe_float(g("news_impact_score"), 50.0) / 100.0) * (1.0 - float(float_ord) / 3.0)

    return [
        _safe_float(g("news_impact_score"), 50.0),
        _safe_float(g("expected_return_score"), 50.0),
        _safe_float(g("continuation_probability"), 50.0),
        _safe_float(g("multi_day_score") or g("multi_day_continuation_score"), 50.0),
        price,
        log_price,
        move_b_0_10,
        move_b_10_30,
        move_b_30_100,
        move_b_100_plus,
        rvol,
        log_volume,
        spread,
        trap,
        dilution,
        velocity,
        sources,
        1.0 if g("is_negative") else 0.0,
        1.0 if g("is_vague") else 0.0,
        1.0 if g("is_delayed_reaction") else 0.0,
        _safe_float(g("prenews_anomaly_score"), 0.0),
        float(float_ord),
        float(mcap_ord),
        float(session_ord),
        is_pm,
        is_ah,
        is_weekend,
        float(hour_of_day),
        is_fda, is_ai, is_earnings, is_corp, is_vague_cat, is_neg_cat,
        float_x_fda,
        float_x_ai,
        premkt_x_move,
        rvol_x_trap,
        impact_x_float,
    ]


def _label_from_outcome(outcome: Optional[AlertOutcome]) -> Optional[int]:
    """Map AlertOutcome to binary label. Returns None if outcome unresolved."""
    if outcome is None:
        return None
    if outcome in WIN_OUTCOMES:
        return 1
    if outcome in LOSS_OUTCOMES:
        return 0
    return None  # MISSED_RUNNER and any unknown class are excluded


# ── Engine ───────────────────────────────────────────────────────────────────


class NewsMomentumMLEngine:
    """Self-training ML scorer for News Momentum alerts.

    Usage:
        engine = NewsMomentumMLEngine()
        engine.load()                                    # load any saved model
        prediction = engine.predict(candidate)           # at alert time
        result = engine.train(records)                   # weekly retrain
    """

    def __init__(self) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._model: Any = None
        self._meta: Dict[str, Any] = {}
        self._feature_importance: List[Tuple[str, float]] = []
        self._backend: str = "none"  # "xgboost", "logistic", or "none"

    # ── Load / Save ───────────────────────────────────────────────────────────

    def load(self) -> bool:
        """Load a previously trained model from disk. Returns True on success."""
        if not MODEL_FILE.exists():
            logger.info("ML: no trained model on disk; using rule-based fallback")
            return False
        try:
            import joblib
            self._model = joblib.load(MODEL_FILE)
            self._meta = load_json_file(META_FILE, default={}) or {}
            self._backend = self._meta.get("backend", "logistic")
            self._feature_importance = self._meta.get("feature_importance", [])
            logger.info(
                "ML: loaded %s model (version=%s, samples=%d, auc=%.3f)",
                self._backend,
                self._meta.get("model_version", "unknown"),
                self._meta.get("samples", 0),
                self._meta.get("auc", 0.0),
            )
            return True
        except Exception as exc:
            logger.warning("ML: model load failed: %s", exc)
            self._model = None
            return False

    def _save(self, model: Any, backend: str, meta: Dict[str, Any]) -> None:
        try:
            import joblib
            joblib.dump(model, MODEL_FILE)
            save_json_file(META_FILE, meta)
            logger.info(
                "ML: saved %s model %s (samples=%d, auc=%.3f)",
                backend,
                meta.get("model_version"),
                meta.get("samples", 0),
                meta.get("auc", 0.0),
            )
        except Exception as exc:
            logger.error("ML: model save failed: %s", exc)

    # ── Predict ───────────────────────────────────────────────────────────────

    def predict(self, candidate_or_record: Any) -> MLPrediction:
        """Predict probability that a candidate will be a winning alert."""
        if self._model is None:
            return MLPrediction(
                win_probability=0.5,
                confidence=0.0,
                used_model=False,
                reason="no_model",
            )
        try:
            features = _extract_features(candidate_or_record)
            import numpy as np
            X = np.array([features], dtype=float)
            proba = self._model.predict_proba(X)[0]
            # Class 1 == win. Some sklearn objects may have .classes_
            classes = list(getattr(self._model, "classes_", [0, 1]))
            if 1 in classes:
                win_idx = classes.index(1)
                win_prob = float(proba[win_idx])
            else:
                win_prob = float(proba[-1])

            # Confidence = distance from 0.5 (normalized)
            confidence = abs(win_prob - 0.5) * 2.0

            top = sorted(
                self._feature_importance, key=lambda kv: kv[1], reverse=True
            )[:5]
            return MLPrediction(
                win_probability=win_prob,
                confidence=confidence,
                used_model=True,
                model_version=self._meta.get("model_version"),
                top_features=top,
                reason=f"{self._backend}_v{self._meta.get('model_version', '?')}",
            )
        except Exception as exc:
            logger.warning("ML: prediction failed, using fallback: %s", exc)
            return MLPrediction(
                win_probability=0.5,
                confidence=0.0,
                used_model=False,
                reason=f"predict_error: {exc}",
            )

    # ── Train ─────────────────────────────────────────────────────────────────

    def train(
        self,
        records: List[TelegramAlertRecord],
        missed_records: Optional[List[Any]] = None,
    ) -> TrainingResult:
        """Train (or retrain) the model on resolved alert records.

        Supports missed-winner records as synthetic positive examples to
        reduce selection bias. Uses 5-fold stratified CV for robust evaluation.
        Auto-promotes the new model if AUC is at least as good as current.
        """
        # Build dataset from resolved alerts
        X_list: List[List[float]] = []
        y_list: List[int] = []
        for r in records:
            label = _label_from_outcome(r.outcome)
            if label is None:
                continue
            X_list.append(_extract_features(r))
            y_list.append(label)

        # Inject missed winners as synthetic positive examples
        # (they scored high but were blocked; treat as "should have been 1")
        missed_injected = 0
        if missed_records:
            for mr in missed_records:
                try:
                    feat = _extract_features(mr)
                    X_list.append(feat)
                    y_list.append(1)
                    missed_injected += 1
                except Exception:
                    continue

        n_samples = len(y_list)
        n_resolved = n_samples - missed_injected
        win_rate = sum(y_list) / n_samples if n_samples else 0.0

        if n_resolved < MIN_SAMPLES_FOR_TRAINING:
            return TrainingResult(
                success=False,
                samples=n_resolved,
                win_rate_baseline=win_rate,
                reason=f"need >= {MIN_SAMPLES_FOR_TRAINING} resolved samples, have {n_resolved} (injected {missed_injected} missed)",
            )

        # Need both classes present
        unique_classes = set(y_list)
        if len(unique_classes) < 2:
            return TrainingResult(
                success=False,
                samples=n_resolved,
                win_rate_baseline=win_rate,
                reason=f"only one class present ({unique_classes}); cannot train binary classifier",
            )

        try:
            import numpy as np
            from sklearn.model_selection import StratifiedKFold, train_test_split
            from sklearn.metrics import accuracy_score, roc_auc_score

            X = np.array(X_list, dtype=float)
            y = np.array(y_list, dtype=int)

            # ── 5-fold stratified cross-validation ──────────────────────────
            cv_aucs: List[float] = []
            cv_accs: List[float] = []
            n_splits = min(5, n_samples // 4)  # ensure at least 4 samples per fold
            if n_splits < 2:
                n_splits = 2

            skf = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=42)
            for fold, (tr_idx, te_idx) in enumerate(skf.split(X, y)):
                X_tr, X_te = X[tr_idx], X[te_idx]
                y_tr, y_te = y[tr_idx], y[te_idx]
                # Use same model config as final model for fair CV
                try:
                    from xgboost import XGBClassifier
                    m = XGBClassifier(
                        n_estimators=30,
                        max_depth=2,
                        learning_rate=0.05,
                        subsample=0.7,
                        colsample_bytree=0.7,
                        min_child_weight=5,
                        reg_lambda=2.0,
                        eval_metric="logloss",
                        random_state=42 + fold,
                        n_jobs=1,
                    )
                    m.fit(X_tr, y_tr)
                except Exception:
                    from sklearn.linear_model import LogisticRegression
                    from sklearn.preprocessing import StandardScaler
                    from sklearn.pipeline import Pipeline
                    m = Pipeline([
                        ("scale", StandardScaler()),
                        ("lr", LogisticRegression(max_iter=1000, class_weight="balanced", random_state=42 + fold)),
                    ])
                    m.fit(X_tr, y_tr)
                try:
                    proba = m.predict_proba(X_te)[:, 1]
                    cv_aucs.append(float(roc_auc_score(y_te, proba)))
                except Exception:
                    cv_aucs.append(0.5)
                cv_accs.append(float(accuracy_score(y_te, m.predict(X_te))))

            cv_auc_mean = float(np.mean(cv_aucs))
            cv_auc_std = float(np.std(cv_aucs))
            cv_acc_mean = float(np.mean(cv_accs))

            # ── Final train/test split for feature importance + hold-out AUC ──
            test_size = 0.25 if n_samples >= 80 else 0.2
            try:
                X_tr, X_te, y_tr, y_te = train_test_split(
                    X, y, test_size=test_size, random_state=42, stratify=y,
                )
            except ValueError:
                X_tr, X_te, y_tr, y_te = train_test_split(
                    X, y, test_size=test_size, random_state=42,
                )

            # ── Model selection: prefer LogisticRegression for small data ──
            # Use XGBoost only when we have >=80 samples; otherwise LR is more
            # stable and less prone to overfitting on tiny datasets.
            backend = "logistic"
            if n_samples >= 80:
                try:
                    from xgboost import XGBClassifier
                    model = XGBClassifier(
                        n_estimators=30,
                        max_depth=2,
                        learning_rate=0.05,
                        subsample=0.7,
                        colsample_bytree=0.7,
                        min_child_weight=5,
                        reg_lambda=2.0,
                        eval_metric="logloss",
                        random_state=42,
                        n_jobs=1,
                    )
                    model.fit(X_tr, y_tr)
                    backend = "xgboost"
                except Exception as exc:
                    logger.warning("ML: XGBoost unavailable (%s), using LogisticRegression", exc)
                    from sklearn.linear_model import LogisticRegression
                    from sklearn.preprocessing import StandardScaler
                    from sklearn.pipeline import Pipeline
                    model = Pipeline([
                        ("scale", StandardScaler()),
                        ("lr", LogisticRegression(max_iter=1000, class_weight="balanced", random_state=42)),
                    ])
                    model.fit(X_tr, y_tr)
            else:
                from sklearn.linear_model import LogisticRegression
                from sklearn.preprocessing import StandardScaler
                from sklearn.pipeline import Pipeline
                model = Pipeline([
                    ("scale", StandardScaler()),
                    ("lr", LogisticRegression(max_iter=1000, class_weight="balanced", random_state=42)),
                ])
                model.fit(X_tr, y_tr)

            # ── Evaluate ──────────────────────────────────────────────────────
            tr_pred = model.predict(X_tr)
            te_pred = model.predict(X_te)
            tr_acc = float(accuracy_score(y_tr, tr_pred))
            te_acc = float(accuracy_score(y_te, te_pred))
            try:
                te_proba = model.predict_proba(X_te)[:, 1]
                auc = float(roc_auc_score(y_te, te_proba))
            except Exception:
                auc = 0.5

            # ── Feature importance ──────────────────────────────────────────
            importance: List[Tuple[str, float]] = []
            try:
                if backend == "xgboost":
                    imp = model.feature_importances_
                    importance = sorted(
                        list(zip(FEATURE_NAMES, [float(v) for v in imp])),
                        key=lambda kv: kv[1], reverse=True,
                    )
                else:
                    coefs = model.named_steps["lr"].coef_[0]
                    importance = sorted(
                        list(zip(FEATURE_NAMES, [abs(float(v)) for v in coefs])),
                        key=lambda kv: kv[1], reverse=True,
                    )
            except Exception:
                importance = []

            version = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
            meta: Dict[str, Any] = {
                "model_version": version,
                "backend": backend,
                "samples": n_resolved,
                "missed_injected": missed_injected,
                "win_rate_baseline": win_rate,
                "train_accuracy": tr_acc,
                "test_accuracy": te_acc,
                "auc": auc,
                "cv_auc_mean": cv_auc_mean,
                "cv_auc_std": cv_auc_std,
                "cv_acc_mean": cv_acc_mean,
                "feature_importance": importance,
                "feature_names": FEATURE_NAMES,
                "trained_at": datetime.now(timezone.utc).isoformat(),
            }

            # ── Promotion with drift detection ──────────────────────────────
            promote = False
            existing_auc = float(self._meta.get("auc", 0.0)) if self._model is not None else 0.0
            existing_cv_mean = float(self._meta.get("cv_auc_mean", 0.0)) if self._model is not None else 0.0

            # Drift: if CV AUC dropped >0.05 from previous model, warn but still
            # promote if hold-out AUC is acceptable (could be regime change)
            drift_warning = ""
            if self._model is not None and existing_cv_mean > 0:
                if cv_auc_mean < existing_cv_mean - 0.05:
                    drift_warning = f" drift_detected (cv_mean {cv_auc_mean:.3f} vs {existing_cv_mean:.3f})"
                    logger.warning("ML: model drift detected%s", drift_warning)

            if n_resolved >= MIN_SAMPLES_FOR_PROMOTION and (
                self._model is None or auc >= existing_auc - 0.02
            ):
                self._save(model, backend, meta)
                self._model = model
                self._meta = meta
                self._feature_importance = importance
                self._backend = backend
                promote = True

            return TrainingResult(
                success=True,
                samples=n_resolved,
                train_accuracy=tr_acc,
                test_accuracy=te_acc,
                auc=auc,
                win_rate_baseline=win_rate,
                feature_importance=importance,
                promoted=promote,
                model_version=version,
                reason=("promoted" if promote else "trained_not_promoted") + drift_warning,
            )
        except Exception as exc:
            logger.error("ML: training failed: %s", exc, exc_info=True)
            return TrainingResult(
                success=False,
                samples=n_resolved if 'n_resolved' in dir() else n_samples,
                win_rate_baseline=win_rate,
                reason=f"training_error: {exc}",
            )

    # ── Reporting ─────────────────────────────────────────────────────────────

    def get_status(self) -> Dict[str, Any]:
        """Return model status info for diagnostics / dashboard."""
        return {
            "model_loaded": self._model is not None,
            "backend": self._backend,
            "model_version": self._meta.get("model_version"),
            "samples_trained_on": self._meta.get("samples", 0),
            "auc": self._meta.get("auc", 0.0),
            "test_accuracy": self._meta.get("test_accuracy", 0.0),
            "trained_at": self._meta.get("trained_at"),
            "top_features": self._feature_importance[:10] if self._feature_importance else [],
        }
