"""
Market Data Service — V1

Uses yfinance to fetch OHLCV and summary data.
Designed as a pluggable provider so Alpaca / Polygon can be swapped in later.
"""

import logging
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from typing import Optional

import numpy as np
import pandas as pd
import yfinance as yf

from src.models.schemas import OHLCVBar, DipFeatures, BounceFeatures
from src.services.data_cache import get_cache, OHLCV_INTRADAY_TTL, OHLCV_DAILY_TTL, FAST_INFO_TTL

logger = logging.getLogger(__name__)

# Default momentum tickers to scan when no screener is available
# NOTE: For penny stocks under $2, use Finviz scanner (finviz-under2) instead of this list
DEFAULT_SCAN_UNIVERSE = [
    # Mega Cap Tech
    "AAPL", "MSFT", "NVDA", "TSLA", "AMD", "META", "AMZN", "GOOG", "GOOGL",
    "NFLX", "CRM", "ORCL", "ADBE", "INTC", "AVGO", "TXN", "QCOM", "MU",
    
    # ETFs & Indices
    "SPY", "QQQ", "IWM", "ARKK", "XLF", "XLK", "XLE", "GDX", "VIX",
    
    # Fintech
    "SOFI", "PLTR", "HOOD", "SQ", "PYPL", "UPST", "AFRM", "RBLX",
    
    # EV & Auto
    "RIVN", "NIO", "XPEV", "LI", "FSR", "GOEV", "PSNY", "LCID",
    
    # Gaming & Entertainment  
    "UBER", "LYFT", "DASH", "ABNB", "DKNG", "PENN", "CZR", "MGM",
    
    # Chinese Tech
    "BABA", "JD", "PDD", "BIDU", "NTES",
    
    # Meme/Momentum
    "GME", "AMC", "BB", "NOK",
    
    # Space
    "ASTS", "RKLB", "SPCE", "ACHR", "LILM", "JOBY",
    
    # Oil & Energy
    "XOM", "CVX", "OXY", "COP", "SLB", "HAL", "MRO", "DVN", "FANG",
    
    # Banks & Financials
    "JPM", "BAC", "GS", "MS", "WFC", "C", "USB", "PNC", "TFC",
    
    # AI/Tech
    "AI", "SOUN", "IONQ", "QBTS",
    "RBLX", "SHOP", "CRWD", "SNOW", "NET", "ENPH",
]


class IMarketDataProvider(ABC):
    """Interface for market data providers — swap implementations for V2+."""

    @abstractmethod
    def get_scan_universe(self) -> pd.DataFrame:
        ...

    @abstractmethod
    def get_ohlcv(
        self, ticker: str, period: str = None, interval: str = "1m",
        start: str = None, end: str = None, prepost: bool = False,
    ) -> list[OHLCVBar]:
        ...

    @abstractmethod
    def compute_dip_features(self, ticker: str) -> Optional[DipFeatures]:
        ...

    @abstractmethod
    def compute_bounce_features(
        self, ticker: str
    ) -> tuple[Optional[BounceFeatures], float]:
        ...


class YFinanceProvider(IMarketDataProvider):
    """V1 market data implementation backed by yfinance."""

    def __init__(self, universe: list[str] | None = None):
        self.universe = universe or DEFAULT_SCAN_UNIVERSE

    # ── scan universe ────────────────────────────────────────────────────

    def get_scan_universe(self) -> pd.DataFrame:
        """Fetch latest quote data for the scan universe."""
        rows = []
        tickers_obj = yf.Tickers(" ".join(self.universe))

        for symbol in self.universe:
            try:
                tkr = tickers_obj.tickers.get(symbol)
                if tkr is None:
                    continue
                info = tkr.fast_info
                hist = tkr.history(period="1d", interval="1m")
                if hist.empty:
                    continue

                price = float(hist["Close"].iloc[-1])
                volume = float(hist["Volume"].sum())
                open_price = float(hist["Open"].iloc[0])
                change_pct = ((price - open_price) / open_price) * 100 if open_price else 0

                # Rough RVOL: today's volume vs 20-day average daily volume
                avg_vol = getattr(info, "three_month_average_volume", None)
                rvol = volume / avg_vol if avg_vol and avg_vol > 0 else None

                rows.append({
                    "ticker": symbol,
                    "price": price,
                    "volume": volume,
                    "rvol": rvol,
                    "change_percent": round(change_pct, 2),
                    "market_cap": getattr(info, "market_cap", None),
                    "float_shares": getattr(info, "shares", None),
                })
            except Exception as exc:
                logger.warning("Failed to fetch %s: %s", symbol, exc)

        return pd.DataFrame(rows)

    # ── OHLCV ────────────────────────────────────────────────────────────

    def get_ohlcv(
        self, ticker: str, period: str = None, interval: str = "1m",
        start: str = None, end: str = None, prepost: bool = False,
    ) -> list[OHLCVBar]:
        """Fetch OHLCV data with caching. Use start/end for historical dates, period for recent data."""
        cache = get_cache()
        cache_key = f"ohlcv:{ticker}:{interval}:{start}:{end}:{period}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        ticker_obj = yf.Ticker(ticker)
        
        # If start/end provided, use them for historical data
        if start and end:
            hist = ticker_obj.history(start=start, end=end, interval=interval, prepost=prepost)
        elif period:
            # Fall back to period (relative to today)
            hist = ticker_obj.history(period=period, interval=interval, prepost=prepost)
        else:
            # Default to 1 day
            hist = ticker_obj.history(period="1d", interval=interval, prepost=prepost)
        
        bars: list[OHLCVBar] = []
        for ts, row in hist.iterrows():
            bars.append(
                OHLCVBar(
                    timestamp=ts.to_pydatetime(),
                    open=float(row["Open"]),
                    high=float(row["High"]),
                    low=float(row["Low"]),
                    close=float(row["Close"]),
                    volume=float(row["Volume"]),
                )
            )

        ttl = OHLCV_DAILY_TTL if interval in ("1d", "1wk") else OHLCV_INTRADAY_TTL
        cache.set(cache_key, bars, ttl)
        return bars

    def get_live_quote(self, ticker: str) -> dict:
        """Fast live quote with caching: price, prev close, premarket/afterhours data."""
        cache = get_cache()
        cache_key = f"quote:{ticker}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            tkr = yf.Ticker(ticker)
            fi = tkr.fast_info

            current_price = getattr(fi, "last_price", 0.0) or 0.0
            prev_close = getattr(fi, "previous_close", 0.0) or 0.0
            market_cap = getattr(fi, "market_cap", 0) or 0
            day_high = getattr(fi, "day_high", 0.0) or 0.0
            day_low = getattr(fi, "day_low", 0.0) or 0.0
            open_price = getattr(fi, "open", 0.0) or 0.0
            volume = getattr(fi, "last_volume", 0) or 0

            change = current_price - prev_close if prev_close > 0 else 0
            change_pct = (change / prev_close * 100) if prev_close > 0 else 0

            # Get extended hours data in one call
            df_ext = tkr.history(period="1d", interval="1m", prepost=True)

            pre_high = 0.0
            pre_low = 0.0
            pre_volume = 0
            after_high = 0.0
            after_low = 0.0
            after_volume = 0
            gap_pct = 0.0

            if not df_ext.empty:
                # Split into premarket (before 9:30 ET), regular, afterhours (after 16:00 ET)
                idx = df_ext.index
                if hasattr(idx, 'tz_convert'):
                    try:
                        idx_et = idx.tz_convert('US/Eastern')
                    except Exception:
                        idx_et = idx
                else:
                    idx_et = idx

                pre_mask = idx_et.hour * 60 + idx_et.minute < 570   # before 9:30
                after_mask = idx_et.hour * 60 + idx_et.minute >= 960  # after 16:00

                pre_df = df_ext[pre_mask]
                after_df = df_ext[after_mask]

                if not pre_df.empty:
                    pre_high = float(pre_df["High"].max())
                    pre_low = float(pre_df["Low"].min())
                    pre_volume = int(pre_df["Volume"].sum())
                    first_pre = float(pre_df["Close"].iloc[0])
                    if prev_close > 0:
                        gap_pct = ((first_pre - prev_close) / prev_close) * 100

                if not after_df.empty:
                    after_high = float(after_df["High"].max())
                    after_low = float(after_df["Low"].min())
                    after_volume = int(after_df["Volume"].sum())

            result = {
                "price": round(current_price, 2),
                "previous_close": round(prev_close, 2),
                "open": round(open_price, 2),
                "change": round(change, 2),
                "change_pct": round(change_pct, 2),
                "day_high": round(day_high, 2),
                "day_low": round(day_low, 2),
                "volume": volume,
                "market_cap": market_cap,
                "premarket": {
                    "high": round(pre_high, 2),
                    "low": round(pre_low, 2),
                    "volume": pre_volume,
                    "gap_pct": round(gap_pct, 2),
                },
                "afterhours": {
                    "high": round(after_high, 2),
                    "low": round(after_low, 2),
                    "volume": after_volume,
                },
            }
            cache.set(cache_key, result, FAST_INFO_TTL)
            return result
        except Exception as exc:
            logger.warning("get_live_quote failed for %s: %s", ticker, exc)
            return {"price": 0, "previous_close": 0, "change": 0, "change_pct": 0}

    # ── Feature computation ──────────────────────────────────────────────

    def compute_dip_features(self, ticker: str) -> Optional[DipFeatures]:
        """Compute DipFeatures from intraday 1-min data."""
        try:
            hist = yf.Ticker(ticker).history(period="1d", interval="1m")
            if hist.empty or len(hist) < 20:
                return None

            close = hist["Close"]
            high = hist["High"]
            volume = hist["Volume"]

            # VWAP
            typical_price = (hist["High"] + hist["Low"] + hist["Close"]) / 3
            cum_tp_vol = (typical_price * volume).cumsum()
            cum_vol = volume.cumsum()
            vwap = cum_tp_vol / cum_vol
            vwap_dist = ((close.iloc[-1] - vwap.iloc[-1]) / vwap.iloc[-1]) * 100

            # EMAs
            ema9 = close.ewm(span=9, adjust=False).mean()
            ema20 = close.ewm(span=20, adjust=False).mean()
            ema9_dist = ((close.iloc[-1] - ema9.iloc[-1]) / ema9.iloc[-1]) * 100
            ema20_dist = ((close.iloc[-1] - ema20.iloc[-1]) / ema20.iloc[-1]) * 100

            # Drop from intraday high
            intraday_high = high.max()
            drop_from_high = (
                (intraday_high - close.iloc[-1]) / intraday_high
            ) * 100

            # Consecutive red candles (from end)
            candle_colors = (close > hist["Open"]).astype(int)  # 1=green, 0=red
            red_count = 0
            for c in reversed(candle_colors.values):
                if c == 0:
                    red_count += 1
                else:
                    break

            # Red vs green candle avg volume
            red_mask = close < hist["Open"]
            green_mask = ~red_mask
            avg_red_vol = volume[red_mask].mean() if red_mask.any() else 0
            avg_green_vol = volume[green_mask].mean() if green_mask.any() else 1
            red_vol_ratio = avg_red_vol / avg_green_vol if avg_green_vol > 0 else 1.0

            # Lower highs (last 10 bars)
            recent_highs = high.tail(10).values
            lower_highs = sum(
                1 for i in range(1, len(recent_highs))
                if recent_highs[i] < recent_highs[i - 1]
            )

            # Momentum decay: rate of change of rate of change
            roc = close.pct_change(5)
            momentum_decay = float(roc.iloc[-1] - roc.iloc[-6]) if len(roc) > 6 else 0

            # V7: Velocity and acceleration calculations
            # Velocity: price change per bar
            velocity_series = close.pct_change(1) * 100  # % per bar
            price_velocity = float(velocity_series.iloc[-1]) if len(velocity_series) > 0 else 0.0
            prev_velocity = float(velocity_series.iloc[-2]) if len(velocity_series) > 1 else price_velocity

            # Acceleration: change in velocity
            price_acceleration = price_velocity - prev_velocity

            # Momentum state classification
            if price_velocity < -1.0 and price_acceleration < 0:
                momentum_state = "accelerating_down"
            elif price_velocity < 0 and price_acceleration > 0:
                momentum_state = "slowing_down"
            elif price_velocity > 0.5:
                momentum_state = "bullish"
            else:
                momentum_state = "neutral"

            # Falling knife detection: strong negative velocity + acceleration
            is_falling_knife = price_velocity < -2.0 and price_acceleration < -0.5

            # Structure check: higher low maintained or reclaimed
            recent_lows = low.tail(10).values
            local_mins = []
            for i in range(1, len(recent_lows) - 1):
                if recent_lows[i] < recent_lows[i - 1] and recent_lows[i] < recent_lows[i + 1]:
                    local_mins.append(recent_lows[i])
            higher_low_maintained = len(local_mins) >= 2 and local_mins[-1] > local_mins[-2]

            # Structure reclaim: was below support, now above
            recent_support = float(low.rolling(10).min().iloc[-1])
            structure_reclaimed = float(close.iloc[-1]) > recent_support * 1.002
            structure_intact = higher_low_maintained or structure_reclaimed

            return DipFeatures(
                vwap_distance_pct=round(float(vwap_dist), 2),
                ema9_distance_pct=round(float(ema9_dist), 2),
                ema20_distance_pct=round(float(ema20_dist), 2),
                drop_from_high_pct=round(float(drop_from_high), 2),
                consecutive_red_candles=red_count,
                red_candle_volume_ratio=round(float(red_vol_ratio), 2),
                lower_highs_count=lower_highs,
                momentum_decay=round(float(momentum_decay), 4),
                # V7 fields
                price_velocity=round(price_velocity, 4),
                price_acceleration=round(price_acceleration, 4),
                momentum_state=momentum_state,
                structure_intact=structure_intact,
                is_falling_knife=is_falling_knife,
            )

        except Exception as exc:
            logger.error("compute_dip_features [%s] failed: %s", ticker, exc)
            return None

    def compute_bounce_features(
        self, ticker: str
    ) -> tuple[Optional[BounceFeatures], float]:
        """Compute BounceFeatures and current price from intraday data."""
        try:
            hist = yf.Ticker(ticker).history(period="1d", interval="1m")
            if hist.empty or len(hist) < 20:
                return None, 0.0

            close = hist["Close"]
            low = hist["Low"]
            volume = hist["Volume"]
            current_price = float(close.iloc[-1])

            # Simple support: rolling 20-bar low
            support = float(low.rolling(20).min().iloc[-1])
            support_dist = ((current_price - support) / support) * 100

            # Selling pressure change: compare last-5-bar avg sell vol to prior-5
            red_mask = close < hist["Open"]
            sell_vol = volume.where(red_mask, 0)
            recent_sell = sell_vol.tail(5).mean()
            prior_sell = sell_vol.iloc[-10:-5].mean() if len(sell_vol) >= 10 else recent_sell
            selling_change = (
                (recent_sell - prior_sell) / prior_sell
                if prior_sell > 0
                else 0
            )

            # Buy/sell ratio last 10 bars
            buy_vol = volume.where(~red_mask, 0)
            buy_sum = buy_vol.tail(10).sum()
            sell_sum = sell_vol.tail(10).sum()
            buy_sell_ratio = buy_sum / sell_sum if sell_sum > 0 else 1.0

            # Higher low: compare last 2 swing lows
            recent_lows = low.tail(20).values
            local_mins = []
            for i in range(1, len(recent_lows) - 1):
                if recent_lows[i] < recent_lows[i - 1] and recent_lows[i] < recent_lows[i + 1]:
                    local_mins.append(recent_lows[i])
            higher_low = (
                len(local_mins) >= 2 and local_mins[-1] > local_mins[-2]
            )

            # Key level reclaim: price above EMA-9 after being below
            ema9 = close.ewm(span=9, adjust=False).mean()
            was_below = any(close.iloc[-10:-3] < ema9.iloc[-10:-3])
            now_above = close.iloc[-1] > ema9.iloc[-1]
            key_reclaim = was_below and now_above

            # RSI (14-period on 1-min)
            delta = close.diff()
            gain = delta.where(delta > 0, 0).rolling(14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
            rs = gain / loss
            rsi_series = 100 - (100 / (1 + rs))
            rsi = float(rsi_series.iloc[-1]) if not rsi_series.isna().iloc[-1] else None

            # MACD histogram slope
            ema12 = close.ewm(span=12, adjust=False).mean()
            ema26 = close.ewm(span=26, adjust=False).mean()
            macd_line = ema12 - ema26
            signal_line = macd_line.ewm(span=9, adjust=False).mean()
            macd_hist = macd_line - signal_line
            macd_slope = (
                float(macd_hist.iloc[-1] - macd_hist.iloc[-3])
                if len(macd_hist) >= 3
                else None
            )

            # V7: Velocity and acceleration for bounce detection
            velocity_series = close.pct_change(1) * 100
            price_velocity = float(velocity_series.iloc[-1]) if len(velocity_series) > 0 else 0.0
            prev_velocity = float(velocity_series.iloc[-2]) if len(velocity_series) > 1 else price_velocity
            price_acceleration = price_velocity - prev_velocity

            # Bounce momentum state: prefer slowing down or accelerating up
            if price_velocity > 0 and price_acceleration > 0:
                momentum_state = "accelerating_up"
            elif price_velocity < 0 and price_acceleration > 0:
                momentum_state = "slowing_down"
            elif price_velocity > 0.3:
                momentum_state = "bullish"
            else:
                momentum_state = "neutral"

            features = BounceFeatures(
                support_distance_pct=round(float(support_dist), 2),
                selling_pressure_change=round(float(selling_change), 4),
                buying_pressure_ratio=round(float(buy_sell_ratio), 2),
                higher_low_formed=higher_low,
                key_level_reclaimed=key_reclaim,
                rsi=round(rsi, 1) if rsi is not None else None,
                macd_histogram_slope=round(macd_slope, 4) if macd_slope is not None else None,
                # V7 fields
                price_velocity=round(price_velocity, 4),
                price_acceleration=round(price_acceleration, 4),
                momentum_state=momentum_state,
            )

            return features, current_price

        except Exception as exc:
            logger.error("compute_bounce_features [%s] failed: %s", ticker, exc)
            return None, 0.0
