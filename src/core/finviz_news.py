"""Finviz News Scraper — Real-time stock news from Finviz v=3 and v=6"""
import asyncio
import concurrent.futures
import logging
import os as _os
import re
import time as _time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from typing import Any, Awaitable, Callable, List, Optional
from urllib.parse import urljoin
import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


def _run_coro_blocking(coro_factory: Callable[[], Awaitable[Any]]) -> Any:
    """Run an async coroutine from sync code, safely from inside an event loop.

    Many of our async scrapers expose `*_sync` wrappers that previously did
    `asyncio.run(coro())`. That fails with `RuntimeError: asyncio.run() cannot
    be called from a running event loop` when invoked from inside an async
    context (e.g. `_check_news_status` called from a coroutine). The exception
    was being swallowed silently and the coroutine garbage-collected
    un-awaited (RuntimeWarning), so the per-ticker news fallback never ran.

    Accept a factory rather than the coroutine itself so we can build a fresh
    coroutine inside the worker thread — a coroutine bound to one loop can't
    be moved to another.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        # No running loop in this thread — safe to use asyncio.run directly.
        return asyncio.run(coro_factory())
    # Already inside an event loop — offload to a worker thread which gets
    # its own loop via asyncio.run().
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        return ex.submit(lambda: asyncio.run(coro_factory())).result()
_ET = ZoneInfo("America/New_York")

# Shared by all news scrapers in this package
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}
# Short TTL so the user-facing feed never trails reality by more than a minute.
# Frontend polls every 5 min but the manual Refresh button bypasses the cache.
CACHE_TTL = 60

def _sort_by_ts_desc(items: list) -> list:
    """Sort news items newest-first; undated items sink to the bottom."""
    return sorted(items, key=lambda i: i.timestamp or datetime.min.replace(tzinfo=timezone.utc), reverse=True)


@dataclass
class FinvizNewsItem:
    headline: str
    source: str
    url: str
    timestamp: Optional[datetime] = None
    timestamp_confidence: str = "HIGH"
    fetched_at: Optional[datetime] = None
    parsed_at: Optional[datetime] = None
    tickers: List[str] = field(default_factory=list)
    category: str = "news"
    sentiment: str = "neutral"
    description: str = ""
    
    def to_dict(self):
        return {
            "headline": self.headline,
            "source": self.source,
            "url": self.url,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "fetched_at": self.fetched_at.isoformat() if self.fetched_at else None,
            "parsed_at": self.parsed_at.isoformat() if self.parsed_at else None,
            "tickers": self.tickers,
            "category": self.category,
            "sentiment": self.sentiment,
            "description": self.description,
        }

@dataclass
class FinvizNewsSummary:
    news_items: List[FinvizNewsItem] = field(default_factory=list)
    blog_items: List[FinvizNewsItem] = field(default_factory=list)
    last_updated: Optional[datetime] = None
    failed_sources: dict[str, int] = field(default_factory=dict)
    
    def to_dict(self):
        return {
            "news": [n.to_dict() for n in self.news_items],
            "blogs": [b.to_dict() for b in self.blog_items],
            "last_updated": self.last_updated.isoformat() if self.last_updated else None,
            "count": len(self.news_items) + len(self.blog_items),
            "failed_sources": self.failed_sources,
        }


class FinvizNewsScraper:
    NEWS_URL = "https://finviz.com/news?v=3"
    BLOG_URL = "https://finviz.com/news?v=6"
    BULLISH = ["surge", "jump", "rally", "soar", "gain", "up", "higher", "bullish", "beat", "beats", "upgrade", "strong", "growth", "profit", "breakout", "partnership", "deal", "contract", "approval", "buy"]
    BEARISH = ["drop", "fall", "plunge", "crash", "decline", "down", "lower", "bearish", "miss", "downgrade", "weak", "loss", "bankruptcy", "investigation", "lawsuit", "sell", "layoff", "warning"]

    def __init__(self, timeout=15):
        self.timeout = timeout
        self._cache: Optional[FinvizNewsSummary] = None
        self._cache_ts: float = 0

    @staticmethod
    async def _fetch_with_retry(client: httpx.AsyncClient, url: str, max_retries: int = 3) -> httpx.Response:
        """Fetch URL with exponential backoff on retryable errors."""
        for attempt in range(1, max_retries + 1):
            try:
                resp = await client.get(url)
                if resp.status_code < 500 and resp.status_code != 429:
                    return resp
                if resp.status_code in (503, 504, 429):
                    if attempt < max_retries:
                        wait = 2 ** (attempt - 1)
                        logger.warning("Finviz fetch %s got %d, retrying in %ds (attempt %d/%d)", url, resp.status_code, wait, attempt, max_retries)
                        await asyncio.sleep(wait)
                        continue
                resp.raise_for_status()
                return resp
            except (httpx.TimeoutException, httpx.ConnectError) as exc:
                if attempt < max_retries:
                    wait = 2 ** (attempt - 1)
                    logger.warning("Finviz fetch %s error: %s, retrying in %ds (attempt %d/%d)", url, exc, wait, attempt, max_retries)
                    await asyncio.sleep(wait)
                else:
                    raise
        raise httpx.HTTPStatusError(
            f"Max retries exceeded for {url}",
            request=None, response=None,
        )

    async def _get(self, url: str) -> str:
        """Fresh HTTP GET per request to avoid stale connections."""
        async with httpx.AsyncClient(headers=HEADERS, timeout=self.timeout, follow_redirects=True) as client:
            resp = await self._fetch_with_retry(client, url)
            return resp.text

    async def fetch_all(self, force_refresh: bool = False) -> FinvizNewsSummary:
        # Return cache if fresh
        if (not force_refresh) and self._cache and (_time.time() - self._cache_ts) < CACHE_TTL:
            return self._cache

        summary = FinvizNewsSummary()
        try:
            summary.news_items = await self._fetch_news()
            logger.info("Fetched %d news items from Finviz", len(summary.news_items))
        except Exception as e:
            summary.failed_sources["FinvizNews"] = summary.failed_sources.get("FinvizNews", 0) + 1
            logger.error("News fetch failed: %s", e)
        try:
            summary.blog_items = await self._fetch_blogs()
            logger.info("Fetched %d blog items from Finviz", len(summary.blog_items))
        except Exception as e:
            summary.failed_sources["FinvizBlogs"] = summary.failed_sources.get("FinvizBlogs", 0) + 1
            logger.error("Blog fetch failed: %s", e)
        summary.last_updated = datetime.now(timezone.utc)

        self._cache = summary
        self._cache_ts = _time.time()
        return summary

    def fetch_all_sync(self, force_refresh: bool = False) -> FinvizNewsSummary:
        """Synchronous wrapper — safe from inside an event loop too."""
        return _run_coro_blocking(lambda: self.fetch_all(force_refresh=force_refresh))

    async def _fetch_news(self) -> List[FinvizNewsItem]:
        items = []
        html = await self._get(self.NEWS_URL)
        soup = BeautifulSoup(html, "html.parser")
        # Finviz's news table shows the time only on the FIRST row of each
        # time-group; following rows in the same minute have an empty time
        # cell. Without forward-filling, ~80% of items end up with no
        # timestamp and downstream code fakes one (== "now"), which makes
        # hours-old headlines appear as fresh catalysts. Carry the last
        # non-empty parsed timestamp forward as we walk the table top→bottom.
        # IMPORTANT: reset per table — Finviz may render multiple table-fixed
        # blocks (e.g. a curated "Editorial" or "Trending" section after the
        # main news feed), and leaking the previous table's last_ts into the
        # first row of a stale-content table would stamp old items as fresh
        # and fire speed-tier alerts on already-played catalysts.
        for table in soup.find_all("table", class_="table-fixed"):
            last_ts: Optional[datetime] = None
            for row in table.find_all("tr"):
                cols = row.find_all("td")
                if len(cols) >= 2:
                    link = cols[1].find("a", class_="nn-tab-link")
                    if link:
                        headline = link.get_text(strip=True)
                        href = link.get("href", "")
                        url = urljoin("https://finviz.com", href) if href.startswith("/") else href
                        spans = cols[1].find_all("span")
                        source = spans[-1].get_text(strip=True) if spans else "Finviz"
                        raw_tags = [s.get_text(strip=True) for s in spans[:-1]] if len(spans) > 1 else []
                        ticker_tags = [t.lstrip('$') for t in raw_tags if t and 'more' not in t.lower() and len(t.lstrip('$')) <= 5]
                        time_text = cols[0].get_text(strip=True)
                        parsed = self._parse_time(time_text)
                        if parsed is not None:
                            last_ts = parsed
                            ts = parsed
                        else:
                            # Empty cell / unparseable — inherit the most recent
                            # known timestamp above us in the document.
                            ts = last_ts
                        # Filter ticker tags down to the article's actual subject.
                        # Without this, a market-commentary piece tagged with 5
                        # related tickers creates 5 candidates, every one of which
                        # the orchestrator will independently score and the missed-
                        # winner learner will independently track.
                        tickers = (
                            self._attribute_primary_tickers(ticker_tags, headline)
                            if ticker_tags
                            else self._extract_tickers(headline)
                        )
                        sentiment = self._sentiment(headline)
                        items.append(FinvizNewsItem(headline=headline, source=source, url=url, timestamp=ts, tickers=tickers, category="news", sentiment=sentiment))
        return _sort_by_ts_desc(items)[:50]

    async def _fetch_blogs(self) -> List[FinvizNewsItem]:
        items = []
        html = await self._get(self.BLOG_URL)
        soup = BeautifulSoup(html, "html.parser")
        # Same "ditto-time" pattern as the news feed: empty time cells
        # inherit the most recent timestamp above them. v=6 also has a
        # separate date column we can fold into the parse if the time
        # column is bare. Reset per table to avoid leaking timestamps
        # across unrelated content blocks (see _fetch_news rationale).
        for table in soup.find_all("table", class_="table-fixed"):
            last_ts: Optional[datetime] = None
            for row in table.find_all("tr"):
                cols = row.find_all("td")
                if len(cols) >= 3:
                    # v=6 layout: col0=date, col1=time, col2=headline
                    headline_col = cols[2]
                    link = headline_col.find("a")
                    if link:
                        headline = link.get_text(strip=True)
                        if not headline or len(headline) < 10:
                            continue
                        href = link.get("href", "")
                        url = urljoin("https://finviz.com", href) if href.startswith("/") else href
                        source = "Blog"
                        spans = headline_col.find_all("span")
                        if spans:
                            source = spans[-1].get_text(strip=True) or "Blog"
                        date_text = cols[0].get_text(strip=True)
                        time_text = cols[1].get_text(strip=True)
                        # Try date+time first (covers older items with full date),
                        # then time-only, then forward-fill from the last known ts.
                        combined = f"{date_text} {time_text}".strip()
                        parsed = self._parse_time(combined) or self._parse_time(time_text)
                        if parsed is not None:
                            last_ts = parsed
                            ts = parsed
                        else:
                            ts = last_ts
                        # The blog/v=6 layout puts ticker spans inside the same
                        # headline column as v=3. Pull any tag spans here and
                        # filter via the same primary-subject heuristic — without
                        # this, generic press-release wires (Business Wire,
                        # PR Newswire) co-tag multiple unrelated tickers.
                        all_spans = headline_col.find_all("span")
                        raw_tags = [s.get_text(strip=True) for s in all_spans[:-1]] if len(all_spans) > 1 else []
                        ticker_tags = [t.lstrip('$') for t in raw_tags if t and 'more' not in t.lower() and len(t.lstrip('$')) <= 5]
                        tickers = (
                            self._attribute_primary_tickers(ticker_tags, headline)
                            if ticker_tags
                            else self._extract_tickers(headline)
                        )
                        cat = "press_release" if "Newswire" in source or "PR " in source else "blog"
                        sentiment = self._sentiment(headline)
                        items.append(FinvizNewsItem(headline=headline, source=source, url=url, timestamp=ts, tickers=tickers, category=cat, sentiment=sentiment))
        return _sort_by_ts_desc(items)[:50]

    def _parse_time(self, text: str) -> Optional[datetime]:
        """Parse Finviz global-feed timestamp string.

        Supported formats (Finviz displays times in US/Eastern):
          - '12 min' / '1 hour' / '3 hr' / '2 days' / '45 sec'
                                   — relative time (CURRENT Finviz v=3 / v=6 layout, 2026+)
          - '04:20PM'              — time only, assumed today (rolled back to yesterday if it would be in the future)
          - 'Yesterday 04:20PM'    — explicit prior day
          - 'Today 04:20PM'        — explicit current day
          - 'Mar-15-26 04:20PM'    — older items with full date
          - 'Mar-15-26'            — date only (defaults to midnight ET)
        """
        if not text:
            return None
        try:
            now = datetime.now(_ET)
            text = text.strip().upper()

            # Relative time: 'N UNIT [AGO]' where UNIT ∈ {sec, min, hr/hour, day, week}.
            # This is what Finviz currently shows on v=3 (global news) and v=6 (blogs);
            # missing it was causing the orchestrator to fabricate "now" for every item
            # and display hours-old headlines as fresh catalysts.
            m = re.match(
                r"^\s*(\d+)\s*(SEC|SECOND|MIN|MINUTE|HR|HOUR|DAY|WEEK)S?\s*(?:AGO)?\s*$",
                text,
            )
            if m:
                n = int(m.group(1))
                unit = m.group(2)
                if unit.startswith("SEC"):
                    delta = timedelta(seconds=n)
                elif unit.startswith("MIN"):
                    delta = timedelta(minutes=n)
                elif unit.startswith("HR") or unit.startswith("HOUR"):
                    delta = timedelta(hours=n)
                elif unit.startswith("DAY"):
                    delta = timedelta(days=n)
                else:  # WEEK
                    delta = timedelta(weeks=n)
                return (now - delta).astimezone(timezone.utc)

            if "YESTERDAY" in text:
                t = datetime.strptime(text.replace("YESTERDAY", "").strip(), "%I:%M%p")
                yesterday = now - timedelta(days=1)
                dt = yesterday.replace(hour=t.hour, minute=t.minute, second=0, microsecond=0)
                return dt.astimezone(timezone.utc)

            if "TODAY" in text:
                t = datetime.strptime(text.replace("TODAY", "").strip(), "%I:%M%p")
                dt = now.replace(hour=t.hour, minute=t.minute, second=0, microsecond=0)
                return dt.astimezone(timezone.utc)

            # Time-only HH:MMam/pm — assume today, but if that puts it in the
            # future (e.g. 11:30PM seen at 1:00AM), the headline was posted
            # late on the prior day, so roll back 24h.
            try:
                t = datetime.strptime(text, "%I:%M%p")
                dt = now.replace(hour=t.hour, minute=t.minute, second=0, microsecond=0)
                if dt > now + timedelta(minutes=2):
                    dt -= timedelta(days=1)
                return dt.astimezone(timezone.utc)
            except ValueError:
                pass

            # Full 'Mon-DD-YY HH:MMam/pm' (e.g. 'Mar-15-26 04:20PM')
            try:
                dt = datetime.strptime(text, "%b-%d-%y %I:%M%p")
                return dt.replace(tzinfo=_ET).astimezone(timezone.utc)
            except ValueError:
                pass

            # Full-month, comma, NO year — e.g. 'MAY 28, 5:40 PM' or 'MAY 28'.
            # This is the per-ticker / overview widget format and was previously
            # unparseable → returned None → defaulted to "now" → old news shown
            # as fresh. Year is absent, so infer it: assume current year, and if
            # that lands in the future (e.g. a Dec headline parsed in Jan), roll
            # back a year. Handles both %b (May) and %B (September) month names.
            for fmt in ("%b %d, %I:%M %p", "%B %d, %I:%M %p", "%b %d %I:%M %p",
                        "%b %d", "%B %d"):
                try:
                    t = datetime.strptime(text, fmt)
                except ValueError:
                    continue
                dt = t.replace(year=now.year, tzinfo=_ET)
                if dt > now + timedelta(days=1):
                    dt = dt.replace(year=now.year - 1)
                return dt.astimezone(timezone.utc)

            # Date-only fallback
            dt = datetime.strptime(text, "%b-%d-%y")
            return dt.replace(tzinfo=_ET).astimezone(timezone.utc)
        except Exception:
            return None

    def _extract_tickers(self, headline: str) -> List[str]:
        tickers = re.findall(r'\$([A-Z]{1,5})\b', headline)
        common = {"A", "I", "AM", "PM", "CEO", "CFO", "FDA", "SEC", "EPS", "IPO", "AI", "ETF", "SPY", "QQQ", "USA", "GDP", "CPI", "FED", "MORE"}
        for w in re.findall(r'\b[A-Z]{2,5}\b', headline):
            if w not in common and w not in tickers:
                tickers.append(w)
        return tickers[:5]

    def _sentiment(self, headline: str) -> str:
        h = headline.lower()
        bull = sum(1 for w in self.BULLISH if w in h)
        bear = sum(1 for w in self.BEARISH if w in h)
        if bull > bear:
            return "bullish"
        if bear > bull:
            return "bearish"
        return "neutral"

    @staticmethod
    def _attribute_primary_tickers(ticker_tags: List[str], headline: str) -> List[str]:
        """Decide which of Finviz's ticker-tag spans the article is REALLY about.

        Finviz tags articles with co-mentioned/related tickers using its own
        relevance algorithm — a market commentary piece routinely gets tagged
        with 3-5 tickers even though it has no specific subject. Inheriting
        those tags wholesale creates a separate candidate per ticker per
        scan, which:
          (a) inflates the candidate set with low-relevance items
          (b) poisons the "missed winner" learner (one Hoth article that
              mentions RKTO becomes a phantom RKTO "missed catalyst")
          (c) corrupts ML training labels — the model sees a winner pattern
              for tickers that weren't actually the article's subject

        Heuristic:
          1. If at least one tag appears as a word in the headline, those
             tags are CONFIRMED subjects — return only those.
          2. Otherwise the headline is ticker-symbol-free (e.g. uses the
             company name only); fall back to the FIRST tag, which Finviz
             consistently lists as its best guess at the primary subject.

        Note: this trims the candidate fan-out per article but does NOT
        prevent legitimate multi-ticker articles like
        "MNTS, ASTC, RKTO Soar As NASA Ramps Up..." from creating one
        candidate per ticker — all three appear as words in the headline.
        """
        if not ticker_tags:
            return []
        headline_upper = headline.upper()
        confirmed = [
            t for t in ticker_tags
            if re.search(r"\b" + re.escape(t.upper()) + r"\b", headline_upper)
        ]
        if confirmed:
            return confirmed
        return [ticker_tags[0]]

    def close(self):
        pass

    # ── Per-ticker news (covers older catalysts not in the global feed) ──
    QUOTE_URL = "https://finviz.com/quote.ashx?t={ticker}&p=d"
    # 10 min default: this runs for ~30 hot tickers per scan, so the cache keeps
    # us from hammering Finviz (ban risk). Tunable via FINVIZ_TICKER_CACHE_TTL_SECONDS
    # for users who want fresher per-ticker coverage and accept the extra load.
    _TICKER_CACHE_TTL = int(_os.environ.get("FINVIZ_TICKER_CACHE_TTL_SECONDS", "600") or 600)

    async def fetch_ticker_news(
        self,
        ticker: str,
        max_items: int = 20,
        force_refresh: bool = False,
    ) -> List[FinvizNewsItem]:
        """Fetch ticker-specific news from Finviz's quote page.

        Unlike `fetch_all` (which scrapes the global feed and only sees recent
        items), this returns headlines tied to a specific ticker including
        older items (multi-day-old catalysts).
        """
        if not hasattr(self, "_ticker_cache"):
            self._ticker_cache: dict = {}
        cache_key = ticker.upper()
        cached = self._ticker_cache.get(cache_key)
        if (not force_refresh) and cached and (_time.time() - cached[0]) < self._TICKER_CACHE_TTL:
            return cached[1]

        items: List[FinvizNewsItem] = []
        try:
            html = await self._get(self.QUOTE_URL.format(ticker=ticker.upper()))
            soup = BeautifulSoup(html, "html.parser")

            # The ticker news table is identified by id `news-table`
            news_table = soup.find("table", id="news-table")
            if not news_table:
                return []

            last_date: Optional[str] = None
            for row in news_table.find_all("tr"):
                td_date = row.find("td", align="right") or (row.find_all("td")[0] if row.find_all("td") else None)
                link = row.find("a", class_="tab-link-news") or row.find("a")
                if not link:
                    continue
                headline = link.get_text(strip=True)
                url = link.get("href", "")
                source_span = row.find("span")
                source = source_span.get_text(strip=True).strip("()") if source_span else "finviz"

                # Date column may show full date or just time (continuation row)
                date_text = td_date.get_text(strip=True) if td_date else ""
                ts = self._parse_quote_timestamp(date_text, last_date)
                if ts and len(date_text.split()) >= 2:
                    first_tok = date_text.split()[0]
                    # Normalize "Today"/"Yesterday" into a concrete date string
                    if first_tok.lower() in ("today", "yesterday"):
                        last_date = ts.strftime("%b-%d-%y")
                    else:
                        last_date = first_tok

                items.append(
                    FinvizNewsItem(
                        headline=headline,
                        source=source,
                        url=url,
                        timestamp=ts,
                        tickers=[ticker.upper()],
                        category="news",
                        sentiment=self._sentiment(headline),
                    )
                )
                if len(items) >= max_items:
                    break
        except Exception as exc:
            logger.debug("FinvizNewsScraper.fetch_ticker_news(%s) failed: %s", ticker, exc)
            return []

        self._ticker_cache[cache_key] = (_time.time(), items)
        return items

    def fetch_ticker_news_sync(self, ticker: str, max_items: int = 20) -> List[FinvizNewsItem]:
        """Synchronous wrapper — safe from inside an event loop too."""
        return _run_coro_blocking(lambda: self.fetch_ticker_news(ticker, max_items=max_items))

    def _parse_quote_timestamp(self, text: str, last_date: Optional[str]) -> Optional[datetime]:
        """Parse Finviz quote-page timestamp.

        Supported formats:
          - 'May-01-26 04:20PM'   (full date + time)
          - '04:20PM'             (time only — uses last_date as fallback)
          - 'Today 01:57PM'       (same-day items)
          - 'Yesterday 09:30AM'   (previous day)
        """
        if not text:
            return None
        try:
            text = text.strip()
            parts = text.split()

            # Handle "Today" / "Yesterday" prefix
            if len(parts) == 2 and parts[0].lower() in ("today", "yesterday"):
                today = datetime.now(_ET).date()
                if parts[0].lower() == "yesterday":
                    today = today - timedelta(days=1)
                time_part = parts[1]
                dt = datetime.strptime(
                    f"{today.strftime('%b-%d-%y')} {time_part}", "%b-%d-%y %I:%M%p"
                )
                dt = dt.replace(tzinfo=_ET)
                return dt.astimezone(timezone.utc)

            if len(parts) == 2:
                date_part, time_part = parts
            elif len(parts) == 1 and last_date:
                date_part, time_part = last_date, parts[0]
            else:
                return None
            dt = datetime.strptime(f"{date_part} {time_part}", "%b-%d-%y %I:%M%p")
            dt = dt.replace(tzinfo=_ET)
            return dt.astimezone(timezone.utc)
        except Exception:
            return None
