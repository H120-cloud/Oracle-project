"""Lookback Window Feature Extractor

Extracts features from lookback windows before a catalyst event.
Reuses existing pre-news anomaly detector logic where possible.
"""
from __future__ import annotations

import logging
import statistics
from typing import Dict, List, Optional, Any

from src.core.agentic.historical_models import HistoricalCatalystEvent

logger = logging.getLogger(__name__)


class LookbackFeatureExtractor:
    """Extract lookback window features for historical catalyst events."""

    @classmethod
    def extract(cls, event: HistoricalCatalystEvent, price_history: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        """Extract feature snapshot from optional price/volume history.

        Parameters
        ----------
        event: The catalyst event.
        price_history: Optional list of bar dicts [{"timestamp": "...", "open": ..., "high": ..., "low": ..., "close": ..., "volume": ...}]
        """
        snapshot: Dict[str, Any] = {}

        # Volume features from event metadata if available
        snapshot["rvol_15m"] = event.rvol_before_news
        snapshot["rvol_30m"] = event.volume_before_30m and event.volume_before_30m / max(event.volume_before_2h or 1, 1) or None
        snapshot["rvol_1h"] = event.volume_before_1h and event.volume_before_1h / max(event.volume_before_2h or 1, 1) or None
        snapshot["rvol_2h"] = 1.0 if event.volume_before_2h else None
        snapshot["volume_acceleration"] = event.volume_acceleration_before_news

        # Price change features
        base_price = event.price_at_news or event.price_before_30m or event.price_before_1h
        if base_price:
            if event.price_before_30m:
                snapshot["price_change_30m_pct"] = round((base_price - event.price_before_30m) / event.price_before_30m * 100, 2)
            if event.price_before_1h:
                snapshot["price_change_1h_pct"] = round((base_price - event.price_before_1h) / event.price_before_1h * 100, 2)
            if event.price_before_2h:
                snapshot["price_change_2h_pct"] = round((base_price - event.price_before_2h) / event.price_before_2h * 100, 2)

        # Float / market cap buckets
        snapshot["float_bucket"] = cls._float_bucket(event.float_shares)
        snapshot["market_cap_bucket"] = cls._market_cap_bucket(event.market_cap)
        snapshot["liquidity_quality"] = cls._liquidity_quality(event.float_shares, event.market_cap)

        # Structural
        snapshot["is_premarket"] = event.is_premarket
        snapshot["time_of_day_bucket"] = event.time_of_day_bucket

        # If price history provided, compute richer features
        if price_history:
            snapshot.update(cls._extract_from_bars(price_history))

        # Spread quality from pre-news spread if available
        if event.spread_before_news is not None:
            snapshot["spread_quality"] = cls._spread_quality(event.spread_before_news, event.price_at_news)

        # VWAP position
        if event.vwap_position_before_news is not None:
            snapshot["vwap_position_pct"] = event.vwap_position_before_news
            snapshot["vwap_hold"] = event.vwap_position_before_news > -1.0

        logger.debug("Extracted %s features for %s", len(snapshot), event.ticker)
        return snapshot

    @staticmethod
    def _float_bucket(float_shares: Optional[float]) -> Optional[str]:
        if float_shares is None:
            return None
        if float_shares < 5_000_000:
            return "ultra_low"
        if float_shares < 20_000_000:
            return "low"
        return "normal"

    @staticmethod
    def _market_cap_bucket(market_cap: Optional[float]) -> Optional[str]:
        if market_cap is None:
            return None
        if market_cap < 300_000_000:
            return "micro"
        if market_cap < 2_000_000_000:
            return "small"
        if market_cap < 10_000_000_000:
            return "mid"
        return "large"

    @staticmethod
    def _liquidity_quality(float_shares: Optional[float], market_cap: Optional[float]) -> Optional[str]:
        if float_shares is None or market_cap is None:
            return None
        if float_shares < 5_000_000 and market_cap < 500_000_000:
            return "low"
        if float_shares < 20_000_000 and market_cap < 2_000_000_000:
            return "moderate"
        return "high"

    @staticmethod
    def _spread_quality(spread: float, price: float) -> str:
        if price <= 0:
            return "unknown"
        pct = spread / price * 100
        if pct < 0.5:
            return "tight"
        if pct < 2.0:
            return "moderate"
        return "wide"

    @classmethod
    def _extract_from_bars(cls, bars: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Compute features from a list of OHLCV bars."""
        snapshot: Dict[str, Any] = {}
        if len(bars) < 2:
            return snapshot

        closes = [b["close"] for b in bars]
        volumes = [b.get("volume", 0) for b in bars]
        highs = [b["high"] for b in bars]
        lows = [b["low"] for b in bars]

        # Price compression (range vs previous range)
        if len(bars) >= 4:
            ranges = [b["high"] - b["low"] for b in bars]
            snapshot["price_range_compression_15m"] = round(ranges[-1] / max(ranges[-2], 0.0001), 2)
            snapshot["price_range_compression_30m"] = round(sum(ranges[-2:]) / max(sum(ranges[-4:-2]), 0.0001), 2)
            snapshot["price_range_compression_1h"] = round(sum(ranges[-4:]) / max(sum(ranges[-8:-4]), 0.0001), 2)

        # Volume z-score
        if len(volumes) >= 2:
            mean_vol = statistics.mean(volumes[:-1])
            stdev_vol = statistics.stdev(volumes[:-1]) if len(volumes) > 2 else 0
            if stdev_vol > 0:
                snapshot["volume_z_score"] = round((volumes[-1] - mean_vol) / stdev_vol, 2)
            else:
                snapshot["volume_z_score"] = 0.0

        # Abnormal volume score (0-100)
        if len(volumes) >= 2:
            avg_vol = statistics.mean(volumes[:-1])
            if avg_vol > 0:
                ratio = volumes[-1] / avg_vol
                snapshot["abnormal_volume_score"] = min(100.0, round(ratio * 10, 1))

        # VWAP hold/reclaim (simplified)
        if len(closes) >= 3:
            snapshot["higher_low_formed"] = lows[-1] > lows[-2]
            snapshot["upper_wick_pct"] = round((highs[-1] - closes[-1]) / max(closes[-1], 0.0001) * 100, 2)
            snapshot["lower_wick_pct"] = round((closes[-1] - lows[-1]) / max(closes[-1], 0.0001) * 100, 2)

        # Pre-news anomaly score (0-100 composite of volume signals)
        if "volume_z_score" in snapshot and "abnormal_volume_score" in snapshot:
            vz = snapshot.get("volume_z_score", 0) or 0
            avs = snapshot.get("abnormal_volume_score", 0) or 0
            snapshot["pre_news_anomaly_score"] = round(min(100, max(0, avs * 0.6 + min(100, vz * 5) * 0.4)), 1)

        # Trap risk score from bars (0-100)
        snapshot["trap_risk_score"] = cls._compute_trap_risk(bars)

        # Quiet accumulation flag: tight range + low wicks + low volume relative to spike
        snapshot["quiet_accumulation"] = cls._is_quiet_accumulation(bars, snapshot)

        # Breakout building flag: price near highs + tightening range + volume building
        snapshot["breakout_building"] = cls._is_breakout_building(bars, snapshot)

        return snapshot

    @classmethod
    def _compute_trap_risk(cls, bars: List[Dict[str, Any]]) -> float:
        """Compute a 0-100 trap risk score from recent bar patterns."""
        if len(bars) < 5:
            return 0.0
        highs = [b["high"] for b in bars]
        lows = [b["low"] for b in bars]
        closes = [b["close"] for b in bars]
        volumes = [b.get("volume", 0) for b in bars]
        score = 0.0

        # Parabolic exhaustion: multiple large-range candles
        big_candles = 0
        for b in bars[-10:]:
            rng = b["high"] - b["low"]
            if rng > 0 and rng / b["low"] > 0.03:
                big_candles += 1
        if big_candles >= 4:
            score += 25

        # Upper wick pressure
        wick_pressure = 0
        for b in bars[-5:]:
            body = abs(b["close"] - b["open"])
            upper_wick = b["high"] - max(b["close"], b["open"])
            if body > 0 and upper_wick > body * 1.5:
                wick_pressure += 1
        if wick_pressure >= 3:
            score += 20
        elif wick_pressure >= 2:
            score += 10

        # Distribution: rising volume on falling price
        if len(bars) >= 10:
            recent_vol = sum(volumes[-5:]) / 5
            prior_vol = sum(volumes[-10:-5]) / 5 if len(volumes) >= 10 else recent_vol
            recent_price = sum(closes[-5:]) / 5
            prior_price = sum(closes[-10:-5]) / 5 if len(closes) >= 10 else recent_price
            if recent_vol > prior_vol * 1.2 and recent_price < prior_price:
                score += 15

        # Extreme extension from low
        hod = max(highs)
        lod = min(lows)
        if lod > 0:
            total_move = (hod - lod) / lod * 100
            if total_move > 100:
                score += 15
            elif total_move > 50:
                score += 8

        return round(min(100, score), 1)

    @classmethod
    def _is_quiet_accumulation(cls, bars: List[Dict[str, Any]], snapshot: Dict[str, Any]) -> bool:
        """Flag tight range, low wicks, controlled price near VWAP."""
        if len(bars) < 5:
            return False
        recent = bars[-5:]
        ranges = [b["high"] - b["low"] for b in recent]
        avg_range = sum(ranges) / len(ranges) if ranges else 1
        # Need a reference price for range comparison
        ref = recent[-1]["close"] if recent else 1
        if ref <= 0:
            ref = 1
        range_pct = avg_range / ref * 100
        upper_wick_pct = snapshot.get("upper_wick_pct", 0) or 0
        # Quiet = tight range (<1.5%), low upper wicks, higher low formed
        tight = range_pct < 1.5
        low_wick = upper_wick_pct < 20
        higher_low = snapshot.get("higher_low_formed", False)
        return tight and low_wick and higher_low

    @classmethod
    def _is_breakout_building(cls, bars: List[Dict[str, Any]], snapshot: Dict[str, Any]) -> bool:
        """Flag price near highs with tightening range and volume building."""
        if len(bars) < 8:
            return False
        highs = [b["high"] for b in bars]
        lows = [b["low"] for b in bars]
        closes = [b["close"] for b in bars]
        volumes = [b.get("volume", 0) for b in bars]
        current = closes[-1]
        day_high = max(highs)
        if day_high <= 0:
            return False
        dist_from_high = (day_high - current) / day_high * 100

        # Tightening range in last 5 vs prior 5
        if len(bars) >= 10:
            prior_ranges = [b["high"] - b["low"] for b in bars[-10:-5]]
            recent_ranges = [b["high"] - b["low"] for b in bars[-5:]]
            avg_prior = sum(prior_ranges) / len(prior_ranges) if prior_ranges else 1
            avg_recent = sum(recent_ranges) / len(recent_ranges) if recent_ranges else 1
            tightening = avg_recent < avg_prior * 0.8
        else:
            tightening = False

        # Volume building
        if len(volumes) >= 6:
            vol_building = sum(volumes[-3:]) / max(sum(volumes[-6:-3]), 0.0001) > 1.2
        else:
            vol_building = False

        # Near highs + tightening + volume building
        return dist_from_high < 2 and tightening and vol_building
