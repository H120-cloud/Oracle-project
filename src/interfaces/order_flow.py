"""
Order Flow Analysis Interface — Stub for V4

Will provide:
  - Bid/ask imbalance
  - Cumulative delta
  - Aggressive buying/selling detection
  - Entry confirmation
  - Fake bounce detection
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class OrderFlowData:
    bid_ask_imbalance: float
    cumulative_delta: float
    aggressive_buy_ratio: float
    aggressive_sell_ratio: float


class IOrderFlow(ABC):
    """Interface for order flow analysis (V4)."""

    @abstractmethod
    def analyze(self, ticker: str) -> Optional[OrderFlowData]:
        ...

    @abstractmethod
    def confirms_entry(self, ticker: str) -> bool:
        """Return True if order flow supports a long entry."""
        ...

    @abstractmethod
    def is_fake_bounce(self, ticker: str) -> bool:
        """Return True if order flow suggests the bounce is not real."""
        ...


class OrderFlowStub(IOrderFlow):
    """No-op implementation for V1."""

    def analyze(self, ticker: str) -> Optional[OrderFlowData]:
        raise NotImplementedError("Order flow not available until V4")

    def confirms_entry(self, ticker: str) -> bool:
        raise NotImplementedError("Order flow not available until V4")

    def is_fake_bounce(self, ticker: str) -> bool:
        raise NotImplementedError("Order flow not available until V4")
