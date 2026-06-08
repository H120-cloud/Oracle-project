"""StockTwits Scraper — Social volume & trending signals

Uses StockTwits public API endpoints (no API key needed for basic endpoints):
  - /api/2/trending/symbols.json        → top trending tickers
  - /api/2/search/symbols.json?q=TICKER → confirm ticker exists
  - /api/2/streams/symbol/TICKER.json   → recent messages + sentiment (may 403)

Heavy scraping falls back gracefully so pre-news detection is never blocked.
"""

import json
import logging
import time as _time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

BASE_API = "https://api.stocktwits.com/api/2"
TRENDING_URL = f"{BASE_API}/trending/symbols.json"
SEARCH_URL = f"{BASE_API}/search/symbols.json"
STREAM_URL = f"{BASE_API}/streams/symbol"

TIMEOUT = 8.0
CACHE_TTL = 300  # 5 min

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json",
}


@dataclass
class StockTwitsTrendingItem:
    ticker: str
    name: str = ""
    watchlist_count: int = 0  # watchers on ST
    rank: int = 0


@dataclass
class StockTwitsTickerData:
    """Per-ticker social signal from StockTwits."""
    ticker: str
    message_volume_24h: Optional[int] = None  # messages last 24h (stream API)
    sentiment_bullish_pct: Optional[float] = None  # 0-100
    trending_rank: Optional[int] = None
    watchlist_count: Optional[int] = None
    is_trending: bool = False
    last_checked: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class StockTwitsScraper:
    """Fetch trending tickers and per-ticker social metrics from StockTwits."""

    # Class-level circuit breaker shared across all instances
    _blocked_until: float = 0.0

    def __init__(self):
        self._trending_cache: list[StockTwitsTrendingItem] = []
        self._trending_ts: float = 0.0
        self._ticker_cache: dict[str, StockTwitsTickerData] = {}
        self._ticker_ts: dict[str, float] = {}

    # ── Trending ───────────────────────────────────────────────────────────

    def fetch_trending(self, limit: int = 30) -> list[StockTwitsTrendingItem]:
        """Fetch top trending symbols from StockTwits. Returns list of trending items."""
        now = _time.time()
        if self._trending_cache and (now - self._trending_ts) < CACHE_TTL:
            return self._trending_cache[:limit]

        if StockTwitsScraper._blocked_until and now < StockTwitsScraper._blocked_until:
            return self._trending_cache[:limit]

        try:
            with httpx.Client(timeout=TIMEOUT, headers=HEADERS, follow_redirects=True) as client:
                r = client.get(TRENDING_URL)
                if r.status_code == 429:
                    logger.debug("StockTwits trending rate limited — using cache")
                    return self._trending_cache[:limit]
                if r.status_code in (401, 403):
                    logger.warning("StockTwits API blocked (403) — disabling for 1h")
                    StockTwitsScraper._blocked_until = now + 3600
                    return self._trending_cache[:limit]
                if r.status_code != 200:
                    logger.debug("StockTwits trending returned %s", r.status_code)
                    return self._trending_cache[:limit]

                data = r.json()
                symbols = data.get("symbols", [])
                items: list[StockTwitsTrendingItem] = []
                for i, s in enumerate(symbols[:limit]):
                    items.append(
                        StockTwitsTrendingItem(
                            ticker=s.get("symbol", "").upper(),
                            name=s.get("title", ""),
                            watchlist_count=s.get("watchlist_count", 0),
                            rank=i + 1,
                        )
                    )

                self._trending_cache = items
                self._trending_ts = now
                logger.info("StockTwits trending: fetched %d symbols", len(items))
                return items

        except Exception as e:
            logger.warning("StockTwits trending fetch failed: %s", e)
            return self._trending_cache[:limit]

    # ── Per-ticker stream (messages + sentiment) ─────────────────────────

    def fetch_ticker_data(self, ticker: str) -> StockTwitsTickerData:
        """Fetch social volume and sentiment for a single ticker."""
        now = _time.time()
        if ticker.upper() in self._ticker_cache:
            if (now - self._ticker_ts.get(ticker.upper(), 0)) < CACHE_TTL:
                return self._ticker_cache[ticker.upper()]

        t = ticker.upper()
        result = StockTwitsTickerData(ticker=t)

        # Check if trending first (cheap)
        trending = self.fetch_trending(limit=50)
        for item in trending:
            if item.ticker == t:
                result.is_trending = True
                result.trending_rank = item.rank
                result.watchlist_count = item.watchlist_count
                break

        # Try stream API for message volume / sentiment
        if StockTwitsScraper._blocked_until and _time.time() < StockTwitsScraper._blocked_until:
            pass  # skip stream while circuit breaker is active
        else:
            try:
                with httpx.Client(timeout=TIMEOUT, headers=HEADERS, follow_redirects=True) as client:
                    url = f"{STREAM_URL}/{t}.json"
                    r = client.get(url)
                    if r.status_code == 200:
                        data = r.json()
                        msgs = data.get("messages", [])
                        result.message_volume_24h = len(msgs)
                        bullish = sum(1 for m in msgs if any(
                            kw in (m.get("body") or "").lower()
                            for kw in ("bullish", "long", "buy", "moon", "rocket", "calls", " Calls")
                        ))
                        total = len(msgs)
                        if total > 0:
                            result.sentiment_bullish_pct = round(bullish / total * 100, 1)
                    elif r.status_code == 429:
                        logger.debug("StockTwits stream rate limited for %s", t)
                    elif r.status_code in (401, 403):
                        logger.debug("StockTwits stream blocked for %s", t)
                        StockTwitsScraper._blocked_until = _time.time() + 3600
                    else:
                        logger.debug("StockTwits stream %s returned %s", t, r.status_code)
            except Exception as e:
                logger.debug("StockTwits stream error for %s: %s", t, e)

        self._ticker_cache[t] = result
        self._ticker_ts[t] = now
        return result

    # ── Batch trending check ───────────────────────────────────────────────

    def get_trending_tickers(self, limit: int = 30) -> list[str]:
        """Return just the ticker symbols from trending list."""
        items = self.fetch_trending(limit=limit)
        return [i.ticker for i in items if i.ticker]

    def get_trending_set(self, limit: int = 30) -> set[str]:
        """Return trending tickers as a set for fast lookups."""
        return set(self.get_trending_tickers(limit=limit))

    # ── Search (symbol validation) ───────────────────────────────────────────

    def search_symbol(self, ticker: str) -> bool:
        """Quick check if ticker exists on StockTwits (used by validator)."""
        try:
            with httpx.Client(timeout=TIMEOUT, headers=HEADERS, follow_redirects=True) as client:
                r = client.get(SEARCH_URL, params={"q": ticker.upper()})
                if r.status_code != 200:
                    return False
                data = r.json()
                symbols = data.get("symbols", [])
                return any(
                    sym.get("symbol", "").upper() == ticker.upper()
                    for sym in symbols
                )
        except Exception as exc:
            logger.debug("StockTwits search_symbol failed: %s", exc)
            return False


# ── Singleton convenience ────────────────────────────────────────────────

_scraper: Optional[StockTwitsScraper] = None


def get_stocktwits_scraper() -> StockTwitsScraper:
    global _scraper
    if _scraper is None:
        _scraper = StockTwitsScraper()
    return _scraper


def enrich_anomaly_with_stocktwits(ticker: str) -> dict:
    """
    Fetch StockTwits social data for a ticker and return a dict
    suitable for merging into pre-news anomaly metadata.
    """
    scraper = get_stocktwits_scraper()
    data = scraper.fetch_ticker_data(ticker)
    return {
        "stocktwits_trending": data.is_trending,
        "stocktwits_rank": data.trending_rank,
        "stocktwits_watchers": data.watchlist_count,
        "stocktwits_message_volume": data.message_volume_24h,
        "stocktwits_sentiment_bullish_pct": data.sentiment_bullish_pct,
    }
