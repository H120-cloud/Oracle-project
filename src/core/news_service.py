"""
News Service — fetch news headlines for tickers.

Uses Yahoo Finance news pages and aggregates headlines.
"""

import logging
import httpx
from bs4 import BeautifulSoup
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, List

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}


@dataclass
class NewsItem:
    headline: str
    source: Optional[str] = None
    url: Optional[str] = None
    published_at: Optional[datetime] = None
    sentiment: Optional[str] = None  # positive, negative, neutral


class NewsService:
    """Fetch news for tickers from Yahoo Finance."""

    def __init__(self):
        self.client = httpx.Client(headers=HEADERS, timeout=30)

    def get_ticker_news(self, ticker: str, max_items: int = 10) -> List[NewsItem]:
        """Fetch recent news headlines for a ticker."""
        try:
            url = f"https://finance.yahoo.com/quote/{ticker.upper()}/news"
            response = self.client.get(url)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "lxml")

            news_items = []

            # Look for news article links
            for link in soup.find_all("a", href=True):
                href = link.get("href", "")
                text = link.get_text(strip=True)

                # Filter for news headlines (typically longer than 20 chars)
                if len(text) > 20 and ("/news/" in href or "/video/" in href or href.startswith("https://")):
                    # Determine sentiment from headline
                    sentiment = self._classify_sentiment(text)

                    news_items.append(NewsItem(
                        headline=text,
                        source=self._extract_source(href),
                        url=href if href.startswith("http") else f"https://finance.yahoo.com{href}",
                        sentiment=sentiment,
                    ))

                    if len(news_items) >= max_items:
                        break

            return news_items

        except Exception as exc:
            logger.error("Failed to fetch news for %s: %s", ticker, exc)
            return []

    def _classify_sentiment(self, headline: str) -> Optional[str]:
        """Simple keyword-based sentiment analysis."""
        headline_lower = headline.lower()

        positive_words = ['beat', 'beats', 'surge', 'surges', 'rally', 'rallies', 'gain', 'gains',
                         'jump', 'jumps', 'soar', 'soars', 'bull', 'bullish', 'upgrade', 'upgrades',
                         'strong', 'growth', 'profit', 'profits', 'exceed', 'exceeds', 'outperform']
        negative_words = ['drop', 'drops', 'fall', 'falls', 'plunge', 'plunges', 'crash', 'crashes',
                         'bear', 'bearish', 'downgrade', 'downgrades', 'miss', 'misses', 'loss',
                         'losses', 'decline', 'declines', 'sell', 'selling', 'cut', 'cuts', 'weak']

        pos_count = sum(1 for w in positive_words if w in headline_lower)
        neg_count = sum(1 for w in negative_words if w in headline_lower)

        if pos_count > neg_count:
            return "positive"
        elif neg_count > pos_count:
            return "negative"
        return "neutral"

    def _extract_source(self, url: str) -> Optional[str]:
        """Extract news source from URL."""
        if "yahoo.com" in url:
            return "Yahoo Finance"
        elif "bloomberg.com" in url:
            return "Bloomberg"
        elif "reuters.com" in url:
            return "Reuters"
        elif "cnbc.com" in url:
            return "CNBC"
        elif "marketwatch.com" in url:
            return "MarketWatch"
        elif " seekingalpha.com" in url:
            return "Seeking Alpha"
        return "News"

    def close(self):
        self.client.close()
