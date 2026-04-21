"""
ML Engine Interface — Stub for V2

Will provide:
  - ML-based dip probability prediction
  - ML-based bounce probability prediction
  - Risk scoring (1-10)
  - Setup grading (A-F)
  - Confidence scoring
  - Signal ranking
"""

from abc import ABC, abstractmethod
from typing import Optional

from src.models.schemas import DipFeatures, BounceFeatures


class IMLEngine(ABC):
    """Interface for ML-based prediction engine (V2)."""

    @abstractmethod
    def predict_dip_probability(self, features: DipFeatures) -> float:
        """Return ML-predicted dip probability (0-100)."""
        ...

    @abstractmethod
    def predict_bounce_probability(self, features: BounceFeatures) -> float:
        """Return ML-predicted bounce probability (0-100)."""
        ...

    @abstractmethod
    def score_risk(self, features: dict) -> int:
        """Return risk score 1-10."""
        ...

    @abstractmethod
    def grade_setup(self, features: dict) -> str:
        """Return setup grade A-F."""
        ...

    @abstractmethod
    def compute_confidence(self, features: dict) -> float:
        """Return confidence percentage 0-100."""
        ...


class MLEngineStub(IMLEngine):
    """No-op implementation for V1."""

    def predict_dip_probability(self, features: DipFeatures) -> float:
        raise NotImplementedError("ML engine not available until V2")

    def predict_bounce_probability(self, features: BounceFeatures) -> float:
        raise NotImplementedError("ML engine not available until V2")

    def score_risk(self, features: dict) -> int:
        raise NotImplementedError("Risk scoring not available until V2")

    def grade_setup(self, features: dict) -> str:
        raise NotImplementedError("Setup grading not available until V2")

    def compute_confidence(self, features: dict) -> float:
        raise NotImplementedError("Confidence scoring not available until V2")
