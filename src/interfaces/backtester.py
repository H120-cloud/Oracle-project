"""
Backtesting Engine Interface — Stub for V4

Will provide:
  - Historical replay
  - Performance evaluation
  - Slippage & spread modeling
  - Win rate / drawdown metrics
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional
from datetime import datetime


@dataclass
class BacktestResult:
    total_signals: int
    wins: int
    losses: int
    win_rate: float
    total_pnl: float
    max_drawdown: float
    sharpe_ratio: Optional[float]
    start_date: datetime
    end_date: datetime


class IBacktester(ABC):
    """Interface for backtesting engine (V4)."""

    @abstractmethod
    def run(
        self,
        start_date: datetime,
        end_date: datetime,
        tickers: list[str] | None = None,
    ) -> BacktestResult:
        ...

    @abstractmethod
    def evaluate_signal_history(self) -> dict:
        """Evaluate all historical signals and return performance metrics."""
        ...


class BacktesterStub(IBacktester):
    """No-op implementation for V1."""

    def run(
        self,
        start_date: datetime,
        end_date: datetime,
        tickers: list[str] | None = None,
    ) -> BacktestResult:
        raise NotImplementedError("Backtesting not available until V4")

    def evaluate_signal_history(self) -> dict:
        raise NotImplementedError("Backtesting not available until V4")
