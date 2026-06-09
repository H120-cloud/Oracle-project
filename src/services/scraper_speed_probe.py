"""On-demand news-scraper speed probe for the Admin Diagnostics dashboard.

Fetches from every news source concurrently with ``force_refresh=True`` (so we
measure the real scrape, not a cache hit), times each one, and reports per-source
duration / item-count / errors so an operator can see which source is the
bottleneck. Read-only: it pulls from external feeds and writes nothing.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)

# (display name, zero-arg coroutine factory). Built lazily so importing this
# module stays cheap and so tests can monkeypatch the whole source list.
SourceFactory = Callable[[], Awaitable[Any]]


def _build_sources() -> list[tuple[str, SourceFactory]]:
    from src.core.finviz_news import FinvizNewsScraper
    from src.core.stocktitan_news import StockTitanScraper
    from src.core.prnewswire_news import PRNewswireScraper
    from src.core.sharecast_news import SharecastScraper
    from src.core.wire_news import WireNewsScraper
    from src.core.investing_news import InvestingNewsScraper

    finviz = FinvizNewsScraper()
    stocktitan = StockTitanScraper()
    prnewswire = PRNewswireScraper()
    sharecast = SharecastScraper()
    wire = WireNewsScraper()
    investing = InvestingNewsScraper()

    return [
        ("Finviz", lambda: finviz.fetch_all(force_refresh=True)),
        ("StockTitan", lambda: stocktitan.fetch_all(force_refresh=True)),
        ("PRNewswire", lambda: prnewswire.fetch_all(force_refresh=True)),
        ("Sharecast", lambda: sharecast.fetch_all(force_refresh=True)),
        ("WireNews", lambda: wire.fetch_all(force_refresh=True)),
        ("Investing", lambda: investing.fetch_all(force_refresh=True)),
    ]


async def _probe_one(name: str, make_coro: SourceFactory, timeout: float) -> dict[str, Any]:
    start = time.perf_counter()
    try:
        summary = await asyncio.wait_for(make_coro(), timeout=timeout)
        elapsed = time.perf_counter() - start
        news = len(getattr(summary, "news_items", None) or [])
        blogs = len(getattr(summary, "blog_items", None) or [])
        return {
            "source": name, "ok": True, "duration_seconds": round(elapsed, 3),
            "news_items": news, "blog_items": blogs, "total_items": news + blogs,
            "error": None,
        }
    except asyncio.TimeoutError:
        return {
            "source": name, "ok": False, "duration_seconds": round(time.perf_counter() - start, 3),
            "news_items": 0, "blog_items": 0, "total_items": 0,
            "error": f"timed out after {timeout:.0f}s",
        }
    except Exception as exc:  # network error, parse error, missing dep, etc.
        logger.warning("Scraper speed probe: %s failed: %s", name, exc)
        return {
            "source": name, "ok": False, "duration_seconds": round(time.perf_counter() - start, 3),
            "news_items": 0, "blog_items": 0, "total_items": 0,
            "error": f"{type(exc).__name__}: {exc}",
        }


async def probe_scraper_speeds(*, timeout: float = 15.0) -> dict[str, Any]:
    """Probe every news source concurrently; return per-source timing + a summary.

    Total wall time ≈ the slowest source (probes run in parallel).
    """
    sources = _build_sources()
    results = await asyncio.gather(*[_probe_one(n, f, timeout) for n, f in sources])
    # Slowest first — the operator wants the bottleneck at the top.
    results.sort(key=lambda r: r["duration_seconds"], reverse=True)

    ok = [r for r in results if r["ok"]]
    slowest = results[0] if results else None
    return {
        "ran_at": datetime.now(timezone.utc).isoformat(),
        "timeout_seconds": timeout,
        "sources_tested": len(results),
        "sources_ok": len(ok),
        "slowest_source": slowest["source"] if slowest else None,
        "slowest_seconds": slowest["duration_seconds"] if slowest else None,
        "total_items": sum(r["total_items"] for r in results),
        "items": results,
    }
