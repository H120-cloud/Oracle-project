"""
Market Regime Service — V19.1

Fetches real-time market regime data for ML feature population:
- SPY 5-day trend
- VIX fear gauge
- Sector RSI (relative strength)
- Market breadth proxy

Uses AlphaVantage as primary, falls back to yfinance.
Caches results to avoid redundant API calls.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Simple in-memory cache with TTL
_cache: dict = {}
_CACHE_TTL_SECONDS = 300  # 5 min


def _get_cached(key: str) -> Optional[any]:
    entry = _cache.get(key)
    if entry and (time.time() - entry["ts"]) < _CACHE_TTL_SECONDS:
        return entry["value"]
    return None


def _set_cached(key: str, value):
    _cache[key] = {"ts": time.time(), "value": value}


def _spy_trend_yfinance() -> float:
    """Fetch SPY 5-day return via yfinance fallback."""
    try:
        import yfinance as yf
        spy = yf.Ticker("SPY")
        hist = spy.history(period="7d")
        if len(hist) < 6:
            return 0.0
        return (hist["Close"].iloc[-1] / hist["Close"].iloc[-6] - 1) * 100
    except Exception as exc:
        logger.warning("yfinance SPY trend failed: %s", exc)
        return 0.0


def _vix_yfinance() -> float:
    """Fetch VIX via yfinance fallback."""
    try:
        import yfinance as yf
        vix = yf.Ticker("^VIX")
        hist = vix.history(period="5d")
        if hist.empty:
            return 20.0
        return hist["Close"].iloc[-1]
    except Exception as exc:
        logger.warning("yfinance VIX failed: %s", exc)
        return 20.0


def _sector_rsi_yfinance(sector_etf: str = "XLK") -> float:
    """Compute sector RSI via yfinance fallback."""
    try:
        import yfinance as yf
        tick = yf.Ticker(sector_etf)
        hist = tick.history(period="30d")
        if len(hist) < 15:
            return 50.0
        delta = hist["Close"].diff()
        gain = delta.where(delta > 0, 0).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        return rsi.iloc[-1]
    except Exception as exc:
        logger.warning("yfinance sector RSI failed: %s", exc)
        return 50.0


def get_regime_snapshot(use_alphavantage: bool = True) -> dict:
    """
    Fetch all market regime features.
    Returns dict with spy_trend_5d, vix_level, sector_rsi, market_breadth.
    """
    cached = _get_cached("regime_snapshot")
    if cached:
        return cached

    result = {
        "spy_trend_5d": 0.0,
        "vix_level": 20.0,
        "sector_rsi": 50.0,
        "market_breadth": 50.0,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    # Try AlphaVantage first
    if use_alphavantage:
        try:
            from src.services.alphavantage_provider import get_alphavantage_provider
            av = get_alphavantage_provider()
            result = av.get_regime_snapshot()
            _set_cached("regime_snapshot", result)
            logger.debug("Market regime fetched from AlphaVantage")
            return result
        except Exception as exc:
            logger.warning("AlphaVantage regime failed, falling back to yfinance: %s", exc)

    # Fallback to yfinance
    result["spy_trend_5d"] = _spy_trend_yfinance()
    result["vix_level"] = _vix_yfinance()
    result["sector_rsi"] = _sector_rsi_yfinance()
    result["market_breadth"] = result["sector_rsi"]  # proxy

    _set_cached("regime_snapshot", result)
    logger.debug("Market regime fetched from yfinance fallback")
    return result


def apply_regime_to_candidate(candidate, regime: dict | None = None) -> None:
    """
    Attach market regime features to an AgenticCandidate.
    Uses Pydantic model fields (safe for model_dump).
    """
    if regime is None:
        regime = get_regime_snapshot()

    candidate.spy_trend_5d = regime.get("spy_trend_5d", 0.0)
    candidate.vix_level = regime.get("vix_level", 20.0)
    candidate.sector_rsi = regime.get("sector_rsi", 50.0)
    candidate.market_breadth = regime.get("market_breadth", 50.0)

    logger.debug(
        "Applied regime to %s: spy=%.2f, vix=%.1f, sector_rsi=%.1f",
        candidate.ticker,
        candidate.spy_trend_5d,
        candidate.vix_level,
        candidate.sector_rsi,
    )
