"""
Stage-of-Move Detection — V3

Classifies each stock into one of 5 stages:
  1. Breakout       — breaking out of range/base, early move
  2. Strong trend   — confirmed trend, healthy pullbacks
  3. Extended       — far from averages, thinning momentum
  4. Distribution   — topping, selling into strength
  5. Breakdown      — breaking down, trend reversal

Only stages 1-2 are suitable for entry.

Uses:
  - price vs. EMA-9/20/50 structure
  - new high distance
  - volume pattern
  - momentum (RSI, ROC)
"""

import logging
from typing import Optional

import numpy as np

from src.models.schemas import MoveStage, StageResult, OHLCVBar

logger = logging.getLogger(__name__)


class StageDetector:
    """Classify the stage of a stock's move from OHLCV data."""

    def detect(self, ticker: str, bars: list[OHLCVBar]) -> Optional[StageResult]:
        if len(bars) < 30:
            logger.warning("Not enough bars (%d) for stage detection [%s]", len(bars), ticker)
            return None

        closes = np.array([b.close for b in bars])
        highs = np.array([b.high for b in bars])
        volumes = np.array([b.volume for b in bars])

        current = float(closes[-1])
        intraday_high = float(highs.max())

        # EMAs
        ema9 = self._ema(closes, 9)
        ema20 = self._ema(closes, 20)
        ema50 = self._ema(closes, min(50, len(closes)))

        # Distance from intraday high
        dist_from_high = ((intraday_high - current) / intraday_high) * 100

        # EMA structure
        above_ema9 = current > ema9
        above_ema20 = current > ema20
        ema9_above_ema20 = ema9 > ema20

        # RSI-14
        rsi = self._rsi(closes, 14)

        # Volume trend: recent 5 bars vs prior 10
        vol_recent = float(np.mean(volumes[-5:])) if len(volumes) >= 5 else 0
        vol_prior = float(np.mean(volumes[-15:-5])) if len(volumes) >= 15 else vol_recent
        vol_ratio = vol_recent / vol_prior if vol_prior > 0 else 1.0

        # Rate of change (10 bars)
        roc = ((current - float(closes[-11])) / float(closes[-11])) * 100 if len(closes) > 11 else 0

        # ── Stage classification ─────────────────────────────────────────

        # Stage 5: Breakdown
        if not above_ema20 and not ema9_above_ema20 and roc < -5:
            return StageResult(
                ticker=ticker, stage=MoveStage.BREAKDOWN,
                entry_allowed=False,
                reason=f"Below EMA-20, EMA crossover down, ROC={roc:.1f}%",
            )

        # Stage 4: Distribution
        if (
            dist_from_high > 3
            and not above_ema9
            and vol_ratio > 1.2
            and rsi > 50
        ):
            return StageResult(
                ticker=ticker, stage=MoveStage.DISTRIBUTION,
                entry_allowed=False,
                reason=f"Selling off high, vol increasing, RSI={rsi:.0f}",
            )

        # Stage 3: Extended
        if (
            above_ema9
            and above_ema20
            and rsi > 80
            and dist_from_high < 2
        ):
            return StageResult(
                ticker=ticker, stage=MoveStage.EXTENDED,
                entry_allowed=False,
                reason=f"RSI={rsi:.0f} overbought, near highs",
            )

        # Stage 1: Breakout
        if (
            dist_from_high < 1.5
            and above_ema9
            and vol_ratio > 1.3
            and rsi > 55
            and rsi < 80
        ):
            return StageResult(
                ticker=ticker, stage=MoveStage.BREAKOUT,
                entry_allowed=True,
                reason=f"Near highs, strong volume ({vol_ratio:.1f}x), RSI={rsi:.0f}",
            )

        # Stage 2: Strong trend
        if above_ema9 and above_ema20 and ema9_above_ema20:
            return StageResult(
                ticker=ticker, stage=MoveStage.STRONG_TREND,
                entry_allowed=True,
                reason=f"Above EMAs, healthy trend, RSI={rsi:.0f}",
            )

        # Default: extended or distribution depending on direction
        if roc > 0:
            return StageResult(
                ticker=ticker, stage=MoveStage.EXTENDED,
                entry_allowed=False,
                reason=f"Ambiguous, leaning extended (ROC={roc:.1f}%)",
            )
        return StageResult(
            ticker=ticker, stage=MoveStage.DISTRIBUTION,
            entry_allowed=False,
            reason=f"Ambiguous, leaning distribution (ROC={roc:.1f}%)",
        )

    # ── Helpers ──────────────────────────────────────────────────────────

    @staticmethod
    def _ema(data: np.ndarray, period: int) -> float:
        if len(data) < period:
            return float(np.mean(data))
        multiplier = 2 / (period + 1)
        ema = float(data[0])
        for val in data[1:]:
            ema = (float(val) - ema) * multiplier + ema
        return ema

    @staticmethod
    def _rsi(closes: np.ndarray, period: int = 14) -> float:
        if len(closes) < period + 1:
            return 50.0
        deltas = np.diff(closes)
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)
        avg_gain = float(np.mean(gains[-period:]))
        avg_loss = float(np.mean(losses[-period:]))
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))
