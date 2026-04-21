"""
Market Regime Detector Interface — Stub for V3

Will detect:
  - trending
  - choppy
  - high volatility
  - low volatility

And adjust model sensitivity accordingly.
"""

from abc import ABC, abstractmethod
from enum import Enum
from typing import Optional


class MarketRegime(str, Enum):
    TRENDING = "trending"
    CHOPPY = "choppy"
    HIGH_VOLATILITY = "high_volatility"
    LOW_VOLATILITY = "low_volatility"


class IRegimeDetector(ABC):
    """Interface for market regime detection (V3)."""

    @abstractmethod
    def detect_regime(self, ticker: str) -> Optional[MarketRegime]:
        ...

    @abstractmethod
    def get_sensitivity_multiplier(self, regime: MarketRegime) -> float:
        """Return a multiplier to adjust detection thresholds."""
        ...


class RegimeDetectorStub(IRegimeDetector):
    """No-op implementation for V1."""

    def detect_regime(self, ticker: str) -> Optional[MarketRegime]:
        raise NotImplementedError("Regime detection not available until V3")

    def get_sensitivity_multiplier(self, regime: MarketRegime) -> float:
        raise NotImplementedError("Regime detection not available until V3")
