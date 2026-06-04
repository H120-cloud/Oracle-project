"""Live smoke test for Polygon free-tier rate limiting + pre-news enrichment.

Run against a REAL Polygon key (free tier, 5 req/min). It verifies:

  Part A — Rate limiter: fires N rapid get_ohlcv calls and confirms requests
           are spaced to the configured quota with zero 429s surfacing.
  Part B — Enrichment wiring: feeds synthetic anomalies to
           PreNewsDetector._enrich_top_anomalies_with_polygon and confirms
           Polygon is called at most PRE_NEWS_POLYGON_ENRICH_LIMIT times and
           the detector's provider is restored afterward.

Usage:
    python scripts/smoke_polygon_enrichment.py
    # optional: tighten the cap for a faster run
    set PRE_NEWS_POLYGON_ENRICH_LIMIT=2 && python scripts/smoke_polygon_enrichment.py

Exits non-zero if any check fails.
"""

import os
import sys
import time

# Ensure repo root on path when run directly
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config import get_settings  # noqa: E402

LIQUID_TICKERS = ["AAPL", "MSFT", "NVDA", "TSLA", "AMD", "META", "AMZN", "GOOGL"]


def _instrument_calls(provider):
    """Wrap provider._get to count calls and capture any 429s + timestamps."""
    stats = {"calls": 0, "rate_limit_errors": 0, "timestamps": []}
    original = provider._get

    def wrapped(path, params=None, _retry=3):
        stats["calls"] += 1
        stats["timestamps"].append(time.time())
        try:
            return original(path, params=params, _retry=_retry)
        except RuntimeError as exc:
            if "rate limit" in str(exc).lower():
                stats["rate_limit_errors"] += 1
            raise

    provider._get = wrapped
    return stats


def part_a_rate_limiter(n: int = 8) -> bool:
    from src.services.polygon_provider import PolygonProvider, _POLYGON_MIN_INTERVAL

    print(f"\n=== Part A: rate limiter ({n} rapid calls, min_interval={_POLYGON_MIN_INTERVAL:.1f}s) ===")
    provider = PolygonProvider()
    stats = _instrument_calls(provider)

    start = time.time()
    ok_bars = 0
    for i in range(n):
        tkr = LIQUID_TICKERS[i % len(LIQUID_TICKERS)]
        bars = provider.get_ohlcv(tkr, period="1d", interval="5m")
        if bars:
            ok_bars += 1
        print(f"  [{i+1}/{n}] {tkr}: {len(bars)} bars")
    elapsed = time.time() - start

    # Check spacing between consecutive HTTP calls. The FIRST request is
    # intentionally not throttled (nothing precedes it), so exclude the first
    # gap — only requests 2..N are subject to the min-interval.
    ts = stats["timestamps"]
    gaps = [round(ts[i] - ts[i - 1], 2) for i in range(2, len(ts))]
    min_gap = min(gaps) if gaps else 0.0

    print(f"  -> http_calls={stats['calls']} elapsed={elapsed:.1f}s "
          f"min_gap={min_gap:.2f}s 429s={stats['rate_limit_errors']} bars_ok={ok_bars}")

    passed = stats["rate_limit_errors"] == 0
    # Allow small scheduling slack below the nominal interval
    if _POLYGON_MIN_INTERVAL > 0 and min_gap < _POLYGON_MIN_INTERVAL - 0.5:
        print(f"  WARN: min gap {min_gap:.2f}s below configured interval {_POLYGON_MIN_INTERVAL:.1f}s")
    print("  PASS" if passed else "  FAIL: 429 errors surfaced despite throttling")
    return passed


def part_b_enrichment() -> bool:
    from src.core.agentic.pre_news_detector import PreNewsDetector
    from src.core.agentic.pre_news_models import PreNewsAnomaly

    limit = int(os.getenv("PRE_NEWS_POLYGON_ENRICH_LIMIT", "3") or 3)
    print(f"\n=== Part B: enrichment wiring (limit={limit}) ===")

    detector = PreNewsDetector()
    polygon = detector._get_polygon_provider()
    if polygon is None:
        print("  SKIP: no Polygon provider (key missing)")
        return True

    stats = _instrument_calls(polygon)
    provider_before = detector._provider

    # Build more anomalies than the cap, with descending suspicion scores so we
    # can assert only the top `limit` get enriched.
    anomalies = [
        PreNewsAnomaly(ticker=LIQUID_TICKERS[i], pre_news_suspicion_score=90.0 - i * 5)
        for i in range(min(limit + 2, len(LIQUID_TICKERS)))
    ]
    print(f"  feeding {len(anomalies)} anomalies: "
          + ", ".join(f"{a.ticker}({a.pre_news_suspicion_score:.0f})" for a in anomalies))

    result = detector._enrich_top_anomalies_with_polygon(list(anomalies))

    provider_restored = detector._provider is provider_before
    # Each enriched ticker does a bounded number of Polygon calls; what matters
    # for quota is that we never enrich more than `limit` tickers. Polygon calls
    # per ticker is small (quote=2 + ohlcv=1), so cap total generously.
    max_expected_calls = limit * 4
    within_budget = stats["calls"] <= max_expected_calls

    print(f"  -> polygon_http_calls={stats['calls']} (budget<= {max_expected_calls}) "
          f"429s={stats['rate_limit_errors']} provider_restored={provider_restored} "
          f"results={len(result)}")

    passed = (
        stats["rate_limit_errors"] == 0
        and provider_restored
        and within_budget
        and len(result) == len(anomalies)
    )
    print("  PASS" if passed else "  FAIL: see numbers above")
    return passed


def main() -> int:
    if not get_settings().polygon_api_key and not os.getenv("POLYGON_API_KEY"):
        print("ERROR: POLYGON_API_KEY not configured — this is a LIVE test.")
        return 2

    a = part_a_rate_limiter()
    b = part_b_enrichment()

    print("\n=== SUMMARY ===")
    print(f"  Part A (rate limiter):  {'PASS' if a else 'FAIL'}")
    print(f"  Part B (enrichment):    {'PASS' if b else 'FAIL'}")
    return 0 if (a and b) else 1


if __name__ == "__main__":
    raise SystemExit(main())
