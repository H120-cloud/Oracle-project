"""PR Newswire public-company news scraper."""

from __future__ import annotations

import asyncio
import logging
import os
import re
import time as _time
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import httpx
from bs4 import BeautifulSoup

from src.core.finviz_news import (
    FinvizNewsItem,
    FinvizNewsSummary,
    HEADERS as _BASE_HEADERS,
    _run_coro_blocking,
    _sort_by_ts_desc,
)
from src.core.news_ticker_extractor import extract_tickers as _extract_news_tickers

logger = logging.getLogger(__name__)

PRNEWSWIRE_PUBLIC_COMPANY_URL = "https://www.prnewswire.com/news-releases/all-public-company-news/"
PRNEWSWIRE_CACHE_TTL = float(os.environ.get("PRNEWSWIRE_CACHE_TTL_SECONDS", "20") or 20)
_ET = ZoneInfo("America/New_York")

HEADERS = {
    **_BASE_HEADERS,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

_LISTING_RE = re.compile(
    r"(?P<hour>\d{1,2}):(?P<minute>\d{2})\s+ET\s+(?P<body>.+)",
    re.IGNORECASE | re.DOTALL,
)
_BULLISH = [
    "award", "contract", "partnership", "launch", "expands", "growth",
    "acquire", "acquisition", "merger", "approval", "milestone", "revenue",
    "purchase", "investment", "commercial", "breakthrough", "patent",
]
_BEARISH = [
    "investigation", "lawsuit", "deadline", "fraud", "loss", "default",
    "bankruptcy", "recall", "downgrade", "delisting",
]


def _quick_sentiment(text: str) -> str:
    lower = text.lower()
    bullish = sum(1 for keyword in _BULLISH if keyword in lower)
    bearish = sum(1 for keyword in _BEARISH if keyword in lower)
    if bullish > bearish:
        return "bullish"
    if bearish > bullish:
        return "bearish"
    return "neutral"


def _parse_timestamp(hour: str, minute: str, *, now: Optional[datetime] = None) -> datetime:
    now_et = (now or datetime.now(timezone.utc)).astimezone(_ET)
    ts_et = now_et.replace(hour=int(hour), minute=int(minute), second=0, microsecond=0)
    if ts_et > now_et + timedelta(minutes=5):
        ts_et -= timedelta(days=1)
    return ts_et.astimezone(timezone.utc)


def extract_tickers(text: str, *, url: str = "") -> list[str]:
    return _extract_news_tickers(text or "", url=url, include_plain_parens=True)


class PRNewswireScraper:
    """Fetch PR Newswire public-company releases as Finviz-compatible items."""

    def __init__(self, timeout: float = 15):
        self.timeout = timeout
        self._cache: Optional[FinvizNewsSummary] = None
        self._cache_time: float = 0.0

    async def fetch_all(self, force_refresh: bool = False) -> FinvizNewsSummary:
        now = _time.time()
        if (not force_refresh) and self._cache and (now - self._cache_time) < PRNEWSWIRE_CACHE_TTL:
            return self._cache

        items: List[FinvizNewsItem] = []
        try:
            items = await self._parse_public_company_page()
            logger.info("PRNewswire: fetched %d public-company items", len(items))
        except Exception as exc:
            logger.error("PRNewswire fetch failed: %s", exc)

        summary = FinvizNewsSummary(
            news_items=_sort_by_ts_desc(items),
            blog_items=[],
            last_updated=datetime.now(timezone.utc),
        )
        self._cache = summary
        self._cache_time = now
        return summary

    def fetch_all_sync(self, force_refresh: bool = False) -> FinvizNewsSummary:
        return _run_coro_blocking(lambda: self.fetch_all(force_refresh=force_refresh))

    async def _fetch(self, url: str) -> str:
        async with httpx.AsyncClient(headers=HEADERS, timeout=self.timeout, follow_redirects=True) as client:
            response = await client.get(url)
            response.raise_for_status()
            return response.text

    async def _parse_public_company_page(self) -> List[FinvizNewsItem]:
        html = await self._fetch(PRNEWSWIRE_PUBLIC_COMPANY_URL)
        return parse_prnewswire_public_company_html(html, base_url=PRNEWSWIRE_PUBLIC_COMPANY_URL)


def parse_prnewswire_public_company_html(
    html: str,
    *,
    base_url: str = PRNEWSWIRE_PUBLIC_COMPANY_URL,
    now: Optional[datetime] = None,
) -> List[FinvizNewsItem]:
    soup = BeautifulSoup(html, "html.parser")
    items: List[FinvizNewsItem] = []

    for link in soup.find_all("a", href=True):
        href = link.get("href") or ""
        if "/news-releases/" not in href:
            continue

        text = " ".join(link.get_text(" ", strip=True).split())
        match = _LISTING_RE.match(text)
        if not match:
            continue

        timestamp = _parse_timestamp(match.group("hour"), match.group("minute"), now=now)
        url = urljoin(base_url, href)
        body = match.group("body").strip()
        tickers = extract_tickers(body, url=url)
        if not tickers:
            continue

        items.append(
            FinvizNewsItem(
                headline=body,
                source="PRNewswire",
                url=url,
                timestamp=timestamp,
                tickers=tickers,
                category="news",
                sentiment=_quick_sentiment(body),
            )
        )

    return items
