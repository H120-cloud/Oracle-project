"""
Self-Learning System Interface — Stub for V4

Will provide:
  - Learning from wrong predictions
  - Learning from missed opportunities
  - Adaptive threshold adjustment
  - Confidence calibration
"""

from abc import ABC, abstractmethod
from typing import Optional


class ISelfLearner(ABC):
    """Interface for self-learning system (V4)."""

    @abstractmethod
    def record_outcome(self, signal_id: str, predicted: float, actual: float) -> None:
        """Record a prediction vs actual outcome for learning."""
        ...

    @abstractmethod
    def adjust_thresholds(self) -> dict:
        """Return adjusted thresholds based on historical performance."""
        ...

    @abstractmethod
    def get_calibration_curve(self) -> dict:
        """Return predicted vs actual probability buckets."""
        ...

    @abstractmethod
    def retrain(self) -> bool:
        """Trigger a retraining cycle. Return success."""
        ...


class SelfLearnerStub(ISelfLearner):
    """No-op implementation for V1."""

    def record_outcome(self, signal_id: str, predicted: float, actual: float) -> None:
        raise NotImplementedError("Self-learning not available until V4")

    def adjust_thresholds(self) -> dict:
        raise NotImplementedError("Self-learning not available until V4")

    def get_calibration_curve(self) -> dict:
        raise NotImplementedError("Self-learning not available until V4")

    def retrain(self) -> bool:
        raise NotImplementedError("Self-learning not available until V4")
