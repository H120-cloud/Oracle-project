"""Supplemental press-wire news scrapers.

These feeds are intentionally conservative: emit only releases with explicit
exchange/ticker text so source expansion does not create fake symbols.
"""

from __future__ import annotations

import logging
import os
import re
import time as _time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Iterable, List, Optional
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
from src.core.news_ticker_extractor import extract_tickers

logger = logging.getLogger(__name__)

WIRE_CACHE_TTL = float(os.environ.get("WIRE_NEWS_CACHE_TTL_SECONDS", "60") or 60)

HEADERS = {
    **_BASE_HEADERS,
    "Accept": "application/rss+xml,application/xml,text/xml,text/html;q=0.9,*/*;q=0.8",
}

DEFAULT_WIRE_FEEDS = {
    "GlobeNewswire": [
        "https://rss.globenewswire.com/GlobeNewswire",
        "https://www.globenewswire.com/RssFeed/orgclass/1/feedTitle/GlobeNewswire%20-%20News%20about%20Public%20Companies",
    ],
    "BusinessWire": [
        "https://www.businesswire.com/portal/site/home/news/rss/",
    ],
    "Accesswire": [
        "https://www.accessnewswire.com/newsroom",
    ],
    "Newsfile": [
        "https://www.newsfilecorp.com/news/",
        "https://www.newsfilecorp.com/rss/news.xml",
    ],
}

_DATE_ATTRS = ("pubdate", "published", "updated", "dc:date", "time")
_DATE_TEXT_RE = re.compile(
    r"(?P<month>Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|"
    r"Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
    r"\s+(?P<day>\d{1,2}),?\s+(?P<year>\d{4})",
    re.IGNORECASE,
)
_TIME_TEXT_RE = re.compile(r"\b\d{1,2}:\d{2}(?::\d{2})?\b|\b\d{1,2}\s*(?:AM|PM)\b", re.IGNORECASE)


def _feed_urls_for(source: str) -> list[str]:
    env_key = f"{source.upper()}_FEED_URLS"
    raw = os.environ.get(env_key, "").strip()
    if raw:
        return [url.strip() for url in raw.split(",") if url.strip()]
    return DEFAULT_WIRE_FEEDS.get(source, [])


def _parse_timestamp(text: str) -> Optional[datetime]:
    text = (text or "").strip()
    if not text:
        return None
    try:
        dt = parsedate_to_datetime(text)
        return dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        logger.debug("Wire news timestamp parse failed for: %s", text)
    match = _DATE_TEXT_RE.search(text)
    if not match:
        return None
    try:
        dt = datetime.strptime(
            f"{match.group('month')} {match.group('day')} {match.group('year')}",
            "%b %d %Y",
        )
    except ValueError:
        try:
            dt = datetime.strptime(
                f"{match.group('month')} {match.group('day')} {match.group('year')}",
                "%B %d %Y",
            )
        except ValueError:
            return None
    return dt.replace(tzinfo=timezone.utc)


def _parse_timestamp_with_confidence(text: str) -> tuple[Optional[datetime], str]:
    parsed = _parse_timestamp(text)
    if parsed is None:
        return None, "UNKNOWN"
    return parsed, "HIGH" if _TIME_TEXT_RE.search(text or "") else "LOW"


def _quick_sentiment(text: str) -> str:
    lower = text.lower()
    bullish = any(k in lower for k in ("award", "contract", "approval", "partnership", "acquisition", "launch", "agreement"))
    bearish = any(k in lower for k in ("offering", "investigation", "lawsuit", "delisting", "bankruptcy", "downgrade"))
    if bullish and not bearish:
        return "bullish"
    if bearish and not bullish:
        return "bearish"
    return "neutral"


def _item_text(item) -> str:
    parts: list[str] = []
    for tag in ("title", "description", "summary", "content:encoded"):
        found = item.find(tag)
        if found:
            parts.append(found.get_text(" ", strip=True))
    return " ".join(" ".join(parts).split())


def _item_timestamp(item) -> Optional[datetime]:
    timestamp, _confidence = _item_timestamp_with_confidence(item)
    return timestamp


def _item_timestamp_with_confidence(item) -> tuple[Optional[datetime], str]:
    for tag in _DATE_ATTRS:
        found = item.find(tag)
        if found:
            parsed, confidence = _parse_timestamp_with_confidence(found.get_text(" ", strip=True))
            if parsed:
                return parsed, confidence
    return None, "UNKNOWN"


def _item_url(item, base_url: str) -> str:
    link = item.find("link")
    if link:
        href = link.get("href") or link.get_text(" ", strip=True)
        if href:
            return urljoin(base_url, href.strip())
    guid = item.find("guid")
    if guid:
        href = guid.get_text(" ", strip=True)
        if href.startswith("http"):
            return href
    return base_url


def parse_wire_feed_html(
    html: str,
    *,
    source: str,
    base_url: str,
) -> List[FinvizNewsItem]:
    soup = BeautifulSoup(html, "xml")
    nodes = soup.find_all("item") or soup.find_all("entry")
    if not nodes:
        soup = BeautifulSoup(html, "html.parser")
        nodes = soup.find_all(["article", "li", "a"])

    items: list[FinvizNewsItem] = []
    for node in nodes:
        text = _item_text(node) if node.name in {"item", "entry"} else " ".join(node.get_text(" ", strip=True).split())
        if not text:
            continue
        item_url = _item_url(node, base_url)
        tickers = extract_tickers(text, url=item_url, include_plain_parens=True)
        if not tickers:
            continue
        if node.name in {"item", "entry"}:
            timestamp, timestamp_confidence = _item_timestamp_with_confidence(node)
            if timestamp is None:
                timestamp, timestamp_confidence = _parse_timestamp_with_confidence(text)
        else:
            timestamp, timestamp_confidence = _parse_timestamp_with_confidence(text)
        items.append(
            FinvizNewsItem(
                headline=text[:400],
                source=source,
                url=item_url,
                timestamp=timestamp,
                timestamp_confidence=timestamp_confidence,
                tickers=tickers,
                category="news",
                sentiment=_quick_sentiment(text),
                description=text,
            )
        )
    return items


class WireNewsScraper:
    """Fetch several supplemental press wires as Finviz-compatible news."""

    def __init__(self, sources: Optional[Iterable[str]] = None, timeout: float = 15):
        self.sources = list(sources or DEFAULT_WIRE_FEEDS.keys())
        self.timeout = timeout
        self._cache: Optional[FinvizNewsSummary] = None
        self._cache_time: float = 0.0

    async def fetch_all(self, force_refresh: bool = False) -> FinvizNewsSummary:
        now = _time.time()
        if (not force_refresh) and self._cache and (now - self._cache_time) < WIRE_CACHE_TTL:
            return self._cache

        items: list[FinvizNewsItem] = []
        failed_sources: dict[str, int] = {}
        async with httpx.AsyncClient(headers=HEADERS, timeout=self.timeout, follow_redirects=True) as client:
            for source in self.sources:
                for url in _feed_urls_for(source):
                    try:
                        response = await client.get(url)
                        response.raise_for_status()
                        parsed = parse_wire_feed_html(response.text, source=source, base_url=url)
                        items.extend(parsed)
                        if parsed:
                            break
                    except Exception as exc:
                        failed_sources[source] = failed_sources.get(source, 0) + 1
                        logger.debug("%s feed fetch failed (%s): %s", source, url, exc)
        logger.info("WireNews: fetched %d tickered items", len(items))
        summary = FinvizNewsSummary(
            news_items=_sort_by_ts_desc(items),
            blog_items=[],
            last_updated=datetime.now(timezone.utc),
        )
        summary.failed_sources = failed_sources  # type: ignore[attr-defined]
        self._cache = summary
        self._cache_time = now
        return summary

    def fetch_all_sync(self, force_refresh: bool = False) -> FinvizNewsSummary:
        return _run_coro_blocking(lambda: self.fetch_all(force_refresh=force_refresh))
