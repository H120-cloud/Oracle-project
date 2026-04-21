"""
Data Cache — TTL-based caching for market data.

Prevents excessive yfinance calls, avoids rate-limiting, and speeds up responses.
- OHLCV data: cached for configurable TTL (default 60s intraday, 5min daily)
- Fast info (price): cached for 10s
- Thread-safe with locking
"""

import logging
import time
import threading
from typing import Optional, Any, Dict, Tuple
from functools import wraps

logger = logging.getLogger(__name__)


class DataCache:
    """Simple thread-safe TTL cache for market data."""

    def __init__(self):
        self._cache: Dict[str, Tuple[Any, float]] = {}  # key -> (value, expiry_time)
        self._lock = threading.Lock()
        self._stats = {"hits": 0, "misses": 0}

    def get(self, key: str) -> Optional[Any]:
        """Get value if exists and not expired."""
        with self._lock:
            if key in self._cache:
                value, expiry = self._cache[key]
                if time.time() < expiry:
                    self._stats["hits"] += 1
                    return value
                else:
                    del self._cache[key]
            self._stats["misses"] += 1
            return None

    def set(self, key: str, value: Any, ttl_seconds: float = 60):
        """Store value with TTL."""
        with self._lock:
            self._cache[key] = (value, time.time() + ttl_seconds)

    def invalidate(self, key: str):
        """Remove a specific key."""
        with self._lock:
            self._cache.pop(key, None)

    def clear(self):
        """Clear all cached data."""
        with self._lock:
            self._cache.clear()
            logger.info("Data cache cleared")

    def cleanup_expired(self):
        """Remove expired entries (call periodically)."""
        now = time.time()
        with self._lock:
            expired = [k for k, (_, exp) in self._cache.items() if now >= exp]
            for k in expired:
                del self._cache[k]
            if expired:
                logger.debug("Cache cleanup: removed %d expired entries", len(expired))

    @property
    def stats(self) -> dict:
        total = self._stats["hits"] + self._stats["misses"]
        hit_rate = (self._stats["hits"] / total * 100) if total > 0 else 0
        return {
            "hits": self._stats["hits"],
            "misses": self._stats["misses"],
            "hit_rate_pct": round(hit_rate, 1),
            "cached_entries": len(self._cache),
        }


# Global singleton
_cache = DataCache()


def get_cache() -> DataCache:
    return _cache


# TTL constants
OHLCV_INTRADAY_TTL = 60    # 1 minute for intraday bars
OHLCV_DAILY_TTL = 300       # 5 minutes for daily bars
FAST_INFO_TTL = 15           # 15 seconds for live price
ANALYSIS_TTL = 120           # 2 minutes for analysis results
