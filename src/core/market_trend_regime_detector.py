"""
Market Trend Regime Detector (V6)

Classifies market into 3 regimes for dip signal filtering:
- STRONG_TREND: Bullish conditions, allow signals
- CHOPPY: Neutral, downgrade confidence
- BEARISH: Weak conditions, block signals

Uses 5-minute timeframe with EMA structure, price position,
trend structure, and VWAP position.
"""

from dataclasses import dataclass
from typing import List, Optional, Tuple
from enum import Enum

from src.models.schemas import MarketTrendRegime, OHLCVBar


@dataclass
class RegimeFilterResult:
    """Result of market trend regime classification."""
    regime: MarketTrendRegime
    confidence_score: float  # 0-100
    reason: str  # Why classified this way
    
    # Individual component scores for debugging
    ema_score: float  # 0-100, based on EMA alignment
    price_vs_ema50: float  # Distance from EMA50 in %
    trend_structure_score: float  # 0-100, based on HH/HL or LH/LL
    vwap_score: float  # 0-100, based on price vs VWAP
    
    # Technical values
    ema9: float
    ema20: float
    ema50: float
    vwap: float
    current_price: float


class MarketTrendRegimeDetector:
    """
    V6: Detects market trend regime for dip signal filtering.
    
    Classification logic:
    - STRONG_TREND: All bullish conditions met
    - CHOPPY: Mixed or flat conditions
    - BEARISH: Bearish conditions dominate
    """
    
    def __init__(self):
        self.lookback_bars = 20  # For HH/HL detection
    
    def detect(self, bars: List[OHLCVBar]) -> RegimeFilterResult:
        """
        Detect market trend regime from price bars.
        
        Args:
            bars: List of OHLCVBar, should be 5-minute or higher timeframe
            
        Returns:
            RegimeFilterResult with regime classification and scores
        """
        if len(bars) < 50:  # Need enough bars for EMA50
            return RegimeFilterResult(
                regime=MarketTrendRegime.CHOPPY,
                confidence_score=50.0,
                reason="Insufficient data for regime detection",
                ema_score=50.0,
                price_vs_ema50=0.0,
                trend_structure_score=50.0,
                vwap_score=50.0,
                ema9=0.0,
                ema20=0.0,
                ema50=0.0,
                vwap=0.0,
                current_price=bars[-1].close if bars else 0.0
            )
        
        # Get current price
        current_price = bars[-1].close
        
        # Calculate EMAs
        ema9 = self._calculate_ema(bars, 9)
        ema20 = self._calculate_ema(bars, 20)
        ema50 = self._calculate_ema(bars, 50)
        
        # Calculate VWAP
        vwap = self._calculate_vwap(bars)
        
        # Component 1: EMA Structure Score
        ema_score = self._score_ema_structure(current_price, ema9, ema20, ema50)
        
        # Component 2: Price vs EMA50
        price_vs_ema50_pct = ((current_price - ema50) / ema50) * 100
        
        # Component 3: Trend Structure (HH/HL or LH/LL)
        trend_score = self._score_trend_structure(bars)
        
        # Component 4: VWAP Score
        vwap_score = self._score_vwap_position(current_price, vwap)
        
        # Classify regime
        regime, confidence, reason = self._classify_regime(
            ema_score, price_vs_ema50_pct, trend_score, vwap_score,
            current_price, ema9, ema20, ema50, vwap
        )
        
        return RegimeFilterResult(
            regime=regime,
            confidence_score=confidence,
            reason=reason,
            ema_score=ema_score,
            price_vs_ema50=price_vs_ema50_pct,
            trend_structure_score=trend_score,
            vwap_score=vwap_score,
            ema9=ema9,
            ema20=ema20,
            ema50=ema50,
            vwap=vwap,
            current_price=current_price
        )
    
    def _calculate_ema(self, bars: List[OHLCVBar], period: int) -> float:
        """Calculate EMA for given period."""
        if len(bars) < period:
            return bars[-1].close if bars else 0.0
        
        # Use closing prices
        prices = [bar.close for bar in bars]
        
        # Calculate SMA for first value
        sma = sum(prices[-period:]) / period
        
        # Calculate EMA
        multiplier = 2 / (period + 1)
        ema = sma
        
        for price in prices[-(period-1):]:
            ema = (price - ema) * multiplier + ema
        
        return ema
    
    def _calculate_vwap(self, bars: List[OHLCVBar]) -> float:
        """Calculate VWAP from bars."""
        if not bars:
            return 0.0
        
        # Use last 20 bars for intraday VWAP
        recent_bars = bars[-20:] if len(bars) >= 20 else bars
        
        total_pv = 0.0
        total_volume = 0.0
        
        for bar in recent_bars:
            typical_price = (bar.high + bar.low + bar.close) / 3
            total_pv += typical_price * bar.volume
            total_volume += bar.volume
        
        return total_pv / total_volume if total_volume > 0 else 0.0
    
    def _score_ema_structure(self, price: float, ema9: float, ema20: float, ema50: float) -> float:
        """
        Score EMA structure from 0-100.
        
        Bullish: price > ema9 > ema20 > ema50
        Bearish: price < ema9 < ema20 < ema50
        """
        # Check perfect bullish alignment
        if price > ema9 > ema20 > ema50:
            # Calculate how strong the alignment is
            spread_pct = ((price - ema50) / ema50) * 100
            return min(100.0, 80.0 + spread_pct * 2)  # 80-100 range
        
        # Check perfect bearish alignment
        if price < ema9 < ema20 < ema50:
            return 0.0
        
        # Mixed alignment - calculate score
        score = 50.0
        
        # Price vs EMA9
        if price > ema9:
            score += 15
        else:
            score -= 15
        
        # EMA9 vs EMA20
        if ema9 > ema20:
            score += 10
        else:
            score -= 10
        
        # EMA20 vs EMA50
        if ema20 > ema50:
            score += 10
        else:
            score -= 10
        
        return max(0.0, min(100.0, score))
    
    def _score_trend_structure(self, bars: List[OHLCVBar]) -> float:
        """
        Score trend structure based on Higher Highs/Higher Lows or Lower Highs/Lower Lows.
        
        Returns 0-100 score where:
        - 100 = Strong uptrend (HH + HL)
        - 50 = No clear trend
        - 0 = Strong downtrend (LH + LL)
        """
        if len(bars) < self.lookback_bars:
            return 50.0
        
        recent_bars = bars[-self.lookback_bars:]
        
        # Find highs and lows
        highs = [bar.high for bar in recent_bars]
        lows = [bar.low for bar in recent_bars]
        
        # Count higher highs vs lower highs
        hh_count = 0
        lh_count = 0
        
        for i in range(1, len(highs)):
            if highs[i] > highs[i-1]:
                hh_count += 1
            elif highs[i] < highs[i-1]:
                lh_count += 1
        
        # Count higher lows vs lower lows
        hl_count = 0
        ll_count = 0
        
        for i in range(1, len(lows)):
            if lows[i] > lows[i-1]:
                hl_count += 1
            elif lows[i] < lows[i-1]:
                ll_count += 1
        
        # Calculate score
        total_highs = hh_count + lh_count
        total_lows = hl_count + ll_count
        
        if total_highs == 0 or total_lows == 0:
            return 50.0
        
        # HH score (0-50)
        hh_score = (hh_count / total_highs) * 50 if total_highs > 0 else 25
        
        # HL score (0-50)
        hl_score = (hl_count / total_lows) * 50 if total_lows > 0 else 25
        
        return hh_score + hl_score
    
    def _score_vwap_position(self, price: float, vwap: float) -> float:
        """
        Score based on price position relative to VWAP.
        
        Above VWAP = bullish (50-100)
        Below VWAP = bearish (0-50)
        """
        if vwap == 0:
            return 50.0
        
        distance_pct = ((price - vwap) / vwap) * 100
        
        # Map -2% to +2% range to 0-100 score
        # -2% or below = 0 score
        # +2% or above = 100 score
        score = 50.0 + (distance_pct * 25)  # 1% = 25 points
        
        return max(0.0, min(100.0, score))
    
    def _classify_regime(
        self,
        ema_score: float,
        price_vs_ema50_pct: float,
        trend_score: float,
        vwap_score: float,
        price: float,
        ema9: float,
        ema20: float,
        ema50: float,
        vwap: float
    ) -> Tuple[MarketTrendRegime, float, str]:
        """
        Classify market regime based on component scores.
        
        Returns: (regime, confidence_score, reason)
        """
        # STRONG_TREND conditions (all must be met)
        strong_trend_conditions = [
            price > ema50,
            ema9 > ema20 > ema50,
            price > vwap,
            ema_score >= 70,
            trend_score >= 60,
            vwap_score >= 60
        ]
        
        if all(strong_trend_conditions):
            confidence = (ema_score + trend_score + vwap_score) / 3
            return (
                MarketTrendRegime.STRONG_TREND,
                confidence,
                f"Strong bullish alignment: price({price:.2f})>EMA50({ema50:.2f}), "
                f"EMA9>EMA20>EMA50, price>VWAP, HH/HL structure, score={confidence:.1f}"
            )
        
        # BEARISH conditions (any dominant)
        bearish_conditions_met = sum([
            price < ema50,
            ema9 < ema20 < ema50,
            price < vwap,
            ema_score <= 30,
            trend_score <= 40,
            vwap_score <= 40
        ])
        
        if bearish_conditions_met >= 4:  # 4+ bearish signals
            confidence = 100 - ((ema_score + trend_score + vwap_score) / 3)
            return (
                MarketTrendRegime.BEARISH,
                confidence,
                f"Bearish conditions dominate: price({price:.2f})<EMA50({ema50:.2f}), "
                f"trend_score={trend_score:.1f}, vwap_score={vwap_score:.1f}"
            )
        
        # CHOPPY (mixed conditions)
        confidence = 50.0
        mixed_reasons = []
        
        if not (ema9 > ema20 > ema50 or ema9 < ema20 < ema50):
            mixed_reasons.append("EMAs not aligned")
        
        if 40 <= trend_score <= 60:
            mixed_reasons.append("No clear trend structure")
        
        if abs(price_vs_ema50_pct) < 2:
            mixed_reasons.append("Price near EMA50")
        
        if abs(((price - vwap) / vwap) * 100) < 1:
            mixed_reasons.append("Price near VWAP")
        
        reason = " | ".join(mixed_reasons) if mixed_reasons else "Mixed market conditions"
        
        return (
            MarketTrendRegime.CHOPPY,
            confidence,
            f"Choppy/Neutral: {reason}"
        )
