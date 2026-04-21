"""Professional Grade Stock Discovery Engine — V6. 19-Layer Market Scanner."""

import logging
from typing import Optional, List, Dict, Tuple
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import numpy as np
import pandas as pd
import yfinance as yf
from src.models.schemas import OHLCVBar

logger = logging.getLogger(__name__)

class CatalystTier(str, Enum): TIER_1 = "tier_1"; TIER_2 = "tier_2"; TIER_3 = "tier_3"; NONE = "none"
class CatalystFreshness(str, Enum): FRESH = "fresh"; AGING = "aging"; STALE = "stale"; NONE = "none"
class PremarketStatus(str, Enum): STRONG = "strong"; WEAK = "weak"; NONE = "none"
class VolumeTrend(str, Enum): INCREASING = "increasing"; STABLE = "stable"; DECREASING = "decreasing"; SINGLE_SPIKE = "single_spike"
class StructureQuality(str, Enum): CLEAN_TREND = "clean_trend"; CHOPPY = "choppy"; WEAKENING = "weakening"; BROKEN = "broken"
class ExtensionState(str, Enum): EARLY = "early"; MID = "mid"; EXTENDED = "extended"
class LiquidityQuality(str, Enum): HIGH = "high"; ACCEPTABLE = "acceptable"; POOR = "poor"
class StockType(str, Enum): PENNY = "penny"; MICRO = "micro"; SMALL = "small"; LARGE = "large"
class InPlayStatus(str, Enum): ACTIVE = "active"; FADING = "fading"; DEAD = "dead"
class SetupReadiness(str, Enum): READY_FOR_DIP = "ready_for_dip"; BREAKOUT_CANDIDATE = "breakout_candidate"; EXTENDED = "extended"; AVOID = "avoid"
class TimeframeAlignment(str, Enum): BULLISH = "bullish"; MIXED = "mixed"; CONFLICTING = "conflicting"
class GapBehavior(str, Enum): GAP_AND_GO = "gap_and_go"; GAP_AND_FADE = "gap_and_fade"; RECLAIM_ATTEMPT = "reclaim_attempt"; NO_GAP = "no_gap"
class MarketRelativeStrength(str, Enum): OUTPERFORMING = "outperforming"; INLINE = "inline"; LAGGING = "lagging"

@dataclass
class CatalystInfo:
    headline: str = ""; timestamp: Optional[datetime] = None; tier: CatalystTier = CatalystTier.NONE
    freshness: CatalystFreshness = CatalystFreshness.NONE; sentiment: str = "neutral"; source: str = ""

@dataclass
class PremarketData:
    gap_percent: float = 0.0; volume: float = 0.0; avg_volume_20d: float = 0.0
    volume_vs_avg: float = 0.0; volume_as_pct_of_float: float = 0.0
    status: PremarketStatus = PremarketStatus.NONE; holding_highs: bool = False
    fading: bool = False; reclaiming: bool = False

@dataclass
class LiquidityMetrics:
    spread_pct: float = 0.0; spread_vs_candle_range: float = 0.0; avg_candle_range: float = 0.0
    quality: LiquidityQuality = LiquidityQuality.ACCEPTABLE; erratic_score: float = 0.0

@dataclass
class RiskFlags:
    halt_risk: bool = False; abnormal_candle_expansion: bool = False; erratic_behavior: bool = False
    recent_halts: int = 0; risk_level: str = "normal"

@dataclass
class StructureMetrics:
    higher_highs: bool = False; higher_lows: bool = False; lower_highs: bool = False; lower_lows: bool = False
    compression_near_highs: bool = False; failed_breakouts: int = 0
    gap_behavior: GapBehavior = GapBehavior.NO_GAP; quality: StructureQuality = StructureQuality.CHOPPY

@dataclass
class MultiTimeframeData:
    trend_1m: str = "neutral"; trend_5m: str = "neutral"; trend_15m: str = "neutral"
    alignment: TimeframeAlignment = TimeframeAlignment.MIXED

@dataclass
class ProfessionalStockData:
    ticker: str; price: float; volume: float; rvol: Optional[float] = None
    change_percent: Optional[float] = None; market_cap: Optional[float] = None
    float_shares: Optional[float] = None; scan_type: str = "professional"
    premarket: Optional[PremarketData] = None; volume_trend: VolumeTrend = VolumeTrend.STABLE
    volume_as_pct_of_float: float = 0.0; sustained_participation: bool = False
    catalyst: Optional[CatalystInfo] = None; has_catalyst: bool = False
    structure: Optional[StructureMetrics] = None; distance_from_vwap: float = 0.0
    distance_from_high: float = 0.0; extension_pct: float = 0.0
    extension_state: ExtensionState = ExtensionState.EARLY
    liquidity: Optional[LiquidityMetrics] = None; stock_type: StockType = StockType.SMALL
    float_category: str = "unknown"; risk: Optional[RiskFlags] = None
    timeframe_data: Optional[MultiTimeframeData] = None; rejection_risk_score: float = 0.0
    proximity_to_resistance: float = 0.0; failed_highs_count: int = 0
    upper_wick_pressure: bool = False; relative_strength: MarketRelativeStrength = MarketRelativeStrength.INLINE
    spy_correlation: float = 0.0; outperformance_pct: float = 0.0; sector: str = "unknown"
    theme: str = "unknown"; theme_momentum: str = "neutral"; in_play_status: InPlayStatus = InPlayStatus.FADING
    setup_readiness: SetupReadiness = SetupReadiness.AVOID; analyze_for_dip: bool = False
    breakout_candidate: bool = False; monitor_bearish_shift: bool = False
    final_score: float = 0.0; scan_rank: int = 0
    positive_reasons: List[str] = field(default_factory=list); negative_reasons: List[str] = field(default_factory=list)
    key_risks: List[str] = field(default_factory=list); excluded: bool = False; exclusion_reason: str = ""
    tags: List[str] = field(default_factory=list); passed_to_main: bool = False


class ProfessionalScanner:
    def __init__(self, max_results: int = 20): self.max_results = max_results; self._spy_data = None; self._qqq_data = None

    def scan_universe(self, tickers: List[str]) -> List[ProfessionalStockData]:
        logger.info("ProfessionalScanner: Analyzing %d stocks", len(tickers))
        self._load_market_data()
        results = []
        for ticker in tickers:
            try:
                stock = self._analyze_stock(ticker)
                if stock and not stock.excluded: results.append(stock)
            except Exception as exc: logger.warning("Failed to analyze %s: %s", ticker, exc)
        for stock in results: self._calculate_final_score(stock)
        results.sort(key=lambda x: x.final_score, reverse=True)
        for i, stock in enumerate(results[:self.max_results], 1):
            stock.scan_rank = i; stock.passed_to_main = stock.final_score >= 60
            self._assign_tags(stock)
        logger.info("ProfessionalScanner: Returning top %d", min(len(results), self.max_results))
        return results[:self.max_results]

    def _analyze_stock(self, ticker: str) -> Optional[ProfessionalStockData]:
        bars_1m, bars_5m, bars_15m, info = self._fetch_data(ticker)
        if bars_1m is None or len(bars_1m) < 10: return None
        current_price = bars_1m[-1].close if bars_1m else 0
        volume_today = sum(b.volume for b in bars_1m)
        float_shares = info.get("floatShares") or info.get("sharesOutstanding", 0)
        market_cap = info.get("marketCap", 0)
        prev_close = info.get("previousClose", current_price)
        change_pct = ((current_price - prev_close) / prev_close * 100) if prev_close > 0 else 0

        stock = ProfessionalStockData(
            ticker=ticker, price=current_price, volume=volume_today,
            change_percent=round(change_pct, 2), market_cap=market_cap,
            float_shares=float_shares, scan_type="professional")

        self._classify_type(stock)
        stock.premarket = self._analyze_premarket(ticker, float_shares, prev_close)
        self._analyze_volume(stock, bars_1m, float_shares)
        stock.catalyst = self._fetch_catalyst(ticker); stock.has_catalyst = stock.catalyst and stock.catalyst.tier != CatalystTier.NONE
        stock.structure = self._analyze_structure(bars_1m, bars_5m, prev_close)
        self._analyze_extension(stock, bars_1m)
        stock.liquidity = self._analyze_liquidity(bars_1m)
        stock.risk = self._assess_risk(bars_1m, stock.stock_type)
        stock.timeframe_data = self._analyze_timeframes(bars_1m, bars_5m, bars_15m)
        self._assess_rejection(stock, bars_1m)
        self._calc_relative_strength(stock, change_pct)
        stock.sector = info.get("sector", "unknown"); stock.theme = self._identify_theme(ticker, stock.sector)
        self._validate_in_play(stock); self._apply_exclusion(stock)
        if stock.excluded: return stock
        self._classify_setup(stock); self._build_reasons(stock)
        return stock

    def _fetch_data(self, ticker: str):
        try:
            ticker_obj = yf.Ticker(ticker); info = ticker_obj.info
            df_1m = ticker_obj.history(period="1d", interval="1m")
            bars_1m = self._df_to_bars(df_1m) if not df_1m.empty else []
            df_5m = ticker_obj.history(period="5d", interval="5m")
            bars_5m = self._df_to_bars(df_5m) if not df_5m.empty else []
            df_15m = ticker_obj.history(period="5d", interval="15m")
            bars_15m = self._df_to_bars(df_15m) if not df_15m.empty else []
            return bars_1m, bars_5m, bars_15m, info
        except Exception as exc: logger.warning("Fetch failed %s: %s", ticker, exc); return None, None, None, {}

    def _df_to_bars(self, df: pd.DataFrame) -> List[OHLCVBar]:
        bars = []
        for idx, row in df.iterrows():
            bars.append(OHLCVBar(
                timestamp=idx.to_pydatetime() if hasattr(idx, 'to_pydatetime') else datetime.now(),
                open=float(row["Open"]), high=float(row["High"]), low=float(row["Low"]),
                close=float(row["Close"]), volume=int(row["Volume"])))
        return bars

    def _load_market_data(self):
        try:
            self._spy_data = yf.Ticker("SPY").history(period="1d", interval="5m")
            self._qqq_data = yf.Ticker("QQQ").history(period="1d", interval="5m")
        except Exception as exc: logger.warning("Market data load failed: %s", exc)

    def _classify_type(self, stock: ProfessionalStockData):
        p = stock.price
        if p < 1.0: stock.stock_type = StockType.PENNY
        elif p < 5.0: stock.stock_type = StockType.MICRO
        elif p < 20.0: stock.stock_type = StockType.SMALL
        else: stock.stock_type = StockType.LARGE
        if stock.float_shares:
            if stock.float_shares < 10_000_000: stock.float_category = "low"
            elif stock.float_shares < 100_000_000: stock.float_category = "medium"
            else: stock.float_category = "high"

    def _analyze_premarket(self, ticker: str, float_shares: float, prev_close: float) -> PremarketData:
        pre = PremarketData()
        try:
            ticker_obj = yf.Ticker(ticker)
            df = ticker_obj.history(period="1d", interval="1m", prepost=True)
            if not df.empty and len(df) > 0:
                first_price = df["Close"].iloc[0]
                pre.gap_percent = ((first_price - prev_close) / prev_close * 100) if prev_close > 0 else 0
                pre.volume = int(df["Volume"].sum())
            hist = ticker_obj.history(period="1mo")
            if not hist.empty:
                pre.avg_volume_20d = float(hist["Volume"].mean())
                if pre.avg_volume_20d > 0: pre.volume_vs_avg = pre.volume / pre.avg_volume_20d
            if float_shares > 0: pre.volume_as_pct_of_float = (pre.volume / float_shares) * 100
            if pre.volume_vs_avg > 2.0 and abs(pre.gap_percent) > 3:
                pre.status = PremarketStatus.STRONG; pre.holding_highs = pre.gap_percent > 0
            elif pre.volume_vs_avg < 0.5: pre.status = PremarketStatus.WEAK; pre.fading = True
            else: pre.status = PremarketStatus.NONE
        except Exception as exc: logger.debug("Premarket failed %s: %s", ticker, exc)
        return pre

    def _analyze_volume(self, stock: ProfessionalStockData, bars: List[OHLCVBar], float_shares: float):
        if not bars: return
        volumes = [b.volume for b in bars]
        stock.volume_as_pct_of_float = (stock.volume / float_shares * 100) if float_shares > 0 else 0
        first_half = volumes[:len(volumes)//2]; second_half = volumes[len(volumes)//2:]
        avg_first = np.mean(first_half) if first_half else 0
        avg_second = np.mean(second_half) if second_half else 0
        if avg_second > avg_first * 1.3: stock.volume_trend = VolumeTrend.INCREASING
        elif avg_second < avg_first * 0.7: stock.volume_trend = VolumeTrend.DECREASING
        else: stock.volume_trend = VolumeTrend.STABLE
        max_vol = max(volumes); spike_idx = volumes.index(max_vol)
        if spike_idx < len(volumes) * 0.3 and avg_second < avg_first * 0.5: stock.volume_trend = VolumeTrend.SINGLE_SPIKE
        stock.sustained_participation = stock.volume_trend == VolumeTrend.INCREASING or (stock.volume_as_pct_of_float > 10)

    def _fetch_catalyst(self, ticker: str) -> Optional[CatalystInfo]:
        # Simplified catalyst detection - can be enhanced with news API
        cat = CatalystInfo()
        try:
            ticker_obj = yf.Ticker(ticker)
            news = ticker_obj.news if hasattr(ticker_obj, 'news') else []
            if news and len(news) > 0:
                latest = news[0]
                cat.headline = latest.get('title', '')
                cat.source = latest.get('publisher', '')
                cat.timestamp = datetime.now()  # Simplified
                headline_lower = cat.headline.lower()
                tier1_keywords = ['earnings', 'fda', 'approval', 'contract', 'merger', 'acquisition', 'settlement']
                tier2_keywords = ['partnership', 'upgrade', 'downgrade', 'initiated', 'target']
                if any(k in headline_lower for k in tier1_keywords): cat.tier = CatalystTier.TIER_1
                elif any(k in headline_lower for k in tier2_keywords): cat.tier = CatalystTier.TIER_2
                else: cat.tier = CatalystTier.TIER_3
                positive = ['beat', 'strong', 'growth', 'approval', 'contract', 'upgrade']
                negative = ['miss', 'weak', 'downgrade', 'delay', 'reject']
                if any(k in headline_lower for k in positive): cat.sentiment = "positive"
                elif any(k in headline_lower for k in negative): cat.sentiment = "negative"
                else: cat.sentiment = "neutral"
                cat.freshness = CatalystFreshness.FRESH
        except Exception as exc: logger.debug("Catalyst fetch failed %s: %s", ticker, exc)
        return cat

    def _analyze_structure(self, bars_1m: List[OHLCVBar], bars_5m: List[OHLCVBar], prev_close: float) -> StructureMetrics:
        struct = StructureMetrics()
        if not bars_1m or len(bars_1m) < 10: return struct
        highs = [b.high for b in bars_1m]; lows = [b.low for b in bars_1m]; closes = [b.close for b in bars_1m]
        # Detect higher highs/lows vs lower
        recent_highs = highs[-20:] if len(highs) >= 20 else highs
        recent_lows = lows[-20:] if len(lows) >= 20 else lows
        if len(recent_highs) >= 10:
            first_half_h = max(recent_highs[:len(recent_highs)//2]); second_half_h = max(recent_highs[len(recent_highs)//2:])
            struct.higher_highs = second_half_h > first_half_h
            struct.lower_highs = second_half_h < first_half_h * 0.98
        if len(recent_lows) >= 10:
            first_half_l = min(recent_lows[:len(recent_lows)//2]); second_half_l = min(recent_lows[len(recent_lows)//2:])
            struct.higher_lows = second_half_l > first_half_l
            struct.lower_lows = second_half_l < first_half_l * 0.98
        # Gap behavior
        if prev_close > 0:
            first_price = bars_1m[0].close; gap_pct = (first_price - prev_close) / prev_close * 100
            if abs(gap_pct) > 2:
                current_price = closes[-1]
                if current_price > first_price: struct.gap_behavior = GapBehavior.GAP_AND_GO
                elif current_price > prev_close: struct.gap_behavior = GapBehavior.RECLAIM_ATTEMPT
                else: struct.gap_behavior = GapBehavior.GAP_AND_FADE
        # Quality classification
        if struct.higher_highs and struct.higher_lows: struct.quality = StructureQuality.CLEAN_TREND
        elif struct.lower_highs or struct.lower_lows: struct.quality = StructureQuality.WEAKENING
        return struct

    def _analyze_extension(self, stock: ProfessionalStockData, bars: List[OHLCVBar]):
        if not bars: return
        highs = [b.high for b in bars]; lows = [b.low for b in bars]; closes = [b.close for b in bars]
        # VWAP calculation (simplified)
        vwap = sum(((b.high + b.low + b.close) / 3) * b.volume for b in bars[-20:]) / sum(b.volume for b in bars[-20:]) if bars else stock.price
        intraday_high = max(highs); current = closes[-1]
        stock.distance_from_vwap = ((current - vwap) / vwap * 100) if vwap > 0 else 0
        stock.distance_from_high = ((intraday_high - current) / intraday_high * 100) if intraday_high > 0 else 0
        # Extension from impulse origin (first 20% of session)
        impulse_origin = closes[len(closes)//5] if len(closes) >= 5 else closes[0]
        stock.extension_pct = ((current - impulse_origin) / impulse_origin * 100) if impulse_origin > 0 else 0
        # Classification
        if stock.extension_pct < 30: stock.extension_state = ExtensionState.EARLY
        elif stock.extension_pct < 60: stock.extension_state = ExtensionState.MID
        else: stock.extension_state = ExtensionState.EXTENDED

    def _analyze_liquidity(self, bars: List[OHLCVBar]) -> LiquidityMetrics:
        liq = LiquidityMetrics()
        if not bars or len(bars) < 5: return liq
        # Calculate spreads
        spreads = []
        candle_ranges = []
        for i in range(1, min(20, len(bars))):
            spread = abs(bars[i].close - bars[i-1].close) / bars[i-1].close * 100 if bars[i-1].close > 0 else 0
            spreads.append(spread)
            candle_range = (bars[i].high - bars[i].low) / bars[i].low * 100 if bars[i].low > 0 else 0
            candle_ranges.append(candle_range)
        liq.spread_pct = np.mean(spreads) if spreads else 0
        liq.avg_candle_range = np.mean(candle_ranges) if candle_ranges else 0
        liq.spread_vs_candle_range = (liq.spread_pct / liq.avg_candle_range * 100) if liq.avg_candle_range > 0 else 0
        # Erratic behavior (high volatility in short timeframe)
        std_range = np.std(candle_ranges) if len(candle_ranges) > 1 else 0
        liq.erratic_score = min(100, std_range * 10)
        # Quality classification
        if liq.spread_pct < 0.1 and liq.erratic_score < 30: liq.quality = LiquidityQuality.HIGH
        elif liq.spread_pct < 0.3 and liq.erratic_score < 50: liq.quality = LiquidityQuality.ACCEPTABLE
        else: liq.quality = LiquidityQuality.POOR
        return liq

    def _assess_risk(self, bars: List[OHLCVBar], stock_type: StockType) -> RiskFlags:
        risk = RiskFlags()
        if not bars or len(bars) < 10: return risk
        # Halt risk: extreme moves (>20% in single bar for penny stocks)
        max_moves = [(b.high - b.low) / b.low * 100 for b in bars[-10:] if b.low > 0]
        if max_moves and max(max_moves) > (30 if stock_type == StockType.PENNY else 15):
            risk.abnormal_candle_expansion = True
        # Erratic behavior (many large range candles)
        large_candles = sum(1 for m in max_moves if m > 5)
        if large_candles >= 3: risk.erratic_behavior = True
        # Risk level
        risk_factors = sum([risk.abnormal_candle_expansion, risk.erratic_behavior, stock_type == StockType.PENNY])
        if risk_factors >= 2: risk.risk_level = "high"
        elif risk_factors >= 1: risk.risk_level = "moderate"
        risk.halt_risk = risk.risk_level == "high"
        return risk

    def _analyze_timeframes(self, bars_1m: List[OHLCVBar], bars_5m: List[OHLCVBar], bars_15m: List[OHLCVBar]) -> MultiTimeframeData:
        mtf = MultiTimeframeData()
        # Trend detection: compare current to earlier in session
        def calc_trend(bars):
            if not bars or len(bars) < 10: return "neutral"
            early = np.mean([b.close for b in bars[:len(bars)//3]])
            late = np.mean([b.close for b in bars[-len(bars)//3:]])
            change = ((late - early) / early * 100) if early > 0 else 0
            if change > 1: return "bullish"
            elif change < -1: return "bearish"
            return "neutral"
        mtf.trend_1m = calc_trend(bars_1m)
        mtf.trend_5m = calc_trend(bars_5m)
        mtf.trend_15m = calc_trend(bars_15m)
        # Alignment
        trends = [mtf.trend_1m, mtf.trend_5m, mtf.trend_15m]
        bullish_count = sum(1 for t in trends if t == "bullish")
        bearish_count = sum(1 for t in trends if t == "bearish")
        if bullish_count >= 2: mtf.alignment = TimeframeAlignment.BULLISH
        elif bearish_count >= 2: mtf.alignment = TimeframeAlignment.CONFLICTING
        return mtf

    def _assess_rejection(self, stock: ProfessionalStockData, bars: List[OHLCVBar]):
        if not bars: return
        highs = [b.high for b in bars]; lows = [b.low for b in bars]; closes = [b.close for b in bars]
        # Failed highs count
        recent_highs = highs[-20:] if len(highs) >= 20 else highs
        max_price = max(recent_highs); current = closes[-1]
        stock.proximity_to_resistance = ((max_price - current) / max_price * 100) if max_price > 0 else 0
        # Count touches of highs that failed
        touches = 0
        for i in range(-10, 0):
            if highs[i] > max_price * 0.995 and closes[i] < highs[i] * 0.99:
                touches += 1
        stock.failed_highs_count = touches
        # Upper wick pressure
        upper_wicks = []
        for i in range(-5, 0):
            body = abs(closes[i] - (closes[i-1] if i > -len(closes) else closes[0]))
            wick = highs[i] - max(closes[i], closes[i-1] if i > -len(closes) else closes[i])
            if body > 0: upper_wicks.append(wick / body)
        stock.upper_wick_pressure = any(w > 2 for w in upper_wicks)
        # Rejection risk score (0-100)
        score = 0
        if stock.proximity_to_resistance < 2: score += 30
        if touches >= 2: score += 25
        if stock.upper_wick_pressure: score += 20
        if stock.distance_from_high < 5: score += 25
        stock.rejection_risk_score = min(100, score)

    def _calc_relative_strength(self, stock: ProfessionalStockData, change_pct: float):
        spy_change = 0; qqq_change = 0
        if self._spy_data is not None and not self._spy_data.empty:
            spy_first = self._spy_data["Close"].iloc[0]; spy_last = self._spy_data["Close"].iloc[-1]
            spy_change = ((spy_last - spy_first) / spy_first * 100) if spy_first > 0 else 0
        if self._qqq_data is not None and not self._qqq_data.empty:
            qqq_first = self._qqq_data["Close"].iloc[0]; qqq_last = self._qqq_data["Close"].iloc[-1]
            qqq_change = ((qqq_last - qqq_first) / qqq_first * 100) if qqq_first > 0 else 0
        market_avg = (spy_change + qqq_change) / 2
        stock.outperformance_pct = change_pct - market_avg
        if stock.outperformance_pct > 3: stock.relative_strength = MarketRelativeStrength.OUTPERFORMING
        elif stock.outperformance_pct < -3: stock.relative_strength = MarketRelativeStrength.LAGGING
        else: stock.relative_strength = MarketRelativeStrength.INLINE
        stock.spy_correlation = spy_change

    def _identify_theme(self, ticker: str, sector: str) -> str:
        themes = {
            "AI": ["AI", "SOUN", "IONQ", "QBTS", "NVDA", "PLTR"],
            "Biotech": ["BIOTECH", "PHARMA", "THERAPEUTICS", "CLINICAL"],
            "EV": ["TSLA", "RIVN", "NIO", "XPEV", "LI", "LCID"],
            "Space": ["ASTS", "RKLB", "SPCE", "ACHR", "LILM", "JOBY"],
            "Fintech": ["SOFI", "HOOD", "SQ", "PYPL", "UPST", "AFRM"],
            "Crypto": ["COIN", "MSTR", "RIOT", "MARA"],
            "Gaming": ["GME", "AMC", "RBLX", "DKNG"],
            "China": ["BABA", "JD", "PDD", "BIDU", "NIO", "XPEV", "LI"],
            "Meme": ["GME", "AMC", "BB", "NOK"],
        }
        for theme, tickers in themes.items():
            if ticker.upper() in [t.upper() for t in tickers]: return theme
        return sector if sector else "unknown"

    def _validate_in_play(self, stock: ProfessionalStockData):
        active_score = 0
        if stock.volume_trend == VolumeTrend.INCREASING: active_score += 3
        if stock.sustained_participation: active_score += 2
        if stock.premarket and stock.premarket.status == PremarketStatus.STRONG: active_score += 2
        if stock.structure and stock.structure.higher_highs: active_score += 2
        if stock.extension_state != ExtensionState.EXTENDED: active_score += 1
        fading_score = 0
        if stock.volume_trend == VolumeTrend.DECREASING: fading_score += 2
        if stock.structure and stock.structure.lower_highs: fading_score += 2
        if stock.distance_from_high > 10: fading_score += 2
        if fading_score >= 3: stock.in_play_status = InPlayStatus.FADING
        elif active_score >= 5: stock.in_play_status = InPlayStatus.ACTIVE
        else: stock.in_play_status = InPlayStatus.DEAD

    def _apply_exclusion(self, stock: ProfessionalStockData):
        exclusions = []
        if stock.liquidity and stock.liquidity.quality == LiquidityQuality.POOR: exclusions.append("Poor liquidity")
        if stock.liquidity and stock.liquidity.spread_pct > 1.0: exclusions.append("Excessive spread")
        if stock.catalyst and stock.catalyst.freshness == CatalystFreshness.STALE: exclusions.append("Stale catalyst")
        if stock.extension_state == ExtensionState.EXTENDED and stock.rejection_risk_score > 70: exclusions.append("Extremely extended")
        if stock.structure and stock.structure.quality == StructureQuality.BROKEN: exclusions.append("Structurally broken")
        if stock.risk and stock.risk.risk_level == "high": exclusions.append("High risk/volatile")
        if stock.volume_as_pct_of_float < 1 and stock.stock_type != StockType.LARGE: exclusions.append("Low participation")
        if exclusions:
            stock.excluded = True
            stock.exclusion_reason = "; ".join(exclusions)

    def _classify_setup(self, stock: ProfessionalStockData):
        if stock.excluded: stock.setup_readiness = SetupReadiness.AVOID; return
        # Ready for dip: early extension, clean structure, active
        if (stock.extension_state in [ExtensionState.EARLY, ExtensionState.MID] and
            stock.structure and stock.structure.quality in [StructureQuality.CLEAN_TREND, StructureQuality.CHOPPY] and
            stock.in_play_status == InPlayStatus.ACTIVE and stock.rejection_risk_score < 50):
            stock.setup_readiness = SetupReadiness.READY_FOR_DIP
            stock.analyze_for_dip = True
        # Breakout candidate: compression near highs, increasing volume
        elif (stock.structure and stock.structure.compression_near_highs or
              (stock.volume_trend == VolumeTrend.INCREASING and stock.proximity_to_resistance < 3)):
            stock.setup_readiness = SetupReadiness.BREAKOUT_CANDIDATE
            stock.breakout_candidate = True
        # Extended: already moved significantly
        elif stock.extension_state == ExtensionState.EXTENDED:
            stock.setup_readiness = SetupReadiness.EXTENDED
            stock.monitor_bearish_shift = True
        else:
            stock.setup_readiness = SetupReadiness.AVOID

    def _calculate_final_score(self, stock: ProfessionalStockData):
        if stock.excluded: stock.final_score = 0; return
        score = 50  # Base score
        # Catalyst (+20 max)
        if stock.has_catalyst:
            if stock.catalyst.tier == CatalystTier.TIER_1: score += 15
            elif stock.catalyst.tier == CatalystTier.TIER_2: score += 10
            else: score += 5
            if stock.catalyst.freshness == CatalystFreshness.FRESH: score += 5
            if stock.catalyst.sentiment == "positive": score += 5
        # Volume/Participation (+20 max)
        if stock.volume_as_pct_of_float > 20: score += 15
        elif stock.volume_as_pct_of_float > 10: score += 10
        elif stock.volume_as_pct_of_float > 5: score += 5
        if stock.sustained_participation: score += 5
        # Structure (+15 max)
        if stock.structure:
            if stock.structure.quality == StructureQuality.CLEAN_TREND: score += 15
            elif stock.structure.quality == StructureQuality.CHOPPY: score += 5
        # Liquidity (+10 max)
        if stock.liquidity:
            if stock.liquidity.quality == LiquidityQuality.HIGH: score += 10
            elif stock.liquidity.quality == LiquidityQuality.ACCEPTABLE: score += 5
        # Extension (+10 max for early, -10 for extended)
        if stock.extension_state == ExtensionState.EARLY: score += 10
        elif stock.extension_state == ExtensionState.MID: score += 5
        elif stock.extension_state == ExtensionState.EXTENDED: score -= 10
        # Timeframe alignment (+10 max)
        if stock.timeframe_data:
            if stock.timeframe_data.alignment == TimeframeAlignment.BULLISH: score += 10
        # Relative strength (+10 max)
        if stock.relative_strength == MarketRelativeStrength.OUTPERFORMING: score += 10
        # Risk penalties (-20 max)
        if stock.risk:
            if stock.risk.risk_level == "high": score -= 15
            elif stock.risk.risk_level == "moderate": score -= 5
        # Rejection risk penalty
        if stock.rejection_risk_score > 50: score -= 10
        if stock.rejection_risk_score > 75: score -= 10
        stock.final_score = max(0, min(100, round(score, 1)))

    def _build_reasons(self, stock: ProfessionalStockData):
        pos, neg, risks = [], [], []
        # Positive reasons
        if stock.has_catalyst:
            if stock.catalyst.tier == CatalystTier.TIER_1: pos.append(f"Tier-1 catalyst: {stock.catalyst.headline[:40]}...")
            else: pos.append("Has news catalyst")
        if stock.sustained_participation: pos.append(f"Sustained volume ({stock.volume_as_pct_of_float:.1f}% of float)")
        if stock.structure and stock.structure.quality == StructureQuality.CLEAN_TREND: pos.append("Clean uptrend structure")
        if stock.premarket and stock.premarket.status == PremarketStatus.STRONG: pos.append("Strong premarket interest")
        if stock.extension_state == ExtensionState.EARLY: pos.append("Early in move (room to run)")
        if stock.liquidity and stock.liquidity.quality == LiquidityQuality.HIGH: pos.append("High liquidity / tight spreads")
        if stock.timeframe_data and stock.timeframe_data.alignment == TimeframeAlignment.BULLISH: pos.append("Multi-timeframe alignment bullish")
        if stock.relative_strength == MarketRelativeStrength.OUTPERFORMING: pos.append(f"Outperforming market (+{stock.outperformance_pct:.1f}%)")
        # Negative reasons / risks
        if stock.extension_state == ExtensionState.EXTENDED: neg.append("Extended move - exhaustion risk")
        if stock.rejection_risk_score > 50: risks.append(f"High rejection risk ({stock.rejection_risk_score:.0f}/100)")
        if stock.structure and stock.structure.lower_highs: neg.append("Lower highs forming - weakening")
        if stock.volume_trend == VolumeTrend.DECREASING: neg.append("Volume declining - interest fading")
        if stock.risk and stock.risk.risk_level == "high": risks.append("High volatility / halt risk")
        if stock.liquidity and stock.liquidity.quality == LiquidityQuality.POOR: risks.append("Poor liquidity - wide spreads")
        if stock.failed_highs_count >= 2: risks.append(f"Multiple failed highs ({stock.failed_highs_count})")
        stock.positive_reasons = pos[:5]; stock.negative_reasons = neg[:3]; stock.key_risks = risks[:3]

    def _assign_tags(self, stock: ProfessionalStockData):
        stock.tags = []
        if stock.analyze_for_dip: stock.tags.append("analyze_for_dip")
        if stock.breakout_candidate: stock.tags.append("breakout_candidate")
        if stock.monitor_bearish_shift: stock.tags.append("monitor_bearish_shift")
        if stock.setup_readiness == SetupReadiness.AVOID: stock.tags.append("ignore")
        else: stock.tags.append("analyze")
        if stock.final_score >= 80: stock.tags.append("high_quality")
        elif stock.final_score >= 60: stock.tags.append("medium_quality")


def to_scanned_stock(stock: ProfessionalStockData):
    """Convert ProfessionalStockData to ScannedStock model."""
    from src.models.schemas import ScannedStock
    return ScannedStock(
        ticker=stock.ticker, price=stock.price, volume=stock.volume,
        change_percent=stock.change_percent, market_cap=stock.market_cap,
        float_shares=stock.float_shares, scan_type="professional",
        premarket_gap_percent=stock.premarket.gap_percent if stock.premarket else None,
        premarket_volume_vs_avg=stock.premarket.volume_vs_avg if stock.premarket else None,
        premarket_status=stock.premarket.status.value if stock.premarket else None,
        volume_as_pct_of_float=stock.volume_as_pct_of_float,
        volume_trend=stock.volume_trend.value, sustained_participation=stock.sustained_participation,
        has_catalyst=stock.has_catalyst, catalyst_tier=stock.catalyst.tier.value if stock.catalyst else None,
        structure_quality=stock.structure.quality.value if stock.structure else None,
        higher_highs=stock.structure.higher_highs if stock.structure else False,
        lower_highs=stock.structure.lower_highs if stock.structure else False,
        extension_state=stock.extension_state.value, rejection_risk_score=stock.rejection_risk_score,
        final_score=stock.final_score, scan_rank=stock.scan_rank,
        in_play_status=stock.in_play_status.value, setup_readiness=stock.setup_readiness.value,
        analyze_for_dip=stock.analyze_for_dip, tags=stock.tags, excluded=stock.excluded)

