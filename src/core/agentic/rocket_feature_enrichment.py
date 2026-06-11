"""Finnhub company-profile enrichment for Rocket shadow feature rows.

The Rocket model's two most informative categoricals — market_cap_category and
float_category — are hardcoded ``None`` on the pre-news pipeline and frequently
missing on news candidates, inflating feature_null_count and dragging
prediction_confidence to LOW. Finnhub's free ``company_profile2`` endpoint
(works from cloud IPs) provides marketCapitalization and shareOutstanding,
from which both categories derive using the SAME thresholds the orchestrator
used to label the training data.

Strictly telemetry-side: this enriches the *feature row copy* used for shadow
predictions only. It never mutates candidates, never touches Telegram gating,
and any failure degrades to the un-enriched row.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Finnhub free tier: 60 req/min. Profiles change rarely; cache for hours and
# negatively cache unknown tickers so they are not re-fetched every scan.
PROFILE_CACHE_TTL_SECONDS = float(
    os.environ.get("FINNHUB_PROFILE_CACHE_TTL_SECONDS", str(6 * 3600)) or 6 * 3600
)


def derive_float_category(shares: Optional[float]) -> Optional[str]:
    """Mirror NewsMomentumOrchestrator._float_category thresholds exactly,
    except: never fabricate a default when the input is unknown."""
    if shares is None or shares <= 0:
        return None
    if shares < 5_000_000:
        return "ultra_low"
    if shares < 20_000_000:
        return "low"
    if shares < 100_000_000:
        return "medium"
    return "high"


def derive_market_cap_category(market_cap: Optional[float]) -> Optional[str]:
    """Mirror NewsMomentumOrchestrator._market_cap_category thresholds exactly,
    except: never fabricate a default when the input is unknown."""
    if market_cap is None or market_cap <= 0:
        return None
    if market_cap < 50_000_000:
        return "nano"
    if market_cap < 300_000_000:
        return "micro"
    if market_cap < 2_000_000_000:
        return "small"
    return "all"


class FinnhubProfileEnricher:
    """Cached Finnhub company-profile lookups with telemetry counters."""

    def __init__(self, *, client: Any = None, cache_ttl_seconds: float = PROFILE_CACHE_TTL_SECONDS):
        self._client = client
        self._client_resolved = client is not None
        self.cache_ttl_seconds = cache_ttl_seconds
        self._cache: dict[str, tuple[float, Optional[dict]]] = {}
        self._requests = 0
        self._successes = 0
        self._cache_hits = 0

    def _get_client(self) -> Any:
        if self._client_resolved:
            return self._client
        self._client_resolved = True
        key = os.getenv("FINNHUB_API_KEY", "").strip()
        if not key:
            try:
                from src.config import get_settings
                key = (getattr(get_settings(), "finnhub_api_key", "") or "").strip()
            except Exception:
                key = ""
        if not key:
            self._client = None
            return None
        try:
            import finnhub
            self._client = finnhub.Client(api_key=key)
        except Exception as exc:
            logger.debug("Finnhub profile enricher: client init failed: %s", exc)
            self._client = None
        return self._client

    def get_profile(self, ticker: str) -> Optional[dict]:
        """Return a normalized profile dict, or None when unavailable.

        Values are converted from Finnhub's millions to absolute units.
        Both hits and misses are cached for the TTL.
        """
        ticker = (ticker or "").strip().upper()
        if not ticker:
            return None
        now = time.time()
        cached = self._cache.get(ticker)
        if cached is not None and (now - cached[0]) < self.cache_ttl_seconds:
            self._cache_hits += 1
            return cached[1]

        client = self._get_client()
        if client is None:
            return None

        self._requests += 1
        try:
            raw = client.company_profile2(symbol=ticker) or {}
        except Exception as exc:
            logger.debug("Finnhub profile fetch failed for %s: %s", ticker, exc)
            raw = {}

        profile: Optional[dict] = None
        mcap_m = raw.get("marketCapitalization")
        shares_m = raw.get("shareOutstanding")
        if mcap_m or shares_m:
            profile = {
                # Finnhub reports both in MILLIONS.
                "market_cap": float(mcap_m) * 1e6 if mcap_m else None,
                "shares_outstanding": float(shares_m) * 1e6 if shares_m else None,
                "exchange": raw.get("exchange") or None,
                "country": raw.get("country") or None,
                "industry": raw.get("finnhubIndustry") or None,
            }
            self._successes += 1

        self._cache[ticker] = (now, profile)
        return profile

    def stats(self) -> dict[str, Any]:
        return {
            "requests": self._requests,
            "successes": self._successes,
            "cache_hits": self._cache_hits,
            "success_rate": round(self._successes / self._requests, 4) if self._requests else 0.0,
            "cached_tickers": len(self._cache),
        }


_default_enricher: Optional[FinnhubProfileEnricher] = None


def get_profile_enricher() -> FinnhubProfileEnricher:
    global _default_enricher
    if _default_enricher is None:
        _default_enricher = FinnhubProfileEnricher()
    return _default_enricher


def enrich_feature_row(
    row: dict, ticker: Optional[str], *, enricher: Optional[FinnhubProfileEnricher] = None
) -> Optional[dict]:
    """Fill missing market_cap_category / float_category in *row* in place.

    Note: shareOutstanding is an upper bound for float — acceptable for the
    category buckets, which are coarse. Existing values are never overwritten.
    Returns the profile (for record telemetry) or None.
    """
    enricher = enricher or get_profile_enricher()
    try:
        profile = enricher.get_profile(ticker or row.get("ticker") or "")
    except Exception as exc:
        logger.debug("Rocket feature enrichment failed for %s: %s", ticker, exc)
        return None
    if not profile:
        return None
    if row.get("market_cap_category") is None:
        row["market_cap_category"] = derive_market_cap_category(profile.get("market_cap"))
    if row.get("float_category") is None:
        row["float_category"] = derive_float_category(profile.get("shares_outstanding"))
    return profile
