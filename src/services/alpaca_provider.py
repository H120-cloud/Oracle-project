"""
Alpaca Market Data Provider — V10

Real-time / low-latency market data via Alpaca API.
Free tier: IEX data (~few seconds delay).
Paid tier: SIP data (real-time).

Implements IMarketDataProvider so it drops in as a replacement for YFinanceProvider.
Requires: ALPACA_API_KEY and ALPACA_SECRET_KEY environment variables.
"""

import os
import logging
from datetime import datetime, timedelta
from typing import Optional, List

import numpy as np
import pandas as pd

from src.models.schemas import OHLCVBar, DipFeatures, BounceFeatures
from src.services.market_data import IMarketDataProvider, DEFAULT_SCAN_UNIVERSE

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy-import alpaca SDK so the rest of the app still works without it
# ---------------------------------------------------------------------------
_alpaca_available = False
try:
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import (
        StockBarsRequest,
        StockLatestQuoteRequest,
        StockSnapshotRequest,
    )
    from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
    from alpaca.trading.client import TradingClient
    from alpaca.trading.requests import (
        MarketOrderRequest,
        LimitOrderRequest,
        GetAssetsRequest,
    )
    from alpaca.trading.enums import OrderSide, TimeInForce, AssetStatus
    _alpaca_available = True
except ImportError:
    logger.warning(
        "alpaca-py not installed. Run: pip install alpaca-py  "
        "AlpacaProvider will raise on first use."
    )


def _require_alpaca():
    if not _alpaca_available:
        raise ImportError(
            "alpaca-py is required for AlpacaProvider. "
            "Install with: pip install alpaca-py"
        )


# ---------------------------------------------------------------------------
# Timeframe mapping
# ---------------------------------------------------------------------------
_TF_MAP = {
    "1m":  ("Minute", 1),
    "5m":  ("Minute", 5),
    "15m": ("Minute", 15),
    "30m": ("Minute", 30),
    "1h":  ("Hour", 1),
    "1d":  ("Day", 1),
    "1w":  ("Week", 1),
}

_PERIOD_MAP = {
    "1d":  timedelta(days=1),
    "5d":  timedelta(days=5),
    "1mo": timedelta(days=30),
    "3mo": timedelta(days=90),
    "6mo": timedelta(days=180),
    "1y":  timedelta(days=365),
    "2y":  timedelta(days=730),
}


class AlpacaProvider(IMarketDataProvider):
    """
    Drop-in replacement for YFinanceProvider using Alpaca APIs.

    Usage:
        provider = AlpacaProvider()        # reads keys from env
        bars = provider.get_ohlcv("AAPL", period="1d", interval="1m")
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        secret_key: Optional[str] = None,
        paper: bool = True,
        universe: Optional[List[str]] = None,
    ):
        _require_alpaca()

        self.api_key = api_key or os.getenv("ALPACA_API_KEY", "")
        self.secret_key = secret_key or os.getenv("ALPACA_SECRET_KEY", "")
        self.paper = paper
        self.universe = universe or DEFAULT_SCAN_UNIVERSE

        if not self.api_key or not self.secret_key:
            raise ValueError(
                "Alpaca API keys required. Set ALPACA_API_KEY and "
                "ALPACA_SECRET_KEY in your .env file. "
                "Get free keys at https://app.alpaca.markets/signup"
            )

        # Data client (market data — no auth needed for IEX, but key speeds up)
        self.data_client = StockHistoricalDataClient(
            api_key=self.api_key,
            secret_key=self.secret_key,
        )

        # Trading client (for paper trading / account info)
        self.trading_client = TradingClient(
            api_key=self.api_key,
            secret_key=self.secret_key,
            paper=self.paper,
        )

        logger.info(
            "AlpacaProvider initialized (paper=%s, universe=%d tickers)",
            paper, len(self.universe),
        )

    # ------------------------------------------------------------------
    # IMarketDataProvider implementation
    # ------------------------------------------------------------------

    def get_scan_universe(self) -> pd.DataFrame:
        """Fetch latest snapshots for scan universe tickers."""
        rows = []
        try:
            request = StockSnapshotRequest(symbol_or_symbols=self.universe)
            snapshots = self.data_client.get_stock_snapshot(request)

            for symbol, snap in snapshots.items():
                try:
                    price = snap.latest_trade.price if snap.latest_trade else 0
                    prev_close = snap.previous_daily_bar.close if snap.previous_daily_bar else price
                    volume = snap.daily_bar.volume if snap.daily_bar else 0
                    change_pct = ((price - prev_close) / prev_close * 100) if prev_close > 0 else 0

                    rows.append({
                        "ticker": symbol,
                        "price": round(price, 2),
                        "volume": volume,
                        "rvol": None,  # Would need historical avg vol
                        "change_percent": round(change_pct, 2),
                        "market_cap": None,
                        "float_shares": None,
                    })
                except Exception as e:
                    logger.debug("Snapshot parse failed for %s: %s", symbol, e)
        except Exception as e:
            logger.error("Failed to fetch Alpaca snapshots: %s", e)

        return pd.DataFrame(rows) if rows else pd.DataFrame()

    def get_ohlcv(
        self,
        ticker: str,
        period: str = None,
        interval: str = "1m",
        start: str = None,
        end: str = None,
        prepost: bool = False,
    ) -> List[OHLCVBar]:
        """Fetch OHLCV bars from Alpaca."""
        _require_alpaca()

        # Resolve timeframe
        tf_key = interval if interval in _TF_MAP else "1m"
        unit_str, amount = _TF_MAP[tf_key]
        unit = TimeFrameUnit(unit_str)
        timeframe = TimeFrame(amount, unit)

        # Resolve date range
        if start and end:
            start_dt = pd.Timestamp(start).to_pydatetime()
            end_dt = pd.Timestamp(end).to_pydatetime()
        elif period and period in _PERIOD_MAP:
            end_dt = datetime.utcnow()
            start_dt = end_dt - _PERIOD_MAP[period]
        else:
            end_dt = datetime.utcnow()
            start_dt = end_dt - timedelta(days=1)

        request = StockBarsRequest(
            symbol_or_symbols=ticker,
            timeframe=timeframe,
            start=start_dt,
            end=end_dt,
        )

        try:
            bars_set = self.data_client.get_stock_bars(request)
            bars_list = bars_set[ticker] if ticker in bars_set else []
        except Exception as e:
            logger.warning("Alpaca get_ohlcv failed for %s: %s", ticker, e)
            return []

        result: List[OHLCVBar] = []
        for bar in bars_list:
            result.append(OHLCVBar(
                timestamp=bar.timestamp,
                open=float(bar.open),
                high=float(bar.high),
                low=float(bar.low),
                close=float(bar.close),
                volume=int(bar.volume),
            ))

        return result

    def compute_dip_features(self, ticker: str) -> Optional[DipFeatures]:
        """Compute DipFeatures using Alpaca 1m bars."""
        try:
            bars = self.get_ohlcv(ticker, period="1d", interval="1m")
            if not bars or len(bars) < 20:
                return None

            close = pd.Series([b.close for b in bars])
            high = pd.Series([b.high for b in bars])
            low = pd.Series([b.low for b in bars])
            open_ = pd.Series([b.open for b in bars])
            volume = pd.Series([b.volume for b in bars])

            # VWAP
            typical = (high + low + close) / 3
            cum_tp_vol = (typical * volume).cumsum()
            cum_vol = volume.cumsum()
            vwap = cum_tp_vol / cum_vol
            vwap_dist = ((close.iloc[-1] - vwap.iloc[-1]) / vwap.iloc[-1]) * 100

            # EMAs
            ema9 = close.ewm(span=9, adjust=False).mean()
            ema20 = close.ewm(span=20, adjust=False).mean()
            ema9_dist = ((close.iloc[-1] - ema9.iloc[-1]) / ema9.iloc[-1]) * 100
            ema20_dist = ((close.iloc[-1] - ema20.iloc[-1]) / ema20.iloc[-1]) * 100

            # Drop from high
            intraday_high = high.max()
            drop = (intraday_high - close.iloc[-1]) / intraday_high * 100

            # Red candles
            candle_colors = (close > open_).astype(int)
            red_count = 0
            for c in reversed(candle_colors.values):
                if c == 0:
                    red_count += 1
                else:
                    break

            # Red/green volume ratio
            red_mask = close < open_
            avg_red = volume[red_mask].mean() if red_mask.any() else 0
            avg_green = volume[~red_mask].mean() if (~red_mask).any() else 1
            red_vol_ratio = avg_red / avg_green if avg_green > 0 else 1.0

            # Lower highs
            recent_highs = high.tail(10).values
            lower_highs = sum(
                1 for i in range(1, len(recent_highs))
                if recent_highs[i] < recent_highs[i - 1]
            )

            # Momentum
            roc = close.pct_change(5)
            momentum_decay = float(roc.iloc[-1] - roc.iloc[-6]) if len(roc) > 6 else 0

            # V7: Velocity / acceleration
            vel = close.pct_change(1) * 100
            price_velocity = float(vel.iloc[-1]) if len(vel) > 0 else 0.0
            prev_vel = float(vel.iloc[-2]) if len(vel) > 1 else price_velocity
            price_acceleration = price_velocity - prev_vel

            if price_velocity < -1.0 and price_acceleration < 0:
                momentum_state = "accelerating_down"
            elif price_velocity < 0 and price_acceleration > 0:
                momentum_state = "slowing_down"
            elif price_velocity > 0.5:
                momentum_state = "bullish"
            else:
                momentum_state = "neutral"

            is_falling_knife = price_velocity < -2.0 and price_acceleration < -0.5

            # Structure
            recent_lows = low.tail(10).values
            local_mins = []
            for i in range(1, len(recent_lows) - 1):
                if recent_lows[i] < recent_lows[i - 1] and recent_lows[i] < recent_lows[i + 1]:
                    local_mins.append(recent_lows[i])
            higher_low = len(local_mins) >= 2 and local_mins[-1] > local_mins[-2]
            recent_support = float(low.rolling(10).min().iloc[-1])
            reclaimed = float(close.iloc[-1]) > recent_support * 1.002
            structure_intact = higher_low or reclaimed

            return DipFeatures(
                vwap_distance_pct=round(float(vwap_dist), 2),
                ema9_distance_pct=round(float(ema9_dist), 2),
                ema20_distance_pct=round(float(ema20_dist), 2),
                drop_from_high_pct=round(float(drop), 2),
                consecutive_red_candles=red_count,
                red_candle_volume_ratio=round(float(red_vol_ratio), 2),
                lower_highs_count=lower_highs,
                momentum_decay=round(float(momentum_decay), 4),
                price_velocity=round(price_velocity, 4),
                price_acceleration=round(price_acceleration, 4),
                momentum_state=momentum_state,
                structure_intact=structure_intact,
                is_falling_knife=is_falling_knife,
            )
        except Exception as e:
            logger.error("compute_dip_features [%s] Alpaca failed: %s", ticker, e)
            return None

    def compute_bounce_features(
        self, ticker: str
    ) -> tuple[Optional[BounceFeatures], float]:
        """Compute BounceFeatures using Alpaca 1m bars."""
        try:
            bars = self.get_ohlcv(ticker, period="1d", interval="1m")
            if not bars or len(bars) < 20:
                return None, 0.0

            close = pd.Series([b.close for b in bars])
            high = pd.Series([b.high for b in bars])
            low = pd.Series([b.low for b in bars])
            open_ = pd.Series([b.open for b in bars])
            volume = pd.Series([b.volume for b in bars])
            current_price = float(close.iloc[-1])

            # Support
            support = float(low.rolling(20).min().iloc[-1])
            support_dist = ((current_price - support) / support) * 100

            # Selling pressure
            red_mask = close < open_
            sell_vol = volume.where(red_mask, 0)
            recent_sell = sell_vol.tail(5).mean()
            prior_sell = sell_vol.iloc[-10:-5].mean() if len(sell_vol) >= 10 else recent_sell
            selling_change = (recent_sell - prior_sell) / prior_sell if prior_sell > 0 else 0

            # Buy/sell ratio
            buy_vol = volume.where(~red_mask, 0)
            buy_sum = buy_vol.tail(10).sum()
            sell_sum = sell_vol.tail(10).sum()
            buy_sell_ratio = buy_sum / sell_sum if sell_sum > 0 else 1.0

            # Higher low
            recent_lows = low.tail(20).values
            local_mins = []
            for i in range(1, len(recent_lows) - 1):
                if recent_lows[i] < recent_lows[i - 1] and recent_lows[i] < recent_lows[i + 1]:
                    local_mins.append(recent_lows[i])
            higher_low = len(local_mins) >= 2 and local_mins[-1] > local_mins[-2]

            # Key level reclaim
            ema9 = close.ewm(span=9, adjust=False).mean()
            was_below = any(close.iloc[-10:-3] < ema9.iloc[-10:-3])
            now_above = close.iloc[-1] > ema9.iloc[-1]
            key_reclaim = was_below and now_above

            # RSI
            delta = close.diff()
            gain = delta.where(delta > 0, 0).rolling(14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
            rs = gain / loss
            rsi_s = 100 - (100 / (1 + rs))
            rsi = float(rsi_s.iloc[-1]) if not rsi_s.isna().iloc[-1] else None

            # MACD
            ema12 = close.ewm(span=12, adjust=False).mean()
            ema26 = close.ewm(span=26, adjust=False).mean()
            macd_line = ema12 - ema26
            signal_line = macd_line.ewm(span=9, adjust=False).mean()
            macd_hist = macd_line - signal_line
            macd_slope = float(macd_hist.iloc[-1] - macd_hist.iloc[-3]) if len(macd_hist) >= 3 else None

            # V7 velocity
            vel = close.pct_change(1) * 100
            price_velocity = float(vel.iloc[-1]) if len(vel) > 0 else 0.0
            prev_vel = float(vel.iloc[-2]) if len(vel) > 1 else price_velocity
            price_acceleration = price_velocity - prev_vel

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
                price_velocity=round(price_velocity, 4),
                price_acceleration=round(price_acceleration, 4),
                momentum_state=momentum_state,
            )
            return features, current_price

        except Exception as e:
            logger.error("compute_bounce_features [%s] Alpaca failed: %s", ticker, e)
            return None, 0.0
