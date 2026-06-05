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

# The /market_reports/ AMP sub-path returns a broken server-side error stub
# ("MANDATORY WS EMPTY"). The parent /amp/press_note index serves the real
# press-note listing (~97KB, ~60 article links) and is what we scrape.
SHARECAST_PRESS_NOTE_URL = "https://www.sharecast.com/amp/press_note"
SHARECAST_CACHE_TTL = float(os.environ.get("SHARECAST_CACHE_TTL_SECONDS", "60") or 60)

HEADERS = {
    **_BASE_HEADERS,
    # Full browser header set — Sharecast 403s the default UA. These get us a
    # 200 (past the block), though their AMP feed is frequently server-side
    # broken and the main site is a JS SPA, so content may still be empty.
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.sharecast.com/",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
    "Upgrade-Insecure-Requests": "1",
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

        html = await self._fetch(SHARECAST_PRESS_NOTE_URL)
        # Sharecast's AMP endpoint regularly returns a server-side error stub
        # ("[Section Exception Catched] MANDATORY WS EMPTY") with HTTP 200, and
        # the main site is a JS SPA with no server-rendered articles. Detect
        # these so we surface a real failure to the health tracker instead of
        # silently caching an empty "success" (which made the dashboard show
        # Sharecast green while it was actually down).
        if "section exception" in html.lower() or "mandatory ws empty" in html.lower():
            raise RuntimeError("Sharecast upstream error stub (MANDATORY WS EMPTY)")

        items = parse_sharecast_press_note_html(html, base_url=SHARECAST_PRESS_NOTE_URL)
        if not items:
            # Reaching here with zero items means the page loaded but had no
            # parseable tickered press-notes (JS-rendered / layout change).
            # Raise so this counts as an error, not a healthy empty fetch.
            raise RuntimeError(
                "Sharecast returned no parseable items (%d bytes) — likely "
                "JS-rendered or layout changed" % len(html)
            )

        logger.info("Sharecast: fetched %d tickered press-note items", len(items))
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
    _seen_headlines: set[str] = set()  # dedup repeated anchors on the page

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
        # Only treat real article anchors as headlines (skip nav/index links
        # like "/press_note/all" and short non-headline text).
        if node.name == "a":
            if not href or "/press_note/market_reports/" not in href:
                continue
            if len(text) < 15:
                continue

        # 1) STRICT: explicit symbol in the headline ($TICK / (TICK)).
        tickers = extract_sharecast_tickers(text)
        # 2) FALLBACK: Sharecast usually prints a company NAME, not a symbol.
        #    Resolve name -> US ticker. Names that don't map to a US listing
        #    (UK-only funds/trusts) return nothing and are correctly dropped.
        if not tickers:
            resolved = _resolve_name_ticker(text)
            if resolved:
                tickers = [resolved]
        if not tickers:
            continue

        if text in _seen_headlines:
            continue
        _seen_headlines.add(text)

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


def _resolve_name_ticker(headline: str) -> Optional[str]:
    """Map a Sharecast company-name headline to a US ticker. The leading text
    before a ' - ' separator is the company name (e.g. 'Capital Gearing Trust
    P.l.c. - Net Asset Value(s)')."""
    try:
        from src.core.company_name_resolver import resolve_company_ticker
    except Exception:
        return None
    cleaned = re.sub(
        r"^(?:NYSE|NASDAQ|AMEX)\s+Content\s+Update:\s*",
        "",
        headline or "",
        flags=re.IGNORECASE,
    ).strip()
    name = cleaned.split(" - ")[0].strip()
    return resolve_company_ticker(name) or resolve_company_ticker(headline)
