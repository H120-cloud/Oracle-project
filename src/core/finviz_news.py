"""Finviz News Scraper — Real-time stock news from Finviz v=3 and v=6"""
import logging
import re
import time as _time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional
from urllib.parse import urljoin
import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}
CACHE_TTL = 300  # 5 minutes

@dataclass
class FinvizNewsItem:
    headline: str
    source: str
    url: str
    timestamp: Optional[datetime] = None
    tickers: List[str] = field(default_factory=list)
    category: str = "news"
    sentiment: str = "neutral"
    
    def to_dict(self):
        return {
            "headline": self.headline,
            "source": self.source,
            "url": self.url,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "tickers": self.tickers,
            "category": self.category,
            "sentiment": self.sentiment,
        }

@dataclass
class FinvizNewsSummary:
    news_items: List[FinvizNewsItem] = field(default_factory=list)
    blog_items: List[FinvizNewsItem] = field(default_factory=list)
    last_updated: Optional[datetime] = None
    
    def to_dict(self):
        return {
            "news": [n.to_dict() for n in self.news_items],
            "blogs": [b.to_dict() for b in self.blog_items],
            "last_updated": self.last_updated.isoformat() if self.last_updated else None,
            "count": len(self.news_items) + len(self.blog_items),
        }


class FinvizNewsScraper:
    NEWS_URL = "https://finviz.com/news.ashx?v=3"
    BLOG_URL = "https://finviz.com/news.ashx?v=6"
    BULLISH = ["surge", "jump", "rally", "soar", "gain", "up", "higher", "bullish", "beat", "beats", "upgrade", "strong", "growth", "profit", "breakout", "partnership", "deal", "contract", "approval", "buy"]
    BEARISH = ["drop", "fall", "plunge", "crash", "decline", "down", "lower", "bearish", "miss", "downgrade", "weak", "loss", "bankruptcy", "investigation", "lawsuit", "sell", "layoff", "warning"]

    def __init__(self, timeout=15):
        self.timeout = timeout
        self._cache: Optional[FinvizNewsSummary] = None
        self._cache_ts: float = 0

    def _get(self, url: str) -> str:
        """Fresh HTTP GET per request to avoid stale connections."""
        with httpx.Client(headers=HEADERS, timeout=self.timeout, follow_redirects=True) as client:
            resp = client.get(url)
            resp.raise_for_status()
            return resp.text

    def fetch_all(self) -> FinvizNewsSummary:
        # Return cache if fresh
        if self._cache and (_time.time() - self._cache_ts) < CACHE_TTL:
            return self._cache

        summary = FinvizNewsSummary()
        try:
            summary.news_items = self._fetch_news()
            logger.info("Fetched %d news items from Finviz", len(summary.news_items))
        except Exception as e:
            logger.error("News fetch failed: %s", e)
        try:
            summary.blog_items = self._fetch_blogs()
            logger.info("Fetched %d blog items from Finviz", len(summary.blog_items))
        except Exception as e:
            logger.error("Blog fetch failed: %s", e)
        summary.last_updated = datetime.now(timezone.utc)

        self._cache = summary
        self._cache_ts = _time.time()
        return summary

    def _fetch_news(self) -> List[FinvizNewsItem]:
        items = []
        html = self._get(self.NEWS_URL)
        soup = BeautifulSoup(html, "html.parser")
        for table in soup.find_all("table", class_="table-fixed"):
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
                        ticker_tags = [s.get_text(strip=True) for s in spans[:-1]] if len(spans) > 1 else []
                        ts = self._parse_time(cols[0].get_text(strip=True))
                        tickers = ticker_tags if ticker_tags else self._extract_tickers(headline)
                        sentiment = self._sentiment(headline)
                        items.append(FinvizNewsItem(headline=headline, source=source, url=url, timestamp=ts, tickers=tickers, category="news", sentiment=sentiment))
        return items[:50]

    def _fetch_blogs(self) -> List[FinvizNewsItem]:
        items = []
        html = self._get(self.BLOG_URL)
        soup = BeautifulSoup(html, "html.parser")
        for table in soup.find_all("table", class_="table-fixed"):
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
                        time_text = cols[1].get_text(strip=True)
                        ts = self._parse_time(time_text)
                        tickers = self._extract_tickers(headline)
                        cat = "press_release" if "Newswire" in source or "PR " in source else "blog"
                        sentiment = self._sentiment(headline)
                        items.append(FinvizNewsItem(headline=headline, source=source, url=url, timestamp=ts, tickers=tickers, category=cat, sentiment=sentiment))
        return items[:50]

    def _parse_time(self, text: str) -> Optional[datetime]:
        try:
            now = datetime.now(timezone.utc)
            text = text.strip().upper()
            if "YESTERDAY" in text:
                t = datetime.strptime(text.replace("YESTERDAY", "").strip(), "%I:%M%p")
                return now.replace(hour=t.hour, minute=t.minute, second=0, microsecond=0, day=now.day-1)
            t = datetime.strptime(text, "%I:%M%p")
            return now.replace(hour=t.hour, minute=t.minute, second=0, microsecond=0)
        except:
            return None

    def _extract_tickers(self, headline: str) -> List[str]:
        tickers = re.findall(r'\$([A-Z]{1,5})\b', headline)
        common = {"A", "I", "AM", "PM", "CEO", "CFO", "FDA", "SEC", "EPS", "IPO", "AI", "ETF", "SPY", "QQQ", "USA", "GDP", "CPI", "FED"}
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

    def close(self):
        pass
