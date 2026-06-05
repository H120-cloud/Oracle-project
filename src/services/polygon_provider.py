"""Polygon.io provider — extended hours bars via free tier."""

import os
import threading
import time
from datetime import datetime, timedelta
from typing import Optional, Tuple
from zoneinfo import ZoneInfo

import httpx

from src.config import get_settings
from src.models.market_data import OHLCVBar
from src.services.ticker_normalization import normalize_ticker_for_provider

import logging

logger = logging.getLogger(__name__)

# Polygon free tier allows only 5 requests/minute. Enforce a global minimum
# spacing between requests so we never exceed quota and trigger 429 storms.
# Override via POLYGON_REQUESTS_PER_MINUTE for paid tiers (e.g. set to 0 to disable).
_POLYGON_RPM = float(os.environ.get("POLYGON_REQUESTS_PER_MINUTE", "5") or 5)
_POLYGON_MIN_INTERVAL = (60.0 / _POLYGON_RPM) if _POLYGON_RPM > 0 else 0.0
_POLYGON_LAST_REQUEST = 0.0
_POLYGON_REQUEST_LOCK = threading.Lock()

POLYGON_API_KEY = os.environ.get("POLYGON_API_KEY", "") or get_settings().polygon_api_key
BASE_URL = "https://api.polygon.io"
ET = ZoneInfo("America/New_York")


def _limited_client_get(url: str, *, params: dict | None = None, timeout: float = 15.0) -> httpx.Response:
    """HTTP GET that shares Polygon's global request spacing across helpers."""
    global _POLYGON_LAST_REQUEST
    if _POLYGON_MIN_INTERVAL > 0:
        with _POLYGON_REQUEST_LOCK:
            elapsed = time.time() - _POLYGON_LAST_REQUEST
            if elapsed < _POLYGON_MIN_INTERVAL:
                time.sleep(_POLYGON_MIN_INTERVAL - elapsed)
            _POLYGON_LAST_REQUEST = time.time()

    with httpx.Client(timeout=timeout) as client:
        return client.get(url, params=params)


def _period_days(period: str | None) -> int:
    if not period:
        return 1
    mapping = {
        "1d": 1,
        "2d": 2,
        "5d": 7,
        "1mo": 35,
        "3mo": 100,
        "6mo": 190,
        "1y": 370,
    }
    return mapping.get(period, 1)


def _interval_parts(interval: str) -> tuple[int, str]:
    normalized = (interval or "1m").lower()
    if normalized.endswith("m"):
        return max(1, int(normalized[:-1] or 1)), "minute"
    if normalized.endswith("h"):
        return max(1, int(normalized[:-1] or 1)), "hour"
    if normalized in {"1d", "d", "day"}:
        return 1, "day"
    return 1, "minute"


class PolygonProvider:
    """Polygon.io-backed market data provider for quotes and OHLCV bars."""

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or POLYGON_API_KEY
        if not self.api_key:
            raise RuntimeError("POLYGON_API_KEY not configured")
        self._ohlcv_cache: dict[str, tuple[float, list[OHLCVBar]]] = {}
        self._quote_cache: dict[str, tuple[float, dict]] = {}
        self._ttl_seconds = 30.0

    def _get(self, path: str, params: dict | None = None, _retry: int = 3) -> dict:
        global _POLYGON_LAST_REQUEST
        params = dict(params or {})
        params["apiKey"] = self.api_key
        url = f"{BASE_URL}{path}"

        for attempt in range(_retry):
            # Enforce global minimum spacing between requests to respect quota.
            if _POLYGON_MIN_INTERVAL > 0:
                with _POLYGON_REQUEST_LOCK:
                    elapsed = time.time() - _POLYGON_LAST_REQUEST
                    if elapsed < _POLYGON_MIN_INTERVAL:
                        time.sleep(_POLYGON_MIN_INTERVAL - elapsed)
                    _POLYGON_LAST_REQUEST = time.time()

            with httpx.Client(timeout=20.0) as client:
                response = client.get(url, params=params)

            if response.status_code == 429:
                backoff = 2.0 * (attempt + 1)
                logger.debug("Polygon rate limit on %s, retry in %.1fs", path, backoff)
                time.sleep(backoff)
                continue
            if response.status_code in (401, 403):
                raise RuntimeError("Polygon authorization failed")
            response.raise_for_status()
            return response.json()

        raise RuntimeError("Polygon rate limit")

    def get_scan_universe(self):
        return []

    def get_ohlcv(
        self,
        ticker: str,
        period: str = None,
        interval: str = "1m",
        start: str = None,
        end: str = None,
        prepost: bool = False,
    ) -> list[OHLCVBar]:
        provider_ticker = normalize_ticker_for_provider(ticker, "polygon")
        cache_key = f"{ticker.upper()}:{period}:{interval}:{start}:{end}:{prepost}"
        cached = self._ohlcv_cache.get(cache_key)
        if cached and time.time() - cached[0] < self._ttl_seconds:
            return cached[1]

        multiplier, timespan = _interval_parts(interval)
        now_et = datetime.now(ET)
        if start:
            from_date = start[:10]
        else:
            from_date = (now_et - timedelta(days=_period_days(period) + 3)).strftime("%Y-%m-%d")
        if end:
            to_date = end[:10]
        else:
            to_date = now_et.strftime("%Y-%m-%d")

        path = f"/v2/aggs/ticker/{provider_ticker}/range/{multiplier}/{timespan}/{from_date}/{to_date}"
        try:
            data = self._get(path, {"adjusted": "true", "sort": "asc", "limit": 50000})
        except Exception as exc:
            logger.warning("Polygon get_ohlcv failed for %s: %s", ticker, exc)
            return []

        results = data.get("results") or []
        bars: list[OHLCVBar] = []
        for row in results:
            try:
                ts = datetime.fromtimestamp(float(row["t"]) / 1000.0, tz=ET)
                if not prepost and timespan != "day":
                    minutes = ts.hour * 60 + ts.minute
                    if minutes < 570 or minutes >= 960:
                        continue
                bars.append(
                    OHLCVBar(
                        timestamp=ts,
                        open=float(row.get("o", 0) or 0),
                        high=float(row.get("h", 0) or 0),
                        low=float(row.get("l", 0) or 0),
                        close=float(row.get("c", 0) or 0),
                        volume=float(row.get("v", 0) or 0),
                    )
                )
            except Exception:
                continue
        self._ohlcv_cache[cache_key] = (time.time(), bars)
        return bars

    def get_live_quote(self, ticker: str) -> dict:
        provider_ticker = normalize_ticker_for_provider(ticker, "polygon")
        cache_key = ticker.upper()
        cached = self._quote_cache.get(cache_key)
        if cached and time.time() - cached[0] < self._ttl_seconds:
            return cached[1]

        bars = self.get_ohlcv(ticker, period="1d", interval="5m", prepost=True)
        if not bars:
            return {"price": 0, "previous_close": 0, "change": 0, "change_pct": 0}

        latest = bars[-1]
        prev_close = 0.0
        avg_volume = 0
        try:
            prev = self._get(f"/v2/aggs/ticker/{provider_ticker}/prev", {"adjusted": "true"})
            prev_results = prev.get("results") or []
            if prev_results:
                prev_close = float(prev_results[0].get("c", 0) or 0)
                avg_volume = int(prev_results[0].get("v", 0) or 0)
        except Exception as exc:
            logger.debug("Polygon previous close failed for %s: %s", ticker, exc)

        if prev_close <= 0:
            for bar in reversed(bars[:-1]):
                if bar.close > 0:
                    prev_close = float(bar.close)
                    break

        price = float(latest.close)
        change = price - prev_close if prev_close > 0 else 0.0
        change_pct = (change / prev_close * 100.0) if prev_close > 0 else 0.0
        result = {
            "price": round(price, 4),
            "previous_close": round(prev_close, 4),
            "open": round(float(bars[0].open), 4),
            "change": round(change, 4),
            "change_pct": round(change_pct, 2),
            "day_high": round(max(float(b.high) for b in bars), 4),
            "day_low": round(min(float(b.low) for b in bars), 4),
            "volume": int(sum(float(b.volume) for b in bars)),
            "average_volume": avg_volume,
            "market_cap": 0,
            "premarket": {"high": 0.0, "low": 0.0, "volume": 0, "gap_pct": 0.0},
            "afterhours": {"high": 0.0, "low": 0.0, "volume": 0},
        }
        self._quote_cache[cache_key] = (time.time(), result)
        return result


def _fmt_polygon_date(dt: datetime) -> str:
    """Polygon uses YYYY-MM-DD format."""
    return dt.strftime("%Y-%m-%d")


def _fmt_polygon_time(dt: datetime) -> str:
    """Polygon uses HH:MM or unix ms for intraday."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


def fetch_premarket_bars(ticker: str) -> Tuple[Optional[dict], Optional[dict]]:
    """
    Fetch premarket bars (04:00-09:30 ET) from Polygon.
    Returns (premarket_high, premarket_low) or (None, None) on failure/no key.
    """
    if not POLYGON_API_KEY:
        return None, None

    now_et = datetime.now(ET)
    # If after market open, fetch today's premarket. If before, fetch yesterday's premarket.
    if now_et.hour < 4:
        # Before premarket — no premarket data for today yet
        return {"high": 0.0, "low": 0.0, "open": 0.0, "close": 0.0, "volume": 0}, None

    # Today's date for premarket window
    date_str = _fmt_polygon_date(now_et)

    # Polygon aggregates: 1-minute bars between 04:00 and 09:30
    from_ts = f"{date_str}T04:00:00"
    to_ts = f"{date_str}T09:30:00"

    provider_ticker = normalize_ticker_for_provider(ticker, "polygon")
    url = (
        f"{BASE_URL}/v2/aggs/ticker/{provider_ticker}/range/1/minute/"
        f"{from_ts}/{to_ts}?adjusted=true&sort=asc&apiKey={POLYGON_API_KEY}"
    )

    try:
        r = _limited_client_get(url, timeout=15)
        if r.status_code == 429:
            logger.debug("Polygon rate limited for %s premarket", ticker)
            return None, None
        if r.status_code == 403:
            logger.debug("Polygon auth failed - check POLYGON_API_KEY")
            return None, None
        if r.status_code != 200:
            logger.debug("Polygon premarket %s returned %s", ticker, r.status_code)
            return None, None

        data = r.json()
        results = data.get("results", [])
        if not results:
            return {"high": 0.0, "low": 0.0, "open": 0.0, "close": 0.0, "volume": 0}, None

        high = max(b.get("h", 0) for b in results)
        low = min(b.get("l", float("inf")) for b in results)
        low = low if low != float("inf") else 0.0
        open_price = results[0].get("o", 0)
        close_price = results[-1].get("c", 0)
        volume = sum(b.get("v", 0) for b in results)

        return (
            {"high": round(high, 4), "low": round(low, 4), "open": round(open_price, 4), "close": round(close_price, 4), "volume": int(volume)},
            None,
        )
    except Exception as e:
        logger.debug("Polygon premarket error for %s: %s", ticker, e)
        return None, None


def fetch_afterhours_bars(ticker: str) -> Tuple[Optional[dict], Optional[dict]]:
    """
    Fetch after-hours bars (16:00-20:00 ET) from Polygon.
    Returns (afterhours_high, afterhours_low) or (None, None) on failure/no key.
    """
    if not POLYGON_API_KEY:
        return None, None

    now_et = datetime.now(ET)
    # After-hours is current day 16:00-20:00. If after 20:00, it's today's AH.
    # If before 16:00, we want yesterday's AH.
    if now_et.hour < 16:
        yesterday = now_et - timedelta(days=1)
        date_str = _fmt_polygon_date(yesterday)
    else:
        date_str = _fmt_polygon_date(now_et)

    from_ts = f"{date_str}T16:00:00"
    to_ts = f"{date_str}T20:00:00"

    provider_ticker = normalize_ticker_for_provider(ticker, "polygon")
    url = (
        f"{BASE_URL}/v2/aggs/ticker/{provider_ticker}/range/1/minute/"
        f"{from_ts}/{to_ts}?adjusted=true&sort=asc&apiKey={POLYGON_API_KEY}"
    )

    try:
        r = _limited_client_get(url, timeout=15)
        if r.status_code == 429:
            logger.debug("Polygon rate limited for %s afterhours", ticker)
            return None, None
        if r.status_code == 403:
            logger.debug("Polygon auth failed")
            return None, None
        if r.status_code != 200:
            logger.debug("Polygon afterhours %s returned %s", ticker, r.status_code)
            return None, None

        data = r.json()
        results = data.get("results", [])
        if not results:
            return {"high": 0.0, "low": 0.0, "open": 0.0, "close": 0.0, "volume": 0}, None

        high = max(b.get("h", 0) for b in results)
        low = min(b.get("l", float("inf")) for b in results)
        low = low if low != float("inf") else 0.0
        open_price = results[0].get("o", 0)
        close_price = results[-1].get("c", 0)
        volume = sum(b.get("v", 0) for b in results)

        return (
            {"high": round(high, 4), "low": round(low, 4), "open": round(open_price, 4), "close": round(close_price, 4), "volume": int(volume)},
            None,
        )
    except Exception as e:
        logger.debug("Polygon afterhours error for %s: %s", ticker, e)
        return None, None
