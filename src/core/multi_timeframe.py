"""
Multi-Timeframe Engine — Part 4

Analyzes price across multiple timeframes:
- 1m/5m  → entry timing
- 15m/1h → structure
- 4h/D   → trend bias

Rules:
- Only trade when timeframes align
- Higher TF controls bias
- Lower TF controls entry
"""

import logging
from dataclasses import dataclass, field
from typing import List, Optional, Dict
from enum import Enum

import numpy as np

logger = logging.getLogger(__name__)


class TimeframeBias(str, Enum):
    STRONG_BULLISH = "STRONG_BULLISH"
    BULLISH = "BULLISH"
    NEUTRAL = "NEUTRAL"
    BEARISH = "BEARISH"
    STRONG_BEARISH = "STRONG_BEARISH"


class TimeframeAlignment(str, Enum):
    FULLY_ALIGNED = "FULLY_ALIGNED"       # All TFs agree
    MOSTLY_ALIGNED = "MOSTLY_ALIGNED"     # Higher + mid agree, lower is close
    PARTIALLY_ALIGNED = "PARTIALLY"       # Mixed signals
    CONFLICTING = "CONFLICTING"           # TFs disagree


@dataclass
class TimeframeAnalysis:
    """Analysis for a single timeframe."""
    timeframe: str              # "1m", "5m", "15m", "1h", "4h", "1d"
    bias: TimeframeBias = TimeframeBias.NEUTRAL

    # Technical signals
    price: float = 0.0
    ema9: float = 0.0
    ema20: float = 0.0
    ema50: float = 0.0
    above_ema9: bool = False
    above_ema20: bool = False
    above_ema50: bool = False

    # Structure
    higher_highs: bool = False
    higher_lows: bool = False
    lower_highs: bool = False
    lower_lows: bool = False

    # Momentum
    rsi: float = 50.0
    momentum_score: float = 0.0  # -100 to 100

    # Volume
    volume_trend: str = "flat"  # increasing, decreasing, flat

    score: float = 0.0  # -100 to 100, computed bias score


@dataclass
class MTFResult:
    """Multi-timeframe analysis result."""
    ticker: str
    alignment: TimeframeAlignment = TimeframeAlignment.CONFLICTING
    alignment_score: float = 0.0     # 0–100

    # Per-timeframe
    entry_tf: Optional[TimeframeAnalysis] = None      # 1m/5m
    structure_tf: Optional[TimeframeAnalysis] = None   # 15m/1h
    trend_tf: Optional[TimeframeAnalysis] = None       # 4h/1d

    # Composite
    overall_bias: TimeframeBias = TimeframeBias.NEUTRAL
    trend_bias: TimeframeBias = TimeframeBias.NEUTRAL   # From higher TF
    entry_ready: bool = False

    # All TF details
    timeframes: Dict[str, TimeframeAnalysis] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "ticker": self.ticker,
            "alignment": self.alignment.value,
            "alignment_score": self.alignment_score,
            "overall_bias": self.overall_bias.value,
            "trend_bias": self.trend_bias.value,
            "entry_ready": self.entry_ready,
            "timeframes": {
                k: {"bias": v.bias.value, "score": v.score, "rsi": v.rsi}
                for k, v in self.timeframes.items()
            },
        }


# Timeframe configs: (period, interval)
TF_CONFIGS = {
    "1m":  ("1d",  "1m"),
    "5m":  ("5d",  "5m"),
    "15m": ("5d",  "15m"),
    "1h":  ("1mo", "1h"),
    "1d":  ("3mo", "1d"),
}


class MultiTimeframeEngine:
    """Analyzes price across multiple timeframes for alignment."""

    def __init__(self, provider=None):
        self.provider = provider

    def analyze(self, ticker: str, timeframes: Optional[List[str]] = None) -> MTFResult:
        """Run multi-timeframe analysis."""
        if not self.provider:
            return MTFResult(ticker=ticker)

        tfs = timeframes or ["1m", "5m", "15m", "1h", "1d"]
        result = MTFResult(ticker=ticker)

        for tf in tfs:
            if tf not in TF_CONFIGS:
                continue
            period, interval = TF_CONFIGS[tf]
            try:
                bars = self.provider.get_ohlcv(ticker, period=period, interval=interval)
                if bars and len(bars) >= 20:
                    analysis = self._analyze_timeframe(tf, bars)
                    result.timeframes[tf] = analysis
            except Exception as exc:
                logger.warning("MTF analysis failed for %s %s: %s", ticker, tf, exc)

        # Assign roles
        entry_tfs = [result.timeframes.get(t) for t in ["1m", "5m"] if t in result.timeframes]
        struct_tfs = [result.timeframes.get(t) for t in ["15m", "1h"] if t in result.timeframes]
        trend_tfs = [result.timeframes.get(t) for t in ["1d"] if t in result.timeframes]

        if entry_tfs:
            result.entry_tf = entry_tfs[0]
        if struct_tfs:
            result.structure_tf = struct_tfs[0]
        if trend_tfs:
            result.trend_tf = trend_tfs[0]

        # Compute alignment
        result.alignment, result.alignment_score = self._compute_alignment(result)
        result.overall_bias = self._compute_overall_bias(result)
        result.trend_bias = result.trend_tf.bias if result.trend_tf else TimeframeBias.NEUTRAL
        result.entry_ready = self._check_entry_ready(result)

        logger.info(
            "MTF [%s]: alignment=%s (%.0f%%) bias=%s trend=%s entry=%s",
            ticker, result.alignment.value, result.alignment_score,
            result.overall_bias.value, result.trend_bias.value, result.entry_ready,
        )

        return result

    def _analyze_timeframe(self, tf: str, bars: list) -> TimeframeAnalysis:
        """Analyze a single timeframe."""
        closes = np.array([float(b.close) for b in bars])
        highs = np.array([float(b.high) for b in bars])
        lows = np.array([float(b.low) for b in bars])
        volumes = np.array([float(b.volume) for b in bars])

        price = closes[-1]

        # EMAs
        ema9 = self._ema(closes, 9)
        ema20 = self._ema(closes, 20)
        ema50 = self._ema(closes, min(50, len(closes) - 1)) if len(closes) >= 20 else ema20

        # Structure detection
        hh, hl, lh, ll = self._detect_structure(highs, lows, lookback=10)

        # RSI
        rsi = self._rsi(closes, 14)

        # Volume trend
        vol_trend = self._volume_trend(volumes)

        # Momentum score
        momentum = self._momentum_score(closes, ema9, ema20, ema50, rsi)

        # Bias classification
        bias = self._classify_bias(price, ema9, ema20, ema50, hh, hl, lh, ll, rsi, momentum)

        return TimeframeAnalysis(
            timeframe=tf,
            bias=bias,
            price=round(price, 4),
            ema9=round(ema9, 4),
            ema20=round(ema20, 4),
            ema50=round(ema50, 4),
            above_ema9=price > ema9,
            above_ema20=price > ema20,
            above_ema50=price > ema50,
            higher_highs=hh,
            higher_lows=hl,
            lower_highs=lh,
            lower_lows=ll,
            rsi=round(rsi, 1),
            momentum_score=round(momentum, 1),
            volume_trend=vol_trend,
            score=round(momentum, 1),
        )

    def _detect_structure(self, highs, lows, lookback=10):
        """Detect swing structure (HH/HL/LH/LL)."""
        if len(highs) < lookback * 2:
            return False, False, False, False

        recent_highs = highs[-lookback:]
        prev_highs = highs[-lookback*2:-lookback]
        recent_lows = lows[-lookback:]
        prev_lows = lows[-lookback*2:-lookback]

        hh = float(np.max(recent_highs)) > float(np.max(prev_highs))
        hl = float(np.min(recent_lows)) > float(np.min(prev_lows))
        lh = float(np.max(recent_highs)) < float(np.max(prev_highs))
        ll = float(np.min(recent_lows)) < float(np.min(prev_lows))

        return hh, hl, lh, ll

    def _classify_bias(self, price, ema9, ema20, ema50, hh, hl, lh, ll, rsi, momentum):
        """Classify timeframe bias."""
        bull_signals = sum([
            price > ema9, price > ema20, price > ema50,
            ema9 > ema20, ema20 > ema50,
            hh, hl,
            rsi > 50, rsi > 60,
            momentum > 20,
        ])
        bear_signals = sum([
            price < ema9, price < ema20, price < ema50,
            ema9 < ema20, ema20 < ema50,
            lh, ll,
            rsi < 50, rsi < 40,
            momentum < -20,
        ])

        net = bull_signals - bear_signals
        if net >= 6:
            return TimeframeBias.STRONG_BULLISH
        elif net >= 3:
            return TimeframeBias.BULLISH
        elif net <= -6:
            return TimeframeBias.STRONG_BEARISH
        elif net <= -3:
            return TimeframeBias.BEARISH
        return TimeframeBias.NEUTRAL

    def _compute_alignment(self, result: MTFResult) -> tuple:
        """Compute alignment between timeframes."""
        if not result.timeframes:
            return TimeframeAlignment.CONFLICTING, 0.0

        scores = [tf.score for tf in result.timeframes.values()]
        if not scores:
            return TimeframeAlignment.CONFLICTING, 0.0

        # Check if all same direction
        all_bull = all(s > 0 for s in scores)
        all_bear = all(s < 0 for s in scores)
        avg_abs = np.mean(np.abs(scores))

        if all_bull or all_bear:
            if avg_abs > 30:
                return TimeframeAlignment.FULLY_ALIGNED, min(100, avg_abs * 2)
            return TimeframeAlignment.MOSTLY_ALIGNED, min(100, avg_abs * 1.5)

        # Check if higher TFs agree
        higher = [result.timeframes.get(t) for t in ["1d", "1h"] if t in result.timeframes]
        if higher and all(h.score > 0 for h in higher):
            return TimeframeAlignment.MOSTLY_ALIGNED, 60.0
        elif higher and all(h.score < 0 for h in higher):
            return TimeframeAlignment.MOSTLY_ALIGNED, 60.0

        # Mixed
        std = np.std(scores)
        if std > 40:
            return TimeframeAlignment.CONFLICTING, max(0, 50 - std)
        return TimeframeAlignment.PARTIALLY_ALIGNED, max(0, 70 - std)

    def _compute_overall_bias(self, result: MTFResult) -> TimeframeBias:
        """Weight higher TF bias more heavily."""
        weights = {"1d": 3.0, "1h": 2.0, "15m": 1.5, "5m": 1.0, "1m": 0.5}
        weighted_sum = 0
        total_weight = 0

        for tf_name, tf_data in result.timeframes.items():
            w = weights.get(tf_name, 1.0)
            weighted_sum += tf_data.score * w
            total_weight += w

        if total_weight == 0:
            return TimeframeBias.NEUTRAL

        avg = weighted_sum / total_weight
        if avg > 40:
            return TimeframeBias.STRONG_BULLISH
        elif avg > 15:
            return TimeframeBias.BULLISH
        elif avg < -40:
            return TimeframeBias.STRONG_BEARISH
        elif avg < -15:
            return TimeframeBias.BEARISH
        return TimeframeBias.NEUTRAL

    def _check_entry_ready(self, result: MTFResult) -> bool:
        """Entry is ready when trend and structure agree with entry timing."""
        if result.alignment in (TimeframeAlignment.CONFLICTING,):
            return False
        if result.trend_tf and result.entry_tf:
            trend_bull = result.trend_tf.bias in (TimeframeBias.BULLISH, TimeframeBias.STRONG_BULLISH)
            entry_bull = result.entry_tf.bias in (TimeframeBias.BULLISH, TimeframeBias.STRONG_BULLISH)
            trend_bear = result.trend_tf.bias in (TimeframeBias.BEARISH, TimeframeBias.STRONG_BEARISH)
            entry_bear = result.entry_tf.bias in (TimeframeBias.BEARISH, TimeframeBias.STRONG_BEARISH)
            return (trend_bull and entry_bull) or (trend_bear and entry_bear)
        return result.alignment_score >= 60

    def _momentum_score(self, closes, ema9, ema20, ema50, rsi):
        """Compute momentum score (-100 to +100)."""
        price = closes[-1]
        score = 0

        # EMA position
        if price > ema9: score += 15
        else: score -= 15
        if price > ema20: score += 10
        else: score -= 10
        if price > ema50: score += 10
        else: score -= 10

        # EMA order
        if ema9 > ema20 > ema50: score += 20
        elif ema9 < ema20 < ema50: score -= 20

        # RSI
        if rsi > 60: score += 15
        elif rsi > 50: score += 5
        elif rsi < 40: score -= 15
        elif rsi < 50: score -= 5

        # Price rate of change
        if len(closes) >= 6:
            roc = (closes[-1] - closes[-6]) / closes[-6] * 100
            score += min(20, max(-20, roc * 5))

        return max(-100, min(100, score))

    def _volume_trend(self, volumes):
        """Classify volume trend."""
        if len(volumes) < 10:
            return "flat"
        recent_avg = np.mean(volumes[-5:])
        prev_avg = np.mean(volumes[-10:-5])
        ratio = recent_avg / prev_avg if prev_avg > 0 else 1
        if ratio > 1.3: return "increasing"
        elif ratio < 0.7: return "decreasing"
        return "flat"

    @staticmethod
    def _ema(data, period):
        if len(data) < period:
            return float(data[-1]) if len(data) > 0 else 0.0
        multiplier = 2 / (period + 1)
        ema = float(data[0])
        for val in data[1:]:
            ema = (float(val) - ema) * multiplier + ema
        return ema

    @staticmethod
    def _rsi(closes, period=14):
        if len(closes) < period + 1:
            return 50.0
        deltas = np.diff(closes)
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)
        avg_gain = np.mean(gains[-period:])
        avg_loss = np.mean(losses[-period:])
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))
