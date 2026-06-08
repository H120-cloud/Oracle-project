"""
News API routes — Finviz + Stock Titan news endpoints.

Endpoints:
- GET /news/finviz — fetch all Finviz news (v=3 + v=6)
- GET /news/finviz/news — news articles only (v=3)
- GET /news/finviz/blogs — blogs/press releases only (v=6)
- GET /news/stocktitan — fetch Stock Titan news (RSS feed)
- GET /news/all — combined Finviz + Stock Titan news feed (sorted newest-first)

All endpoints accept `?force_refresh=true` to bypass the in-process cache.
"""

import logging
import asyncio
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Query
from src.core.finviz_news import FinvizNewsScraper
from src.core.stocktitan_news import StockTitanScraper
from src.services.market_data import get_market_data_provider

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/news", tags=["news"])

# Shared scraper instances — both maintain their own in-process cache
_scraper = FinvizNewsScraper()
_stocktitan_scraper = StockTitanScraper()
_market_data_provider = get_market_data_provider()


def _ts_key(item) -> datetime:
    """Sort key: newest first, undated items sink to the bottom."""
    return item.timestamp or datetime.min.replace(tzinfo=timezone.utc)


def _run_live_quote(ticker: str):
    return _market_data_provider.get_live_quote(ticker.upper())


@router.get("/finviz")
async def get_finviz_news(force_refresh: bool = Query(False)):
    """Fetch all Finviz news (articles + blogs/press releases)."""
    try:
        summary = await _scraper.fetch_all(force_refresh=force_refresh)
        return summary.to_dict()
    except Exception as exc:
        logger.error("Failed to fetch Finviz news: %s", exc)
        raise HTTPException(status_code=503, detail=f"News service unavailable: {exc}")


@router.get("/finviz/news")
async def get_finviz_articles():
    """Fetch Finviz news articles only (v=3)."""
    try:
        items = await _scraper._fetch_news()
        return {"news": [n.to_dict() for n in items], "count": len(items)}
    except Exception as exc:
        logger.error("Failed to fetch news: %s", exc)
        raise HTTPException(status_code=503, detail=f"News service unavailable: {exc}")


@router.get("/finviz/blogs")
async def get_finviz_blogs():
    """Fetch Finviz blogs/press releases only (v=6)."""
    try:
        items = await _scraper._fetch_blogs()
        return {"blogs": [b.to_dict() for b in items], "count": len(items)}
    except Exception as exc:
        logger.error("Failed to fetch blogs: %s", exc)
        raise HTTPException(status_code=503, detail=f"News service unavailable: {exc}")


@router.get("/stocktitan")
async def get_stocktitan_news(force_refresh: bool = Query(False)):
    """Fetch Stock Titan news (RSS feed)."""
    try:
        summary = await _stocktitan_scraper.fetch_all(force_refresh=force_refresh)
        return {
            "news": [n.to_dict() for n in summary.news_items],
            "count": len(summary.news_items),
            "source": "stocktitan",
            "last_updated": summary.last_updated.isoformat() if summary.last_updated else None,
        }
    except Exception as exc:
        logger.error("Failed to fetch Stock Titan news: %s", exc)
        raise HTTPException(status_code=503, detail=f"News service unavailable: {exc}")


@router.get("/all")
async def get_all_news(force_refresh: bool = Query(False)):
    """Combined news feed from all sources (Finviz + Stock Titan), newest-first."""
    all_news = []
    sources = {}
    last_updates = []

    try:
        finviz = await _scraper.fetch_all(force_refresh=force_refresh)
        finviz_items = finviz.news_items + finviz.blog_items
        all_news.extend(finviz_items)
        sources["finviz"] = len(finviz_items)
        if finviz.last_updated:
            last_updates.append(finviz.last_updated)
    except Exception as exc:
        logger.error("Finviz fetch failed in /all: %s", exc)
        sources["finviz"] = 0

    try:
        st = await _stocktitan_scraper.fetch_all(force_refresh=force_refresh)
        all_news.extend(st.news_items)
        sources["stocktitan"] = len(st.news_items)
        if st.last_updated:
            last_updates.append(st.last_updated)
    except Exception as exc:
        logger.error("StockTitan fetch failed in /all: %s", exc)
        sources["stocktitan"] = 0

    # Deduplicate by headline (case-insensitive)
    seen = set()
    deduped = []
    for item in all_news:
        key = item.headline.strip().lower()
        if key and key not in seen:
            seen.add(key)
            deduped.append(item)

    # Newest first — critical so the UI doesn't show stale Finviz items
    # ahead of more-recent StockTitan ones (or vice versa).
    deduped.sort(key=_ts_key, reverse=True)

    return {
        "news": [n.to_dict() for n in deduped],
        "count": len(deduped),
        "sources": sources,
        # Reflect the oldest underlying scrape so the UI can tell when data is stale
        "last_updated": min(last_updates).isoformat() if last_updates else None,
    }


@router.get("/quote/{ticker}")
async def get_news_quote(ticker: str):
    """Strategic quote endpoint for news surfaces without importing old analysis routes."""
    try:
        quote = await asyncio.wait_for(
            asyncio.to_thread(_run_live_quote, ticker),
            timeout=30.0,
        )
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Live quote timed out; data provider is slow.")
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Live quote failed: {exc}")
    if quote is None:
        raise HTTPException(status_code=503, detail=f"Live quote unavailable for {ticker.upper()}")
    return quote
