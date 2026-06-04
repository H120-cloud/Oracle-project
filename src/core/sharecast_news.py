"""Sharecast press-note scraper.

Sharecast's press-note pages are useful as supplemental discovery, but many
items expose company names without exchange tickers. This scraper only emits
items when a ticker can be extracted with high confidence.
"""

from __future__ import annotations

import logging
import os
import re
import time as _time
from datetime import datetime, timezone
from typing import List, Optional
from urllib.parse import urljoin

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

SHARECAST_PRESS_NOTE_URL = "https://www.sharecast.com/amp/press_note/market_reports/"
SHARECAST_CACHE_TTL = float(os.environ.get("SHARECAST_CACHE_TTL_SECONDS", "60") or 60)

HEADERS = {
    **_BASE_HEADERS,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

_DATE_RE = re.compile(r"^(?P<day>\d{1,2})\s+(?P<month>[A-Za-z]{3,9})$", re.IGNORECASE)
_MONTHS = {
    "jan": 1, "january": 1,
    "feb": 2, "february": 2,
    "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "may": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}
_BULLISH = [
    "award", "contract", "partnership", "launch", "acquisition", "merger",
    "approval", "agreement", "revenue", "profit", "upgrade", "buyback",
    "dividend", "guidance", "milestone",
]
_BEARISH = [
    "warning", "downgrade", "investigation", "lawsuit", "loss", "delisting",
    "bankruptcy", "suspension",
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


def _parse_date(text: str, *, now: Optional[datetime] = None) -> Optional[datetime]:
    match = _DATE_RE.match((text or "").strip())
    if not match:
        return None
    month = _MONTHS.get(match.group("month").lower())
    if month is None:
        return None
    base = now or datetime.now(timezone.utc)
    dt = datetime(base.year, month, int(match.group("day")), tzinfo=timezone.utc)
    if dt > base:
        dt = dt.replace(year=base.year - 1)
    return dt


def extract_sharecast_tickers(text: str) -> list[str]:
    return _extract_news_tickers(text or "", include_plain_parens=True)


class SharecastScraper:
    """Fetch Sharecast press-note releases as Finviz-compatible items."""

    def __init__(self, timeout: float = 15):
        self.timeout = timeout
        self._cache: Optional[FinvizNewsSummary] = None
        self._cache_time: float = 0.0

    async def fetch_all(self, force_refresh: bool = False) -> FinvizNewsSummary:
        now = _time.time()
        if (not force_refresh) and self._cache and (now - self._cache_time) < SHARECAST_CACHE_TTL:
            return self._cache

        items: List[FinvizNewsItem] = []
        try:
            html = await self._fetch(SHARECAST_PRESS_NOTE_URL)
            items = parse_sharecast_press_note_html(html, base_url=SHARECAST_PRESS_NOTE_URL)
            logger.info("Sharecast: fetched %d tickered press-note items", len(items))
        except Exception as exc:
            logger.error("Sharecast fetch failed: %s", exc)

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


def parse_sharecast_press_note_html(
    html: str,
    *,
    base_url: str = SHARECAST_PRESS_NOTE_URL,
    now: Optional[datetime] = None,
) -> List[FinvizNewsItem]:
    soup = BeautifulSoup(html, "html.parser")
    items: List[FinvizNewsItem] = []
    current_date: Optional[datetime] = None

    for node in soup.find_all(["a", "h6", "h5", "p", "span", "time"]):
        text = " ".join(node.get_text(" ", strip=True).split())
        if not text:
            continue
        parsed_date = _parse_date(text, now=now)
        if parsed_date is not None:
            current_date = parsed_date
            continue

        href = node.get("href") if node.name == "a" else None
        if href and "/press_note/" not in href:
            continue

        tickers = extract_sharecast_tickers(text)
        if not tickers:
            continue

        items.append(
            FinvizNewsItem(
                headline=text,
                source="Sharecast",
                url=urljoin(base_url, href) if href else base_url,
                timestamp=current_date,
                tickers=tickers,
                category="news",
                sentiment=_quick_sentiment(text),
            )
        )

    return items
