"""
Market Regime Detector — V3

Classifies the current market regime:
  - trending      (ADX > 25, clear direction)
  - choppy        (ADX < 20, no direction)
  - high_volatility (ATR% above threshold)
  - low_volatility  (ATR% below threshold, BB squeeze)

Returns a sensitivity multiplier to adjust detection thresholds.
"""

import logging
from typing import Optional

import numpy as np
import pandas as pd

from src.models.schemas import MarketRegime, RegimeData, OHLCVBar

logger = logging.getLogger(__name__)


class RegimeDetector:
    """Detect market regime from OHLCV data using ADX, ATR%, and BB width."""

    def __init__(
        self,
        adx_trending: float = 25.0,
        adx_choppy: float = 20.0,
        atr_high_vol_pct: float = 3.0,
        atr_low_vol_pct: float = 1.0,
        bb_squeeze_width: float = 0.03,
    ):
        self.adx_trending = adx_trending
        self.adx_choppy = adx_choppy
        self.atr_high_vol_pct = atr_high_vol_pct
        self.atr_low_vol_pct = atr_low_vol_pct
        self.bb_squeeze_width = bb_squeeze_width

    def detect(self, bars: list[OHLCVBar]) -> Optional[RegimeData]:
        """Classify the market regime from OHLCV bars."""
        if len(bars) < 30:
            logger.warning("Not enough bars (%d) for regime detection", len(bars))
            return None

        highs = np.array([b.high for b in bars])
        lows = np.array([b.low for b in bars])
        closes = np.array([b.close for b in bars])

        adx = self._compute_adx(highs, lows, closes, period=14)
        atr_pct = self._compute_atr_pct(highs, lows, closes, period=14)
        bb_width = self._compute_bb_width(closes, period=20, num_std=2.0)

        # Classification priority: volatility extremes first, then trend
        if atr_pct >= self.atr_high_vol_pct:
            regime = MarketRegime.HIGH_VOLATILITY
            multiplier = 1.3  # widen thresholds — expect bigger swings
        elif atr_pct <= self.atr_low_vol_pct or bb_width <= self.bb_squeeze_width:
            regime = MarketRegime.LOW_VOLATILITY
            multiplier = 0.7  # tighten thresholds — small moves matter more
        elif adx >= self.adx_trending:
            regime = MarketRegime.TRENDING
            multiplier = 1.0  # normal sensitivity
        else:
            regime = MarketRegime.CHOPPY
            multiplier = 0.8  # reduce sensitivity — avoid false signals

        result = RegimeData(
            regime=regime,
            adx=round(adx, 2),
            bb_width=round(bb_width, 4),
            atr_pct=round(atr_pct, 2),
            sensitivity_multiplier=multiplier,
        )

        logger.info(
            "RegimeDetector: %s (ADX=%.1f ATR%%=%.2f BB_W=%.4f mult=%.1f)",
            regime.value, adx, atr_pct, bb_width, multiplier,
        )
        return result

    # ── Indicators ───────────────────────────────────────────────────────

    @staticmethod
    def _compute_adx(highs, lows, closes, period=14) -> float:
        """Average Directional Index."""
        n = len(highs)
        if n < period + 1:
            return 0.0

        tr = np.maximum(
            highs[1:] - lows[1:],
            np.maximum(
                np.abs(highs[1:] - closes[:-1]),
                np.abs(lows[1:] - closes[:-1]),
            ),
        )

        plus_dm = np.where(
            (highs[1:] - highs[:-1]) > (lows[:-1] - lows[1:]),
            np.maximum(highs[1:] - highs[:-1], 0),
            0,
        )
        minus_dm = np.where(
            (lows[:-1] - lows[1:]) > (highs[1:] - highs[:-1]),
            np.maximum(lows[:-1] - lows[1:], 0),
            0,
        )

        # Wilder smoothing
        atr = np.zeros(len(tr))
        atr[period - 1] = np.mean(tr[:period])
        for i in range(period, len(tr)):
            atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period

        plus_di_smooth = np.zeros(len(plus_dm))
        minus_di_smooth = np.zeros(len(minus_dm))
        plus_di_smooth[period - 1] = np.mean(plus_dm[:period])
        minus_di_smooth[period - 1] = np.mean(minus_dm[:period])

        for i in range(period, len(plus_dm)):
            plus_di_smooth[i] = (plus_di_smooth[i - 1] * (period - 1) + plus_dm[i]) / period
            minus_di_smooth[i] = (minus_di_smooth[i - 1] * (period - 1) + minus_dm[i]) / period

        # DI values
        valid = atr[period - 1 :] > 0
        if not np.any(valid):
            return 0.0

        plus_di = np.where(atr[period - 1 :] > 0, 100 * plus_di_smooth[period - 1 :] / atr[period - 1 :], 0)
        minus_di = np.where(atr[period - 1 :] > 0, 100 * minus_di_smooth[period - 1 :] / atr[period - 1 :], 0)

        di_sum = plus_di + minus_di
        dx = np.where(di_sum > 0, 100 * np.abs(plus_di - minus_di) / di_sum, 0)

        if len(dx) < period:
            return float(np.mean(dx)) if len(dx) > 0 else 0.0

        adx = np.zeros(len(dx))
        adx[period - 1] = np.mean(dx[:period])
        for i in range(period, len(dx)):
            adx[i] = (adx[i - 1] * (period - 1) + dx[i]) / period

        return float(adx[-1])

    @staticmethod
    def _compute_atr_pct(highs, lows, closes, period=14) -> float:
        """ATR as percentage of price."""
        tr = np.maximum(
            highs[1:] - lows[1:],
            np.maximum(
                np.abs(highs[1:] - closes[:-1]),
                np.abs(lows[1:] - closes[:-1]),
            ),
        )
        if len(tr) < period:
            return 0.0

        atr = float(np.mean(tr[-period:]))
        current = float(closes[-1])
        return (atr / current) * 100 if current > 0 else 0.0

    @staticmethod
    def _compute_bb_width(closes, period=20, num_std=2.0) -> float:
        """Bollinger Band width as fraction of middle band."""
        if len(closes) < period:
            return 0.0
        sma = float(np.mean(closes[-period:]))
        std = float(np.std(closes[-period:]))
        if sma == 0:
            return 0.0
        upper = sma + num_std * std
        lower = sma - num_std * std
        return (upper - lower) / sma
