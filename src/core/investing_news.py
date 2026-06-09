"""Investing.com stock-market news scraper (RSS).

The HTML page (m.uk.investing.com/news/stock-market-news) sits behind a
Cloudflare bot challenge and returns HTTP 403, so it cannot be scraped directly.
The RSS feed for the same "Stock Market News" category is served without the
challenge, so we ingest that instead.

Investing.com headlines usually name the company rather than the symbol
(e.g. "Why is Zevra Therapeutics stock surging today?"), so we resolve the
leading company name to a US ticker and only emit items where a ticker is found.
"""

from __future__ import annotations

import logging
import os
import re
import time as _time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Callable, List, Optional

import httpx

from src.core.finviz_news import (
    FinvizNewsItem,
    FinvizNewsSummary,
    HEADERS as _BASE_HEADERS,
    _run_coro_blocking,
    _sort_by_ts_desc,
)
from src.core.news_ticker_extractor import extract_tickers as _extract_news_tickers
from src.core.company_name_resolver import resolve_company_ticker

logger = logging.getLogger(__name__)

# news_25 = Investing.com "Stock Market News" category (RSS form of the page
# the user linked). Overridable via env for other categories.
INVESTING_FEED_URL = os.environ.get(
    "INVESTING_RSS_URL", "https://www.investing.com/rss/news_25.rss"
).strip()
INVESTING_CACHE_TTL = float(os.environ.get("INVESTING_CACHE_TTL_SECONDS", "60") or 60)

HEADERS = {
    **_BASE_HEADERS,
    "Accept": "application/rss+xml,application/xml,text/xml;q=0.9,*/*;q=0.8",
}

# "Why is <Company> stock surging" / "<Company> shares jump" → capture <Company>.
# \b(?:stock|shares)\b deliberately does NOT match "shareholders".
_NAME_RE = re.compile(
    r"^(?:why\s+(?:is|are)\s+)?(?P<name>.+?)\s+(?:stock|shares)\b",
    re.IGNORECASE,
)

_BULLISH = [
    "surge", "surges", "surging", "jumps", "soars", "rallies", "rises", "gains",
    "beat", "approval", "approved", "wins", "awarded", "contract", "partnership",
    "acquisition", "merger", "upgrade", "record", "milestone", "raises guidance",
]
_BEARISH = [
    "plunge", "plunges", "plunging", "falls", "drops", "slumps", "sinks", "tumbles",
    "downgrade", "lawsuit", "investigation", "warning", "loss", "bankruptcy",
    "delisting", "cuts guidance", "misses",
]


def _quick_sentiment(text: str) -> str:
    lower = (text or "").lower()
    bullish = sum(1 for kw in _BULLISH if kw in lower)
    bearish = sum(1 for kw in _BEARISH if kw in lower)
    if bullish > bearish:
        return "bullish"
    if bearish > bullish:
        return "bearish"
    return "neutral"


def _extract_company_name(title: str) -> Optional[str]:
    """Best-effort company name from a '<Company> stock/shares ...' headline."""
    match = _NAME_RE.match(title or "")
    if not match:
        return None
    name = match.group("name").strip()
    name = re.sub(r"'s$", "", name).strip()  # "Apple's" -> "Apple"
    return name or None


def _parse_pubdate(text: str, *, now: Optional[datetime] = None) -> Optional[datetime]:
    text = (text or "").strip()
    if not text:
        return None
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%a, %d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S GMT",
    ):
        try:
            dt = datetime.strptime(text, fmt)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def extract_tickers(text: str, *, url: str = "") -> list[str]:
    return _extract_news_tickers(text or "", url=url, include_plain_parens=True)


def parse_investing_rss(
    xml_text: str,
    *,
    now: Optional[datetime] = None,
    resolve: Callable[[str], Optional[str]] = resolve_company_ticker,
) -> List[FinvizNewsItem]:
    items: List[FinvizNewsItem] = []
    try:
        root = ET.fromstring(xml_text or "")
    except Exception:
        return items  # garbage/empty feed — healthy empty, never raise

    for node in root.iter("item"):
        title = (node.findtext("title") or "").strip()
        if not title:
            continue
        link = (node.findtext("link") or "").strip()
        ts = _parse_pubdate(node.findtext("pubDate"), now=now)

        # 1) explicit symbol in the headline ($TICK / (NASDAQ:TICK))
        tickers = extract_tickers(title, url=link)
        # 2) fall back to resolving the leading company name to a US ticker
        if not tickers:
            name = _extract_company_name(title)
            if name:
                try:
                    resolved = resolve(name)
                except Exception:
                    resolved = None
                if resolved:
                    tickers = [resolved]
        if not tickers:
            continue  # no US ticker — drop (keeps the feed relevant)

        items.append(
            FinvizNewsItem(
                headline=title,
                source="Investing",
                url=link or INVESTING_FEED_URL,
                timestamp=ts,
                timestamp_confidence="HIGH" if ts else "LOW",
                tickers=tickers,
                category="news",
                sentiment=_quick_sentiment(title),
            )
        )
    return items


class InvestingNewsScraper:
    """Fetch Investing.com stock-market RSS as Finviz-compatible items."""

    def __init__(self, timeout: float = 15):
        self.timeout = timeout
        self._cache: Optional[FinvizNewsSummary] = None
        self._cache_time: float = 0.0

    async def fetch_all(self, force_refresh: bool = False) -> FinvizNewsSummary:
        now = _time.time()
        if (not force_refresh) and self._cache and (now - self._cache_time) < INVESTING_CACHE_TTL:
            return self._cache

        items: List[FinvizNewsItem] = []
        try:
            xml_text = await self._fetch(INVESTING_FEED_URL)
            items = parse_investing_rss(xml_text)
            logger.info("Investing: fetched %d tickered items", len(items))
        except Exception as exc:
            # Log and return empty — a transient feed/network error must not crash
            # the scan loop (the source-health tracker records the empty fetch).
            logger.warning("Investing fetch failed: %s", exc)

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
