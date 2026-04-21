"""
Backtesting Engine — V4

Replays historical data through the signal pipeline and evaluates
performance. Uses simplified entry/exit rules for reproducibility.

Flow:
  1. Fetch historical OHLCV
  2. Walk forward bar-by-bar
  3. Detect signals at each point
  4. Simulate entries/exits
  5. Compute aggregate stats
"""

import logging
from typing import Optional

import numpy as np

from src.models.schemas import (
    OHLCVBar,
    BacktestConfig,
    BacktestTrade,
    BacktestResult,
)
from src.services.market_data import YFinanceProvider, IMarketDataProvider
from src.core.dip_detector import DipDetector
from src.core.bounce_detector import BounceDetector
from src.core.stage_detector import StageDetector
from src.core.regime_detector import RegimeDetector

logger = logging.getLogger(__name__)

MIN_BARS_FOR_SIGNAL = 30
DEFAULT_STOP_PCT = 2.0
DEFAULT_TARGET_PCT = 4.0


class Backtester:
    """Walk-forward backtester using the Oracle signal pipeline."""

    def __init__(
        self,
        market_data: Optional[IMarketDataProvider] = None,
        stop_pct: float = DEFAULT_STOP_PCT,
        target_pct: float = DEFAULT_TARGET_PCT,
    ):
        self.market_data = market_data or YFinanceProvider()
        self.dip_detector = DipDetector()
        self.bounce_detector = BounceDetector()
        self.stage_detector = StageDetector()
        self.regime_detector = RegimeDetector()
        self.stop_pct = stop_pct
        self.target_pct = target_pct

    def run(self, config: BacktestConfig) -> BacktestResult:
        """Execute a backtest for the given configuration."""
        # Use start/end dates for historical backtesting (not period which is relative to today)
        bars = self.market_data.get_ohlcv(
            config.ticker,
            start=config.start_date,
            end=config.end_date,
            interval=config.interval,
        )

        if len(bars) < MIN_BARS_FOR_SIGNAL:
            logger.warning("Not enough bars (%d) for backtest", len(bars))
            return BacktestResult(config=config, trades=[])

        trades: list[BacktestTrade] = []
        position = None  # (entry_price, entry_date, stop, target)
        equity = config.initial_capital

        for i in range(MIN_BARS_FOR_SIGNAL, len(bars)):
            bar = bars[i]

            # Check if in a position
            if position:
                entry_price, entry_date, stop, target = position

                # Hit stop
                if bar.low <= stop:
                    pnl_pct = ((stop - entry_price) / entry_price) * 100
                    trades.append(BacktestTrade(
                        entry_date=entry_date,
                        exit_date=str(bar.timestamp),
                        entry_price=round(entry_price, 2),
                        exit_price=round(stop, 2),
                        action="STOP_LOSS",
                        pnl_pct=round(pnl_pct, 2),
                    ))
                    equity *= (1 + pnl_pct / 100)
                    position = None
                    continue

                # Hit target
                if bar.high >= target:
                    pnl_pct = ((target - entry_price) / entry_price) * 100
                    trades.append(BacktestTrade(
                        entry_date=entry_date,
                        exit_date=str(bar.timestamp),
                        entry_price=round(entry_price, 2),
                        exit_price=round(target, 2),
                        action="TARGET_HIT",
                        pnl_pct=round(pnl_pct, 2),
                    ))
                    equity *= (1 + pnl_pct / 100)
                    position = None
                    continue

                # Still holding
                continue

            # Not in a position — look for entry signal
            window = bars[i - MIN_BARS_FOR_SIGNAL : i + 1]

            # Stage gate
            stage = self.stage_detector.detect(config.ticker, window)
            if stage and not stage.entry_allowed:
                continue

            # Regime check (avoid choppy)
            regime = self.regime_detector.detect(window)

            # Simple entry: look for bullish bar (close > open) after a dip
            if self._is_entry_bar(window):
                entry_price = bar.close
                stop = entry_price * (1 - self.stop_pct / 100)
                target = entry_price * (1 + self.target_pct / 100)
                position = (entry_price, str(bar.timestamp), stop, target)

        # Close any open position at last bar
        if position:
            entry_price, entry_date, _, _ = position
            last_price = bars[-1].close
            pnl_pct = ((last_price - entry_price) / entry_price) * 100
            trades.append(BacktestTrade(
                entry_date=entry_date,
                exit_date=str(bars[-1].timestamp),
                entry_price=round(entry_price, 2),
                exit_price=round(last_price, 2),
                action="OPEN_CLOSE",
                pnl_pct=round(pnl_pct, 2),
            ))

        return self._compute_stats(config, trades, equity)

    # ── Entry detection ──────────────────────────────────────────────────

    def _is_entry_bar(self, window: list[OHLCVBar]) -> bool:
        """Simple entry rule: 2+ red bars followed by a green bar with higher volume."""
        if len(window) < 4:
            return False

        bars = window[-4:]
        # At least 2 of the first 3 bars are red
        red_count = sum(1 for b in bars[:3] if b.close < b.open)
        if red_count < 2:
            return False

        # Current bar is green
        current = bars[-1]
        if current.close <= current.open:
            return False

        # Volume expansion
        avg_vol = np.mean([b.volume for b in bars[:3]])
        if avg_vol > 0 and current.volume > avg_vol * 1.2:
            return True

        return False

    # ── Stats computation ────────────────────────────────────────────────

    def _compute_stats(
        self, config: BacktestConfig, trades: list[BacktestTrade], final_equity: float
    ) -> BacktestResult:
        if not trades:
            return BacktestResult(config=config, trades=trades)

        pnls = [t.pnl_pct for t in trades]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p < 0]

        win_rate = (len(wins) / len(pnls)) * 100 if pnls else 0
        total_return = ((final_equity - config.initial_capital) / config.initial_capital) * 100

        # Max drawdown
        equity_curve = [config.initial_capital]
        for pnl in pnls:
            equity_curve.append(equity_curve[-1] * (1 + pnl / 100))
        peak = equity_curve[0]
        max_dd = 0
        for eq in equity_curve:
            peak = max(peak, eq)
            dd = ((peak - eq) / peak) * 100
            max_dd = max(max_dd, dd)

        # Sharpe (simplified: daily returns, annualized)
        returns = np.array(pnls) / 100
        sharpe = None
        if len(returns) > 1 and np.std(returns) > 0:
            sharpe = round(float(np.mean(returns) / np.std(returns) * np.sqrt(252)), 2)

        gross_profit = sum(wins) if wins else 0
        gross_loss = abs(sum(losses)) if losses else 0
        pf = gross_profit / gross_loss if gross_loss > 0 else 999.0

        return BacktestResult(
            config=config,
            trades=trades,
            total_trades=len(trades),
            win_rate=round(win_rate, 1),
            total_return_pct=round(total_return, 2),
            max_drawdown_pct=round(max_dd, 2),
            sharpe_ratio=sharpe,
            profit_factor=round(pf, 2) if pf != float("inf") else 999.0,
            avg_win_pct=round(np.mean(wins), 2) if wins else 0,
            avg_loss_pct=round(np.mean(losses), 2) if losses else 0,
        )

    @staticmethod
    def _days_between(start: str, end: str) -> int:
        from datetime import datetime
        d1 = datetime.strptime(start, "%Y-%m-%d")
        d2 = datetime.strptime(end, "%Y-%m-%d")
        return max((d2 - d1).days, 1)
