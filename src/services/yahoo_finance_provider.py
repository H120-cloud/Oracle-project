"""Yahoo Finance provider — extended hours via unofficial chart API (no API key)."""

import httpx
import logging
from typing import Optional, Tuple

from src.services.ticker_normalization import normalize_ticker_for_provider

logger = logging.getLogger(__name__)

YAHOO_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
}


def fetch_extended_hours(ticker: str) -> Tuple[Optional[dict], Optional[dict]]:
    """
    Fetch premarket / after-hours data from Yahoo Finance chart API.
    Uses prepost=true to get extended-hours bars.
    Returns (premarket_dict, afterhours_dict) or (None, None) on failure.
    """
    provider_ticker = normalize_ticker_for_provider(ticker, "yahoo")
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{provider_ticker}"
        f"?interval=1m&range=1d&prepost=true"
    )

    try:
        with httpx.Client(timeout=15, headers=YAHOO_HEADERS) as client:
            r = client.get(url)
            if r.status_code != 200:
                logger.debug("Yahoo Finance %s returned %s", ticker, r.status_code)
                return None, None

            data = r.json()
            result = data.get("chart", {}).get("result", [None])[0]
            if not result:
                return None, None

            meta = result.get("meta", {})
            timestamps = result.get("timestamp", [])
            indicators = result.get("indicators", {})
            quotes = indicators.get("quote", [{}])[0]

            if not timestamps:
                return None, None

            # Determine market open time from meta (Unix ms -> seconds)
            reg_mkt_open = meta.get("regularMarketTime")
            pre_mkt_time = meta.get("preMarketTime")
            post_mkt_time = meta.get("postMarketTime")

            # Default splits: pre 09:30, regular 09:30-16:00, post 16:00-20:00 (ET)
            # Yahoo timestamps are Unix seconds
            premarket_bars = []
            afterhours_bars = []

            for i, ts in enumerate(timestamps):
                if ts is None:
                    continue
                # Yahoo timestamps are UTC unix seconds
                # Pre-market: before 09:30 ET (roughly 14:30 UTC)
                # After-hours: after 16:00 ET (roughly 21:00 UTC)
                # Simpler heuristic: use Yahoo's own pre/post price data if available
                high = quotes.get("high", [None] * len(timestamps))[i]
                low = quotes.get("low", [None] * len(timestamps))[i]
                open_p = quotes.get("open", [None] * len(timestamps))[i]
                close = quotes.get("close", [None] * len(timestamps))[i]
                volume = quotes.get("volume", [None] * len(timestamps))[i]

                if all(v is None for v in (high, low, open_p, close, volume)):
                    continue

                # Use meta timestamps to split pre/post
                if pre_mkt_time and ts < pre_mkt_time:
                    premarket_bars.append({"h": high or 0, "l": low or 0, "o": open_p or 0, "c": close or 0, "v": volume or 0})
                elif post_mkt_time and ts >= post_mkt_time:
                    afterhours_bars.append({"h": high or 0, "l": low or 0, "o": open_p or 0, "c": close or 0, "v": volume or 0})
                elif reg_mkt_open and ts < reg_mkt_open:
                    premarket_bars.append({"h": high or 0, "l": low or 0, "o": open_p or 0, "c": close or 0, "v": volume or 0})
                else:
                    # During regular hours — skip
                    pass

            # Build summary dicts
            premarket = _summarize_bars(premarket_bars)
            afterhours = _summarize_bars(afterhours_bars)

            return premarket, afterhours

    except Exception as e:
        logger.debug("Yahoo Finance error for %s: %s", ticker, e)
        return None, None


def _summarize_bars(bars: list) -> dict:
    """Aggregate a list of bar dicts into a summary."""
    if not bars:
        return {"high": 0.0, "low": 0.0, "open": 0.0, "close": 0.0, "volume": 0}

    highs = [b["h"] for b in bars if b["h"] is not None and b["h"] > 0]
    lows = [b["l"] for b in bars if b["l"] is not None and b["l"] > 0]
    opens = [b["o"] for b in bars if b["o"] is not None and b["o"] > 0]
    closes = [b["c"] for b in bars if b["c"] is not None and b["c"] > 0]
    volumes = [b["v"] for b in bars if b["v"] is not None]

    return {
        "high": round(max(highs), 4) if highs else 0.0,
        "low": round(min(lows), 4) if lows else 0.0,
        "open": round(opens[0], 4) if opens else 0.0,
        "close": round(closes[-1], 4) if closes else 0.0,
        "volume": int(sum(volumes)) if volumes else 0,
    }
