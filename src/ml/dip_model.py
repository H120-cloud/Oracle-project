"""
ML Dip Prediction Model — V2

Gradient Boosting classifier that predicts dip probability.
Falls back to rule-based scoring when no trained model exists (cold start).
"""

import logging
from typing import Optional

import numpy as np
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.calibration import CalibratedClassifierCV
from sklearn.preprocessing import StandardScaler
from sklearn.utils.class_weight import compute_sample_weight

from src.models.schemas import DipFeatures
from src.ml.feature_engineer import FeatureEngineer
from src.ml.model_store import ModelStore

logger = logging.getLogger(__name__)

MODEL_NAME = "dip_predictor"


class DipModel:
    """ML-enhanced dip probability predictor with cold-start fallback."""

    def __init__(self, model_store: Optional[ModelStore] = None):
        self.model_store = model_store or ModelStore()
        self._model: Optional[CalibratedClassifierCV] = None
        self._scaler: Optional[StandardScaler] = None
        self._is_trained = False
        self._load_model()

    def _load_model(self):
        payload = self.model_store.load(MODEL_NAME)
        if payload is not None:
            self._model = payload["model"]
            self._scaler = payload.get("scaler")
            self._is_trained = True
            logger.info("Dip model loaded (trained)")
        else:
            logger.info("No trained dip model found — cold-start mode")

    @property
    def is_trained(self) -> bool:
        return self._is_trained

    def predict(self, features: DipFeatures, rule_based_prob: float) -> float:
        """
        Return dip probability (0–100).

        If a trained model exists, blend ML prediction with rule-based.
        Otherwise return rule-based score directly.
        """
        if not self._is_trained or self._model is None:
            return rule_based_prob

        try:
            X = FeatureEngineer.dip_to_array(features).reshape(1, -1)

            # Apply feature scaling if scaler exists
            if self._scaler is not None:
                X = self._scaler.transform(X)

            ml_prob = float(self._model.predict_proba(X)[0][1]) * 100

            # Blend: 60% ML, 40% rule-based (trust grows with more data)
            blended = 0.6 * ml_prob + 0.4 * rule_based_prob
            blended = max(0.0, min(100.0, blended))

            logger.debug(
                "DipModel predict: ml=%.1f rule=%.1f blended=%.1f",
                ml_prob, rule_based_prob, blended,
            )
            return round(blended, 1)

        except Exception as exc:
            logger.error("DipModel predict failed, fallback to rule-based: %s", exc)
            return rule_based_prob

    def train(
        self, X_train: np.ndarray, y_train: np.ndarray,
        X_test: np.ndarray, y_test: np.ndarray
    ) -> dict:
        """
        Train the model on historical feature vectors and binary labels.

        X_train: shape (n_train_samples, n_dip_features)
        y_train: binary array (1 = valid dip that bounced, 0 = false dip)
        X_test: shape (n_test_samples, n_dip_features) - held-out test set
        y_test: binary array for test set

        Returns training metrics including test accuracy.
        """
        if len(X_train) < 30:
            logger.warning("Not enough samples to train (%d). Need >= 30.", len(X_train))
            return {"status": "insufficient_data", "samples": len(X_train)}

        # Feature scaling
        self._scaler = StandardScaler()
        X_train_scaled = self._scaler.fit_transform(X_train)
        X_test_scaled = self._scaler.transform(X_test)

        # Class balancing via sample weights
        sample_weights = compute_sample_weight(class_weight='balanced', y=y_train)

        base = GradientBoostingClassifier(
            n_estimators=100,
            max_depth=4,
            learning_rate=0.1,
            subsample=0.8,
            random_state=42,
        )
        calibrated = CalibratedClassifierCV(base, cv=3, method="isotonic")
        calibrated.fit(X_train_scaled, y_train, sample_weight=sample_weights)

        # Score on training data
        train_score = float(calibrated.score(X_train_scaled, y_train))
        train_proba = calibrated.predict_proba(X_train_scaled)[:, 1]
        avg_train_conf = float(np.mean(train_proba))

        # Score on test data (unseen data for realistic accuracy)
        test_score = float(calibrated.score(X_test_scaled, y_test))
        test_proba = calibrated.predict_proba(X_test_scaled)[:, 1]
        avg_test_conf = float(np.mean(test_proba))

        self._model = calibrated
        self._is_trained = True

        metadata = {
            "samples": len(X_train),
            "train_accuracy": round(train_score, 4),
            "test_accuracy": round(test_score, 4),
            "avg_train_confidence": round(avg_train_conf, 4),
            "avg_test_confidence": round(avg_test_conf, 4),
        }

        # Save both model and scaler
        self.model_store.save(
            {"model": calibrated, "scaler": self._scaler},
            MODEL_NAME,
            metadata
        )

        logger.info(
            "Dip model trained: samples=%d, train_acc=%.3f, test_acc=%.3f",
            len(X_train), train_score, test_score
        )
        return {"status": "trained", **metadata}
