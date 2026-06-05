"""Stock Titan News Scraper — Real-time catalyst news via RSS feed from stocktitan.net"""
import asyncio
import html
import logging
import os
import re
import time as _time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import List, Optional
import xml.etree.ElementTree as ET

import httpx

from src.core.finviz_news import (
    FinvizNewsItem,
    FinvizNewsSummary,
    HEADERS as _BASE_HEADERS,
    _run_coro_blocking,
    _sort_by_ts_desc,
)
from src.core.news_ticker_extractor import extract_tickers

# StockTitan is a primary real-time catalyst source consumed by the ~20s news
# momentum scan loop. Its own cache TTL (default 20s) is decoupled from Finviz's
# 60s frontend cache so the scan never serves StockTitan news that's more than
# one scan cycle stale. Tune via STOCKTITAN_CACHE_TTL_SECONDS.
STOCKTITAN_CACHE_TTL = float(os.environ.get("STOCKTITAN_CACHE_TTL_SECONDS", "20") or 20)

logger = logging.getLogger(__name__)

# Reuse the shared browser-UA but advertise RSS as preferred for this scraper
HEADERS = {**_BASE_HEADERS, "Accept": "application/rss+xml, application/xml, text/xml, */*"}

# RSS feed — latest 100 news items with tickers embedded in title & URL
STOCKTITAN_RSS_URL = "https://www.stocktitan.net/rss"

# Simple sentiment keywords
_BULLISH = [
    "partnership", "contract", "awarded", "launch", "expand", "acquisition",
    "growth", "revenue growth", "beat", "surpass", "record", "breakthrough",
    "approval", "patent", "milestone", "strategic", "investment",
]
_BEARISH = [
    "lawsuit", "decline", "loss", "investigation", "recall", "warning",
    "downgrade", "default", "bankruptcy", "layoff", "cut", "delay",
]


def _clean_description(description: str) -> str:
    """Convert RSS descriptions into plain text for ticker/classifier use."""
    text = html.unescape(description or "")
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _quick_sentiment(headline: str) -> str:
    h = headline.lower()
    bull = sum(1 for kw in _BULLISH if kw in h)
    bear = sum(1 for kw in _BEARISH if kw in h)
    if bull > bear:
        return "bullish"
    if bear > bull:
        return "bearish"
    return "neutral"


class StockTitanScraper:
    """Fetch news from stocktitan.net RSS feed and return FinvizNewsItem-compatible objects."""

    def __init__(self):
        self._cache: Optional[FinvizNewsSummary] = None
        self._cache_time: float = 0

    async def fetch_all(self, force_refresh: bool = False) -> FinvizNewsSummary:
        """Fetch and parse Stock Titan RSS feed. Returns FinvizNewsSummary for compatibility."""
        now = _time.time()
        if (not force_refresh) and self._cache and (now - self._cache_time) < STOCKTITAN_CACHE_TTL:
            return self._cache

        items: List[FinvizNewsItem] = []
        try:
            items = await self._parse_rss()
            logger.info("StockTitan: fetched %d items from RSS feed", len(items))
        except Exception as e:
            logger.error("StockTitan RSS fetch failed: %s", e)

        summary = FinvizNewsSummary(
            news_items=_sort_by_ts_desc(items),
            blog_items=[],
            last_updated=datetime.now(timezone.utc),
        )
        self._cache = summary
        self._cache_time = now
        return summary

    def fetch_all_sync(self, force_refresh: bool = False) -> FinvizNewsSummary:
        """Synchronous wrapper — safe from inside an event loop too."""
        return _run_coro_blocking(lambda: self.fetch_all(force_refresh=force_refresh))

    @staticmethod
    async def _fetch_with_retry(url: str, max_retries: int = 3) -> httpx.Response:
        """Fetch URL with exponential backoff on retryable errors."""
        for attempt in range(1, max_retries + 1):
            try:
                async with httpx.AsyncClient(headers=HEADERS, timeout=15, follow_redirects=True) as client:
                    resp = await client.get(url)
                if resp.status_code < 500 and resp.status_code != 429:
                    return resp
                if resp.status_code in (503, 504, 429):
                    if attempt < max_retries:
                        wait = 2 ** (attempt - 1)
                        logger.warning("StockTitan fetch got %d, retrying in %ds (attempt %d/%d)", resp.status_code, wait, attempt, max_retries)
                        await asyncio.sleep(wait)
                        continue
                resp.raise_for_status()
                return resp
            except (httpx.TimeoutException, httpx.ConnectError) as exc:
                if attempt < max_retries:
                    wait = 2 ** (attempt - 1)
                    logger.warning("StockTitan fetch error: %s, retrying in %ds (attempt %d/%d)", exc, wait, attempt, max_retries)
                    await asyncio.sleep(wait)
                else:
                    raise
        raise httpx.HTTPStatusError(
            f"Max retries exceeded for {url}",
            request=None, response=None,
        )

    async def _parse_rss(self) -> List[FinvizNewsItem]:
        """Parse the Stock Titan RSS feed for ticker + headline pairs."""
        resp = await self._fetch_with_retry(STOCKTITAN_RSS_URL)
        resp.raise_for_status()

        root = ET.fromstring(resp.text)
        channel = root.find("channel")
        if channel is None:
            return []

        items: List[FinvizNewsItem] = []

        for item_el in channel.findall("item"):
            title = (item_el.findtext("title") or "").strip()
            link = (item_el.findtext("link") or "").strip()
            description = _clean_description((item_el.findtext("description") or "").strip())
            pub_date_str = item_el.findtext("pubDate")

            if not title or not link:
                continue

            tickers = extract_tickers(title, description, url=link, include_plain_parens=True)
            if not tickers:
                continue

            # Clean headline: remove " | TICKER Stock News" suffix
            headline = re.sub(r"\s*\|\s*[A-Z]{1,5}\s+Stock\s+News\s*$", "", title, flags=re.IGNORECASE).strip()
            if len(headline) < 15:
                continue

            # Parse publication date. Leave as None (NOT now) if missing or
            # unparseable — downstream freshness filters drop undated items,
            # whereas defaulting to "now" would surface old news as fresh.
            ts = None
            if pub_date_str:
                try:
                    ts = parsedate_to_datetime(pub_date_str)
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                except Exception:
                    ts = None

            sentiment = _quick_sentiment(f"{headline} {description}")

            items.append(FinvizNewsItem(
                headline=headline,
                source="StockTitan",
                url=link,
                timestamp=ts,
                tickers=tickers,
                category="news",
                sentiment=sentiment,
                description=description,
            ))

        return items
