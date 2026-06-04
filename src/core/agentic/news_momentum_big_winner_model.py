"""
Big-Winner ML Model (V23.1 Upgrade #4)

A dedicated XGBoost classifier trained ONLY to predict GREAT_ALERT outcomes
(>25% moves). Used by the winner-targeting layer to identify "rocket"
candidates for the HIGH_CONVICTION tier.

This sits ALONGSIDE the main NewsMomentumMLEngine — the main model predicts
"will it move >2% positively" (broad winner), this model predicts "will it
deliver a >25% rocket move" (the alerts that actually drive returns).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.core.agentic.news_momentum_models import (
    AlertOutcome,
    TelegramAlertRecord,
)
from src.core.agentic.news_momentum_ml_engine import _extract_features
from src.utils.atomic_json import load_json_file, save_json_file

logger = logging.getLogger(__name__)

DATA_DIR = Path("data/agentic")
MODEL_FILE = DATA_DIR / "news_momentum_big_winner_model.joblib"
META_FILE = DATA_DIR / "news_momentum_big_winner_meta.json"

MIN_SAMPLES_FOR_TRAINING = 100


@dataclass
class BigWinnerPrediction:
    rocket_probability: float  # 0.0 to 1.0 — likelihood of >25% move
    confidence: float
    used_model: bool
    model_version: Optional[str] = None
    reason: str = ""


@dataclass
class BigWinnerTrainingResult:
    success: bool
    samples: int = 0
    rockets: int = 0
    auc: float = 0.0
    model_version: Optional[str] = None
    reason: str = ""


class BigWinnerMLEngine:
    """Specialised model: predict probability of a GREAT_ALERT (>25% move)."""

    def __init__(self) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._model: Any = None
        self._meta: Dict[str, Any] = {}

    # ── Persistence ─────────────────────────────────────────────────────────
    def load(self) -> bool:
        if not MODEL_FILE.exists():
            return False
        try:
            import joblib
            self._model = joblib.load(MODEL_FILE)
            self._meta = load_json_file(META_FILE, default={}) or {}
            logger.info(
                "BigWinner ML: loaded model %s (samples=%d, rockets=%d, auc=%.3f)",
                self._meta.get("model_version", "?"),
                self._meta.get("samples", 0),
                self._meta.get("rockets", 0),
                self._meta.get("auc", 0.0),
            )
            return True
        except Exception as exc:
            logger.warning("BigWinner ML: load failed: %s", exc)
            self._model = None
            return False

    def _save(self) -> None:
        try:
            import joblib
            joblib.dump(self._model, MODEL_FILE)
            save_json_file(META_FILE, self._meta)
        except Exception as exc:
            logger.error("BigWinner ML: save failed: %s", exc)

    # ── Predict ─────────────────────────────────────────────────────────────
    def predict(self, candidate_or_record: Any) -> BigWinnerPrediction:
        if self._model is None:
            return BigWinnerPrediction(
                rocket_probability=0.05, confidence=0.0,
                used_model=False, reason="no_model",
            )
        try:
            import numpy as np
            features = _extract_features(candidate_or_record)
            X = np.array([features], dtype=float)
            proba = self._model.predict_proba(X)[0]
            classes = list(getattr(self._model, "classes_", [0, 1]))
            idx = classes.index(1) if 1 in classes else -1
            prob = float(proba[idx])
            return BigWinnerPrediction(
                rocket_probability=prob,
                confidence=abs(prob - 0.05) * 2.0,
                used_model=True,
                model_version=self._meta.get("model_version"),
                reason="xgboost",
            )
        except Exception as exc:
            logger.warning("BigWinner ML: predict failed: %s", exc)
            return BigWinnerPrediction(
                rocket_probability=0.05, confidence=0.0,
                used_model=False, reason=f"predict_error: {exc}",
            )

    # ── Train ───────────────────────────────────────────────────────────────
    def train(self, records: List[TelegramAlertRecord]) -> BigWinnerTrainingResult:
        """Binary classifier: ROCKET (>25% forward return) vs everything else.

        Label source — prefer explicit forward-return fields populated by
        the outcome resolver; fall back to the derived ``outcome`` enum for
        records that pre-date the multi-horizon label rollout. Using the
        explicit return is more robust because it doesn't depend on the
        ``mfe_pct`` / outcome-classification pipeline staying constant
        across retrains.
        """
        X_list: List[List[float]] = []
        y_list: List[int] = []
        for r in records:
            # Choose the strongest available forward-return signal.
            # Prefer 2-day high (captures intra-window peak across both
            # trading days), then next-day high, then 4h, then the legacy
            # outcome enum as final fallback.
            label: Optional[int] = None
            for fld in (
                "return_two_day_high_pct",
                "return_next_day_high_pct",
                "return_4h_pct",
            ):
                val = getattr(r, fld, None)
                if val is not None:
                    label = 1 if val >= 25.0 else 0
                    break
            if label is None:
                if r.outcome is None:
                    continue
                label = 1 if r.outcome == AlertOutcome.GREAT_ALERT else 0
            X_list.append(_extract_features(r))
            y_list.append(label)

        n_samples = len(y_list)
        n_rockets = sum(y_list)
        if n_samples < MIN_SAMPLES_FOR_TRAINING:
            return BigWinnerTrainingResult(
                success=False, samples=n_samples, rockets=n_rockets,
                reason=f"need >= {MIN_SAMPLES_FOR_TRAINING} samples, have {n_samples}",
            )
        if n_rockets < 10 or n_rockets == n_samples:
            return BigWinnerTrainingResult(
                success=False, samples=n_samples, rockets=n_rockets,
                reason=f"need both rockets and non-rockets; have {n_rockets} rockets of {n_samples}",
            )

        try:
            import numpy as np
            from sklearn.model_selection import StratifiedKFold
            from sklearn.metrics import roc_auc_score
            from xgboost import XGBClassifier

            X = np.array(X_list, dtype=float)
            y = np.array(y_list, dtype=int)

            # Up-weight rockets — they're rare (~5%)
            scale = (n_samples - n_rockets) / max(1, n_rockets)

            # Use lighter trees + more regularization to fight overfitting
            # (rocket class is rare → easy to memorize).
            common_kwargs = dict(
                n_estimators=40,
                max_depth=2,
                learning_rate=0.05,
                scale_pos_weight=scale,
                reg_alpha=1.0,
                reg_lambda=2.0,
                subsample=0.8,
                colsample_bytree=0.7,
                eval_metric="logloss",
                use_label_encoder=False,
                verbosity=0,
            )
            skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
            cv_aucs: List[float] = []
            for tr_idx, te_idx in skf.split(X, y):
                m = XGBClassifier(**common_kwargs)
                m.fit(X[tr_idx], y[tr_idx])
                preds = m.predict_proba(X[te_idx])[:, 1]
                try:
                    cv_aucs.append(roc_auc_score(y[te_idx], preds))
                except Exception:
                    pass
            mean_auc = float(np.mean(cv_aucs)) if cv_aucs else 0.0

            # Fit final on full data for production
            final = XGBClassifier(**common_kwargs)
            final.fit(X, y)
            self._model = final
            version = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
            self._meta = {
                "model_version": version,
                "samples": n_samples,
                "rockets": n_rockets,
                "rocket_rate": round(n_rockets / n_samples, 4),
                "auc": round(mean_auc, 4),
                "trained_at": datetime.now(timezone.utc).isoformat(),
            }
            self._save()
            logger.info(
                "BigWinner ML: trained model %s — samples=%d rockets=%d auc=%.3f",
                version, n_samples, n_rockets, mean_auc,
            )
            return BigWinnerTrainingResult(
                success=True, samples=n_samples, rockets=n_rockets,
                auc=mean_auc, model_version=version,
            )
        except ImportError as exc:
            return BigWinnerTrainingResult(
                success=False, samples=n_samples, rockets=n_rockets,
                reason=f"xgboost/sklearn not available: {exc}",
            )
        except Exception as exc:
            logger.exception("BigWinner ML: training failed")
            return BigWinnerTrainingResult(
                success=False, samples=n_samples, rockets=n_rockets,
                reason=f"train_error: {exc}",
            )

    def get_status(self) -> Dict[str, Any]:
        return {
            "model_loaded": self._model is not None,
            "model_version": self._meta.get("model_version"),
            "samples_trained_on": self._meta.get("samples", 0),
            "rockets": self._meta.get("rockets", 0),
            "rocket_rate": self._meta.get("rocket_rate", 0.0),
            "auc": self._meta.get("auc", 0.0),
            "trained_at": self._meta.get("trained_at"),
        }
