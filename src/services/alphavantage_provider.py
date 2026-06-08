"""
AlphaVantage Market Data Provider

Fetches:
- Intraday OHLCV bars (1min, 5min, 15min, 30min, 60min)
- Daily closes for trend analysis
- Technical indicators (RSI, SMA, MACD)
- Fundamental data (overview, earnings)
- Market regime data (SPY, VIX, sector ETFs)

Free tier: 25 API calls/day, 5 calls/minute
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
import numpy as np
import pandas as pd

from src.config import get_settings
from src.models.market_data import OHLCVBar
from src.services.ticker_normalization import normalize_ticker_for_provider

logger = logging.getLogger(__name__)

_BASE_URL = "https://www.alphavantage.co/query"


class AlphaVantageClient:
    """Low-level AlphaVantage API client with rate-limiting."""

    def __init__(self, api_key: str | None = None):
        settings = get_settings()
        self.api_key = api_key or settings.alphavantage_api_key
        self._last_call = 0.0
        self._min_interval = 12.1  # 5 calls/min = 12s spacing (free tier)

    def _call(self, params: dict) -> dict:
        """Make a rate-limited API call."""
        if not self.api_key:
            raise RuntimeError("AlphaVantage API key not configured")

        elapsed = time.time() - self._last_call
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)

        params["apikey"] = self.api_key
        try:
            resp = httpx.get(_BASE_URL, params=params, timeout=30.0)
            resp.raise_for_status()
            self._last_call = time.time()
            data = resp.json()
            if "Note" in data:
                logger.warning("AlphaVantage rate limit: %s", data["Note"])
            if "Information" in data:
                logger.info("AlphaVantage: %s", data["Information"])
            return data
        except Exception as exc:
            logger.error("AlphaVantage API error: %s", exc)
            raise

    # ── Time Series ───────────────────────────────────────────────────

    def intraday(self, symbol: str, interval: str = "5min", month: str | None = None) -> pd.DataFrame:
        """Fetch intraday time series."""
        provider_symbol = normalize_ticker_for_provider(symbol, "alpha_vantage")
        params = {
            "function": "TIME_SERIES_INTRADAY",
            "symbol": provider_symbol,
            "interval": interval,
            "outputsize": "full",
            "datatype": "json",
        }
        if month:
            params["month"] = month
        data = self._call(params)
        key = f"Time Series ({interval})"
        if key not in data:
            return pd.DataFrame()
        df = pd.DataFrame.from_dict(data[key], orient="index")
        df = df.rename(columns=lambda c: c.split(". ")[1])
        df = df.astype(float)
        df.index = pd.to_datetime(df.index)
        df = df.sort_index()
        return df

    def daily(self, symbol: str, outputsize: str = "full") -> pd.DataFrame:
        """Fetch daily adjusted close time series."""
        provider_symbol = normalize_ticker_for_provider(symbol, "alpha_vantage")
        params = {
            "function": "TIME_SERIES_DAILY_ADJUSTED",
            "symbol": provider_symbol,
            "outputsize": outputsize,
            "datatype": "json",
        }
        data = self._call(params)
        key = "Time Series (Daily)"
        if key not in data:
            return pd.DataFrame()
        df = pd.DataFrame.from_dict(data[key], orient="index")
        df = df.rename(columns=lambda c: c.split(". ")[1])
        df = df.astype(float)
        df.index = pd.to_datetime(df.index)
        df = df.sort_index()
        return df

    # ── Technical Indicators ──────────────────────────────────────────

    def rsi(self, symbol: str, interval: str = "daily", time_period: int = 14) -> pd.DataFrame:
        """Fetch RSI technical indicator."""
        provider_symbol = normalize_ticker_for_provider(symbol, "alpha_vantage")
        params = {
            "function": "RSI",
            "symbol": provider_symbol,
            "interval": interval,
            "time_period": str(time_period),
            "series_type": "close",
        }
        data = self._call(params)
        key = "Technical Analysis: RSI"
        if key not in data:
            return pd.DataFrame()
        df = pd.DataFrame.from_dict(data[key], orient="index")
        df.index = pd.to_datetime(df.index)
        df = df.sort_index()
        return df.astype(float)

    def sma(self, symbol: str, interval: str = "daily", time_period: int = 20) -> pd.DataFrame:
        """Fetch SMA technical indicator."""
        provider_symbol = normalize_ticker_for_provider(symbol, "alpha_vantage")
        params = {
            "function": "SMA",
            "symbol": provider_symbol,
            "interval": interval,
            "time_period": str(time_period),
            "series_type": "close",
        }
        data = self._call(params)
        key = "Technical Analysis: SMA"
        if key not in data:
            return pd.DataFrame()
        df = pd.DataFrame.from_dict(data[key], orient="index")
        df.index = pd.to_datetime(df.index)
        df = df.sort_index()
        return df.astype(float)

    def macd(self, symbol: str, interval: str = "daily") -> pd.DataFrame:
        """Fetch MACD technical indicator."""
        provider_symbol = normalize_ticker_for_provider(symbol, "alpha_vantage")
        params = {
            "function": "MACD",
            "symbol": provider_symbol,
            "interval": interval,
            "series_type": "close",
        }
        data = self._call(params)
        key = "Technical Analysis: MACD"
        if key not in data:
            return pd.DataFrame()
        df = pd.DataFrame.from_dict(data[key], orient="index")
        df.index = pd.to_datetime(df.index)
        df = df.sort_index()
        return df.astype(float)

    # ── Fundamental Data ────────────────────────────────────────────

    def overview(self, symbol: str) -> dict:
        """Fetch company overview (P/E, market cap, EPS, etc.)."""
        params = {
            "function": "OVERVIEW",
            "symbol": normalize_ticker_for_provider(symbol, "alpha_vantage"),
        }
        data = self._call(params)
        return data if data and "Symbol" in data else {}

    # ── Market Regime ───────────────────────────────────────────────

    def spy_5d_return(self) -> float:
        """Return SPY 5-day % return."""
        try:
            df = self.daily("SPY", outputsize="compact")
            if len(df) < 6:
                return 0.0
            return (df["close"].iloc[-1] / df["close"].iloc[-6] - 1) * 100
        except Exception as exc:
            logger.warning("AlphaVantage SPY 5d failed: %s", exc)
            return 0.0

    def vix_latest(self) -> float:
        """Return latest VIX close."""
        try:
            df = self.daily("VIX", outputsize="compact")
            if df.empty:
                return 20.0
            return df["close"].iloc[-1]
        except Exception as exc:
            logger.warning("AlphaVantage VIX failed: %s", exc)
            return 20.0

    def sector_rsi(self, sector_etf: str = "XLK") -> float:
        """Return RSI for a sector ETF (proxy for sector strength)."""
        try:
            df = self.rsi(sector_etf, interval="daily", time_period=14)
            if df.empty:
                return 50.0
            return df.iloc[-1].iloc[-1]
        except Exception as exc:
            logger.warning("AlphaVantage sector RSI failed: %s", exc)
            return 50.0

    def market_breadth(self) -> float:
        """
        Proxy for market breadth: % of S&P 500 stocks above 20-day SMA.
        AlphaVantage doesn't have this directly, so we use SPY RSI as proxy.
        """
        try:
            df = self.rsi("SPY", interval="daily", time_period=20)
            if df.empty:
                return 50.0
            return df.iloc[-1].iloc[-1]
        except Exception as exc:
            logger.warning("AlphaVantage market breadth failed: %s", exc)
            return 50.0


class AlphaVantageProvider:
    """AlphaVantage-backed provider for OHLCV and regime data."""

    def __init__(self, api_key: str | None = None):
        self.client = AlphaVantageClient(api_key=api_key)

    def get_ohlcv(
        self,
        ticker: str,
        period: str | None = None,
        interval: str = "5min",
        start: str | None = None,
        end: str | None = None,
        prepost: bool = False,
    ) -> list[OHLCVBar]:
        """Fetch intraday bars and convert to OHLCVBar list."""
        try:
            df = self.client.intraday(ticker, interval=interval)
            if df.empty:
                return []

            # Filter by date range if provided
            if start:
                df = df[df.index >= pd.Timestamp(start)]
            if end:
                df = df[df.index <= pd.Timestamp(end)]

            bars = []
            for ts, row in df.iterrows():
                bars.append(
                    OHLCVBar(
                        timestamp=ts.to_pydatetime().replace(tzinfo=timezone.utc),
                        open=round(float(row["open"]), 2),
                        high=round(float(row["high"]), 2),
                        low=round(float(row["low"]), 2),
                        close=round(float(row["close"]), 2),
                        volume=int(row["volume"]),
                    )
                )
            return bars
        except Exception as exc:
            logger.error("AlphaVantage get_ohlcv failed for %s: %s", ticker, exc)
            return []

    def get_live_quote(self, ticker: str) -> dict:
        """Fast quote from latest intraday bar."""
        try:
            df = self.client.intraday(ticker, interval="1min")
            if df.empty:
                return None
            latest = df.iloc[-1]
            prev_close = df.iloc[0]["close"] if len(df) > 1 else latest["close"]
            price = latest["close"]
            change = price - prev_close
            change_pct = (change / prev_close * 100) if prev_close else 0.0
            return {
                "price": round(price, 2),
                "change": round(change, 2),
                "change_pct": round(change_pct, 2),
                "volume": int(latest["volume"]),
            }
        except Exception as exc:
            logger.error("AlphaVantage get_live_quote failed for %s: %s", ticker, exc)
            return None

    def get_regime_snapshot(self) -> dict:
        """Fetch all market regime features in one call sequence."""
        return {
            "spy_trend_5d": self.client.spy_5d_return(),
            "vix_level": self.client.vix_latest(),
            "sector_rsi": self.client.sector_rsi(),
            "market_breadth": self.client.market_breadth(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def get_fundamentals(self, ticker: str) -> dict:
        """Fetch company fundamentals."""
        return self.client.overview(ticker)

    def get_indicator(self, ticker: str, indicator: str) -> pd.DataFrame:
        """Fetch a technical indicator by name."""
        if indicator.upper() == "RSI":
            return self.client.rsi(ticker)
        if indicator.upper() == "SMA":
            return self.client.sma(ticker)
        if indicator.upper() == "MACD":
            return self.client.macd(ticker)
        return pd.DataFrame()


def get_alphavantage_provider() -> AlphaVantageProvider:
    """Factory — returns provider or raises if key missing."""
    settings = get_settings()
    if not settings.alphavantage_api_key:
        raise RuntimeError("ALPHAVANTAGE_API_KEY not set")
    return AlphaVantageProvider(api_key=settings.alphavantage_api_key)
