"""Higher Timeframe Bias Detector — V8"""
import logging
from dataclasses import dataclass
from typing import List, Optional, Tuple
from enum import Enum
import numpy as np
from src.models.schemas import OHLCVBar

logger = logging.getLogger(__name__)

class HTFBias(Enum):
    BULLISH = "BULLISH"
    NEUTRAL = "NEUTRAL"
    BEARISH = "BEARISH"

class AlignmentStatus(Enum):
    ALIGNED = "ALIGNED"
    NEUTRAL = "NEUTRAL"
    COUNTER_TREND = "COUNTER_TREND"

class TradeType(Enum):
    TREND_FOLLOWING = "TREND_FOLLOWING"
    COUNTER_TREND_REVERSAL = "COUNTER_TREND_REVERSAL"

@dataclass
class HTFBiasResult:
    ticker: str
    bias: HTFBias
    strength_score: float
    reasoning: List[str]
    structure_score: float
    ema_alignment_score: float
    momentum_score: float
    adx_score: float
    ema20: float
    ema50: float
    rsi: float
    adx: float
    current_price: float

@dataclass
class HTFAlignmentResult:
    ticker: str
    htf_bias: HTFBias
    htf_strength: float
    alignment_status: AlignmentStatus
    trade_type: TradeType
    confidence_adjustment: int
    allowed: bool
    reason: str

class HigherTimeframeBiasDetector:
    """V8: Detects HTF (DAILY) bias using weighted multi-factor scoring."""
    
    def __init__(self):
        self.lookback_bars = 20
        self.adx_period = 14
        self.rsi_period = 14
        self.structure_weight = 0.30
        self.ema_weight = 0.25
        self.momentum_weight = 0.25
        self.adx_weight = 0.20
    
    def detect_bias(self, ticker: str, bars: List[OHLCVBar]) -> Optional[HTFBiasResult]:
        """Analyze DAILY timeframe bars to determine HTF bias."""
        if len(bars) < 50:
            return self._neutral_fallback(ticker, bars)
        
        closes = np.array([b.close for b in bars])
        highs = np.array([b.high for b in bars])
        lows = np.array([b.low for b in bars])
        current_price = float(closes[-1])
        
        ema20 = self._calculate_ema(closes, 20)
        ema50 = self._calculate_ema(closes, 50)
        rsi = self._calculate_rsi(closes, self.rsi_period)
        adx = self._calculate_adx(highs, lows, closes, self.adx_period)
        
        structure_score, structure_reason = self._score_structure(highs, lows)
        ema_score, ema_reason = self._score_ma_alignment(current_price, ema20, ema50)
        momentum_score, momentum_reason = self._score_momentum(rsi)
        adx_score, adx_reason = self._score_trend_strength(adx)
        
        composite_score = (
            structure_score * self.structure_weight +
            ema_score * self.ema_weight +
            momentum_score * self.momentum_weight +
            adx_score * self.adx_weight
        )
        
        bias, reasoning = self._classify_bias(composite_score,
            [structure_reason, ema_reason, momentum_reason, adx_reason])
        
        return HTFBiasResult(
            ticker=ticker, bias=bias, strength_score=round(composite_score, 1),
            reasoning=reasoning, structure_score=round(structure_score, 1),
            ema_alignment_score=round(ema_score, 1),
            momentum_score=round(momentum_score, 1),
            adx_score=round(adx_score, 1),
            ema20=ema20, ema50=ema50, rsi=rsi, adx=adx,
            current_price=current_price
        )
    
    def _neutral_fallback(self, ticker: str, bars: List[OHLCVBar]) -> HTFBiasResult:
        price = bars[-1].close if bars else 0.0
        return HTFBiasResult(
            ticker=ticker, bias=HTFBias.NEUTRAL, strength_score=50.0,
            reasoning=["Insufficient daily data, defaulting to NEUTRAL"],
            structure_score=50.0, ema_alignment_score=50.0,
            momentum_score=50.0, adx_score=50.0,
            ema20=price, ema50=price, rsi=50.0, adx=20.0,
            current_price=price
        )
    
    def _score_structure(self, highs: np.ndarray, lows: np.ndarray) -> Tuple[float, str]:
        lookback = self.lookback_bars
        if len(highs) < lookback + 5:
            return 50.0, "Insufficient data"
        
        recent_highs = highs[-lookback:]
        recent_lows = lows[-lookback:]
        
        hh_count = sum(1 for i in range(1, len(recent_highs)) if recent_highs[i] > recent_highs[i-1])
        lh_count = sum(1 for i in range(1, len(recent_highs)) if recent_highs[i] < recent_highs[i-1])
        hl_count = sum(1 for i in range(1, len(recent_lows)) if recent_lows[i] > recent_lows[i-1])
        ll_count = sum(1 for i in range(1, len(recent_lows)) if recent_lows[i] < recent_lows[i-1])
        
        total = hh_count + lh_count + hl_count + ll_count
        if total == 0:
            return 50.0, "No clear swings"
        
        bullish = (hh_count + hl_count) / total * 100
        
        if bullish >= 75:
            reason = f"Strong bullish: {hh_count} HH, {hl_count} HL"
        elif bullish >= 60:
            reason = "Bullish structure"
        elif bullish >= 40:
            reason = "Neutral structure"
        elif bullish >= 25:
            reason = "Bearish structure"
        else:
            reason = f"Strong bearish: {lh_count} LH, {ll_count} LL"
        
        return bullish, reason
    
    def _score_ma_alignment(self, price: float, ema20: float, ema50: float) -> Tuple[float, str]:
        score = 50.0
        reasons = []
        
        if price > ema20:
            score += 15
            reasons.append("Price > EMA20")
        else:
            score -= 15
            reasons.append("Price < EMA20")
        
        if price > ema50:
            score += 15
            reasons.append("Price > EMA50")
        else:
            score -= 15
            reasons.append("Price < EMA50")
        
        if ema20 > ema50:
            score += 20
            reasons.append("EMA20 > EMA50")
        elif ema20 < ema50:
            score -= 20
            reasons.append("EMA20 < EMA50")
        
        return max(0.0, min(100.0, score)), " | ".join(reasons)
    
    def _score_momentum(self, rsi: float) -> Tuple[float, str]:
        if rsi > 60:
            return 80.0, f"RSI {rsi:.1f} > 60 (strong)"
        elif rsi > 55:
            return 70.0, f"RSI {rsi:.1f} > 55 (bullish)"
        elif rsi > 50:
            return 60.0, f"RSI {rsi:.1f} > 50 (slight)"
        elif rsi > 45:
            return 40.0, f"RSI {rsi:.1f} < 50 (slight bear)"
        elif rsi > 40:
            return 30.0, f"RSI {rsi:.1f} < 45 (bearish)"
        else:
            return 20.0, f"RSI {rsi:.1f} < 40 (strong bear)"
    
    def _score_trend_strength(self, adx: float) -> Tuple[float, str]:
        if adx > 35:
            return 90.0, f"ADX {adx:.1f} > 35 (very strong)"
        elif adx > 25:
            return 80.0, f"ADX {adx:.1f} > 25 (strong)"
        elif adx > 20:
            return 65.0, f"ADX {adx:.1f} 20-25 (moderate)"
        elif adx > 15:
            return 45.0, f"ADX {adx:.1f} 15-20 (weak)"
        else:
            return 30.0, f"ADX {adx:.1f} < 15 (choppy)"
    
    def _classify_bias(self, score: float, reasons: List[str]) -> Tuple[HTFBias, List[str]]:
        out_reasons = []
        if score >= 70:
            bias = HTFBias.BULLISH
            out_reasons.append(f"HTF BULLISH ({score:.1f}/100)")
        elif score >= 40:
            bias = HTFBias.NEUTRAL
            out_reasons.append(f"HTF NEUTRAL ({score:.1f}/100)")
        else:
            bias = HTFBias.BEARISH
            out_reasons.append(f"HTF BEARISH ({score:.1f}/100)")
        out_reasons.extend(reasons)
        return bias, out_reasons
    
    def _calculate_ema(self, data: np.ndarray, period: int) -> float:
        if len(data) < period:
            return float(np.mean(data))
        multiplier = 2 / (period + 1)
        ema = float(data[0])
        for val in data[1:]:
            ema = (float(val) - ema) * multiplier + ema
        return ema
    
    def _calculate_rsi(self, closes: np.ndarray, period: int = 14) -> float:
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
    
    def _calculate_adx(self, highs: np.ndarray, lows: np.ndarray, 
                       closes: np.ndarray, period: int = 14) -> float:
        if len(highs) < period + 1:
            return 20.0
        
        tr_list = []
        plus_dm_list = []
        minus_dm_list = []
        
        for i in range(1, len(highs)):
            tr = max(highs[i] - lows[i], 
                    abs(highs[i] - closes[i-1]), 
                    abs(lows[i] - closes[i-1]))
            tr_list.append(tr)
            
            plus_dm = highs[i] - highs[i-1] if highs[i] - highs[i-1] > lows[i-1] - lows[i] else 0
            minus_dm = lows[i-1] - lows[i] if lows[i-1] - lows[i] > highs[i] - highs[i-1] else 0
            plus_dm_list.append(plus_dm)
            minus_dm_list.append(minus_dm)
        
        if len(tr_list) < period:
            return 20.0
        
        atr = float(np.mean(tr_list[-period:]))
        plus_di = float(np.mean(plus_dm_list[-period:])) / atr * 100 if atr > 0 else 0
        minus_di = float(np.mean(minus_dm_list[-period:])) / atr * 100 if atr > 0 else 0
        
        dx = abs(plus_di - minus_di) / (plus_di + minus_di) * 100 if (plus_di + minus_di) > 0 else 0
        return dx


class HTFAlignmentEvaluator:
    """Evaluates alignment between HTF bias and LTF signal."""
    
    def __init__(self, min_htf_strength: float = 40.0):
        self.min_htf_strength = min_htf_strength
    
    def evaluate_alignment(
        self,
        ticker: str,
        htf_result: HTFBiasResult,
        ltf_can_buy: bool,
        ict: Optional[object],
        early_bearish_warning: bool = False
    ) -> HTFAlignmentResult:
        """Evaluate HTF-LTF alignment using CASE 1-3 rules."""
        bias = htf_result.bias
        strength = htf_result.strength_score
        
        # Trend quality filter: weak HTF treated as NEUTRAL
        if strength < self.min_htf_strength:
            bias = HTFBias.NEUTRAL
        
        if not ltf_can_buy:
            return HTFAlignmentResult(
                ticker=ticker, htf_bias=bias, htf_strength=strength,
                alignment_status=AlignmentStatus.NEUTRAL,
                trade_type=TradeType.TREND_FOLLOWING,
                confidence_adjustment=0, allowed=False,
                reason="LTF not ready for entry"
            )
        
        # CASE 1: Strong Long (Ideal)
        if bias == HTFBias.BULLISH:
            return HTFAlignmentResult(
                ticker=ticker, htf_bias=bias, htf_strength=strength,
                alignment_status=AlignmentStatus.ALIGNED,
                trade_type=TradeType.TREND_FOLLOWING,
                confidence_adjustment=15, allowed=True,
                reason="CASE 1: HTF BULLISH + LTF BUY → Ideal trend following"
            )
        
        # CASE 2: Neutral Environment
        if bias == HTFBias.NEUTRAL:
            can_enter = self._check_neutral_requirements(ict)
            if can_enter:
                return HTFAlignmentResult(
                    ticker=ticker, htf_bias=bias, htf_strength=strength,
                    alignment_status=AlignmentStatus.NEUTRAL,
                    trade_type=TradeType.TREND_FOLLOWING,
                    confidence_adjustment=-10, allowed=True,
                    reason="CASE 2: HTF NEUTRAL + LTF BUY → Allowed with caution"
                )
            else:
                return HTFAlignmentResult(
                    ticker=ticker, htf_bias=bias, htf_strength=strength,
                    alignment_status=AlignmentStatus.NEUTRAL,
                    trade_type=TradeType.TREND_FOLLOWING,
                    confidence_adjustment=-20, allowed=False,
                    reason="CASE 2: HTF NEUTRAL but LTF confirmation insufficient"
                )
        
        # CASE 3: Counter-Trend (Dangerous)
        if bias == HTFBias.BEARISH:
            is_exception = self._check_counter_trend_exception(
                ict, early_bearish_warning
            )
            
            if is_exception:
                return HTFAlignmentResult(
                    ticker=ticker, htf_bias=bias, htf_strength=strength,
                    alignment_status=AlignmentStatus.COUNTER_TREND,
                    trade_type=TradeType.COUNTER_TREND_REVERSAL,
                    confidence_adjustment=-30, allowed=True,
                    reason="CASE 3 EXCEPTION: HTF BEARISH + LTF BUY → Valid reversal (all conditions met)"
                )
            else:
                return HTFAlignmentResult(
                    ticker=ticker, htf_bias=bias, htf_strength=strength,
                    alignment_status=AlignmentStatus.COUNTER_TREND,
                    trade_type=TradeType.TREND_FOLLOWING,
                    confidence_adjustment=-50, allowed=False,
                    reason="CASE 3 BLOCKED: HTF BEARISH + LTF BUY → Counter-trend rejected"
                )
        
        return HTFAlignmentResult(
            ticker=ticker, htf_bias=bias, htf_strength=strength,
            alignment_status=AlignmentStatus.NEUTRAL,
            trade_type=TradeType.TREND_FOLLOWING,
            confidence_adjustment=0, allowed=False,
            reason="Unknown bias state"
        )
    
    def _check_neutral_requirements(self, ict: Optional[object]) -> bool:
        """Check if LTF has strong enough confirmation in neutral HTF."""
        if not ict:
            return False
        # Require stronger confirmation in neutral environment
        has_sweep = getattr(ict, 'liquidity_sweep', False)
        has_reclaim = getattr(ict, 'structure_reclaimed', False)
        has_break = getattr(ict, 'structure_break_confirmed', False)
        not_overextended = not getattr(ict, 'is_overextended', False)
        
        # Require at least 2 of: sweep, reclaim, break, and not overextended
        conditions_met = sum([has_sweep, has_reclaim, has_break])
        return conditions_met >= 2 and not_overextended
    
    def _check_counter_trend_exception(
        self, 
        ict: Optional[object],
        early_bearish_warning: bool
    ) -> bool:
        """
        Check if counter-trend trade meets exception criteria.
        ALL must be true:
        1. Liquidity sweep detected
        2. Structure reclaim confirmed
        3. Strong momentum reversal
        4. No early bearish warning
        """
        if not ict:
            return False
        
        # Early bearish kills counter-trend immediately
        if early_bearish_warning:
            return False
        
        has_sweep = getattr(ict, 'liquidity_sweep', False)
        has_reclaim = getattr(ict, 'structure_reclaimed', False)
        
        # Check momentum reversal (velocity improving)
        momentum_ok = False
        if hasattr(ict, 'price_velocity'):
            velocity = ict.price_velocity
            if isinstance(velocity, (int, float)) and velocity > -0.5:
                momentum_ok = True
        else:
            # Fallback: check if structure break confirmed but not extreme
            momentum_ok = getattr(ict, 'structure_break_confirmed', False)
        
        return has_sweep and has_reclaim and momentum_ok
