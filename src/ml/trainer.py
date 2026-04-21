"""
Model Trainer — V2

Pulls historical signals + outcomes from the database, engineers features,
and trains both the dip and bounce ML models.
"""

import logging
from typing import Optional

import numpy as np
from sklearn.model_selection import train_test_split
from sqlalchemy.orm import Session

from src.models.database import Signal, SignalOutcome
from src.ml.feature_engineer import FeatureEngineer
from src.ml.dip_model import DipModel
from src.ml.bounce_model import BounceModel
from src.ml.model_store import ModelStore

logger = logging.getLogger(__name__)


class ModelTrainer:
    """Orchestrates training of dip and bounce models from DB history."""

    def __init__(self, db: Session, model_store: Optional[ModelStore] = None):
        self.db = db
        self.model_store = model_store or ModelStore()

    def train_all(self) -> dict:
        """Train both dip and bounce models. Returns combined metrics."""
        dip_result = self.train_dip_model()
        bounce_result = self.train_bounce_model()
        return {"dip_model": dip_result, "bounce_model": bounce_result}

    def train_dip_model(self) -> dict:
        """Build training set and train the dip prediction model with train/test split."""
        rows = self._get_labeled_signals()
        if not rows:
            return {"status": "no_data"}

        X_list, y_list = [], []
        for signal, outcome in rows:
            if signal.features_snapshot is None:
                continue
            dip_features = self._extract_dip_features(signal.features_snapshot)
            if dip_features is None:
                continue

            X_list.append(FeatureEngineer.dip_to_array(dip_features))
            # Label: did the stock bounce after the dip? (positive outcome)
            y_list.append(1 if outcome.outcome == "win" else 0)

        if not X_list:
            return {"status": "no_valid_features"}

        X = np.array(X_list)
        y = np.array(y_list)

        # Train/test split with stratification to maintain class balance
        if len(X) >= 50:  # Only split if we have enough data
            X_train, X_test, y_train, y_test = train_test_split(
                X, y, test_size=0.2, stratify=y, random_state=42
            )
        else:
            X_train, X_test, y_train, y_test = X, X, y, y  # Use same data for small sets

        model = DipModel(self.model_store)
        return model.train(X_train, y_train, X_test, y_test)

    def train_bounce_model(self) -> dict:
        """Build training set and train the bounce prediction model with train/test split."""
        rows = self._get_labeled_signals()
        if not rows:
            return {"status": "no_data"}

        X_list, y_list = [], []
        for signal, outcome in rows:
            if signal.features_snapshot is None:
                continue
            bounce_features = self._extract_bounce_features(signal.features_snapshot)
            if bounce_features is None:
                continue

            X_list.append(FeatureEngineer.bounce_to_array(bounce_features))
            y_list.append(1 if outcome.outcome == "win" else 0)

        if not X_list:
            return {"status": "no_valid_features"}

        X = np.array(X_list)
        y = np.array(y_list)

        # Train/test split with stratification to maintain class balance
        if len(X) >= 50:
            X_train, X_test, y_train, y_test = train_test_split(
                X, y, test_size=0.2, stratify=y, random_state=42
            )
        else:
            X_train, X_test, y_train, y_test = X, X, y, y

        model = BounceModel(self.model_store)
        return model.train(X_train, y_train, X_test, y_test)

    # ── Private helpers ──────────────────────────────────────────────────

    def _get_labeled_signals(self) -> list[tuple[Signal, SignalOutcome]]:
        """Retrieve signals that have recorded outcomes."""
        results = (
            self.db.query(Signal, SignalOutcome)
            .join(SignalOutcome, Signal.id == SignalOutcome.signal_id)
            .filter(SignalOutcome.outcome.in_(["win", "loss"]))
            .all()
        )
        logger.info("Found %d labeled signal-outcome pairs", len(results))
        return results

    @staticmethod
    def _extract_dip_features(snapshot: dict):
        """Attempt to reconstruct DipFeatures from a stored snapshot."""
        from src.models.schemas import DipFeatures

        dip_data = snapshot.get("dip_features")
        if dip_data is None:
            return None
        try:
            return DipFeatures(**dip_data)
        except Exception:
            return None

    @staticmethod
    def _extract_bounce_features(snapshot: dict):
        """Attempt to reconstruct BounceFeatures from a stored snapshot."""
        from src.models.schemas import BounceFeatures

        bounce_data = snapshot.get("bounce_features")
        if bounce_data is None:
            return None
        try:
            return BounceFeatures(**bounce_data)
        except Exception:
            return None
