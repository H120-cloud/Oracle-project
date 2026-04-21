"""
Trading 212 Scraper — Top Movers & Popular Stocks Discovery

Fetches from Trading 212's public data endpoints:
- Top movers (daily % gainers/losers)
- Most traded stocks
- Popular in community

Note: Trading 212 doesn't have an official public API, so this uses
web scraping with fallbacks to cached/simulated data if blocked.
"""

import logging
import re
from dataclasses import dataclass
from typing import List, Optional
from datetime import datetime

try:
    import httpx
    from bs4 import BeautifulSoup
    HAS_DEPS = True
except ImportError:
    HAS_DEPS = False

logger = logging.getLogger(__name__)


@dataclass
class Trading212Stock:
    """Trading 212 stock discovery result."""
    ticker: str
    name: str
    change_pct: float
    volume: int = 0
    category: str = ""  # 'top_gainer', 'top_loser', 'most_traded', 'popular'
    reason: str = ""


class Trading212Scraper:
    """Scrape Trading 212 top movers and popular stocks."""

    # Trading 212 community/invest page URLs
    POPULAR_URL = "https://www.trading212.com/en/invest/popular"
    EXPLORE_URL = "https://www.trading212.com/en/invest/explore"

    # Alternative: use their search/popular API if available
    API_BASE = "https://www.trading212.com/api/v1"

    def __init__(self):
        self.client: Optional[httpx.AsyncClient] = None
        if HAS_DEPS:
            self.client = httpx.AsyncClient(
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0.0.0 Safari/537.36"
                    ),
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.5",
                    "Accept-Encoding": "gzip, deflate, br",
                    "DNT": "1",
                    "Connection": "keep-alive",
                },
                timeout=30,
                follow_redirects=True,
            )

    async def fetch_top_movers(self, limit: int = 20) -> List[Trading212Stock]:
        """Fetch top movers from Trading 212."""
        if not HAS_DEPS or not self.client:
            logger.warning("Dependencies missing for Trading 212 scraper")
            return []

        stocks = []

        try:
            # Try to fetch popular stocks page
            response = await self.client.get(self.POPULAR_URL)
            response.raise_for_status()

            soup = BeautifulSoup(response.text, "lxml")

            # Look for stock data in the page
            # Trading 212 uses React, so data might be in script tags as JSON
            scripts = soup.find_all("script")

            for script in scripts:
                text = script.string or ""
                # Look for window.__INITIAL_STATE__ or similar data stores
                if "__INITIAL_STATE__" in text or "window.__data" in text:
                    stocks.extend(self._parse_initial_state(text, limit))

            # Fallback: look for HTML structure if React data not found
            if not stocks:
                stocks.extend(self._parse_html_table(soup, limit))

        except httpx.HTTPStatusError as exc:
            logger.warning("Trading 212 returned %s - may require auth or be blocked", exc.response.status_code)
            # Fallback to alternative source
            stocks.extend(await self._fetch_from_alternative(limit))
        except Exception as exc:
            logger.error("Trading 212 scrape failed: %s", exc)
            stocks.extend(await self._fetch_from_alternative(limit))

        return stocks[:limit]

    def _parse_initial_state(self, script_text: str, limit: int) -> List[Trading212Stock]:
        """Parse React initial state from script tag."""
        stocks = []

        # Extract JSON from window.__INITIAL_STATE__ = {...}
        match = re.search(r'window\.__INITIAL_STATE__\s*=\s*({.+?});', script_text, re.DOTALL)
        if not match:
            match = re.search(r'window\.__data\s*=\s*({.+?});', script_text, re.DOTALL)

        if match:
            try:
                import json
                data = json.loads(match.group(1))

                # Navigate to stocks data (structure varies)
                instruments = data.get("instruments", []) or data.get("stocks", [])
                popular = data.get("popular", []) or data.get("topMovers", [])

                for item in popular[:limit]:
                    ticker = item.get("ticker") or item.get("symbol", "").upper()
                    if ticker:
                        stocks.append(Trading212Stock(
                            ticker=ticker,
                            name=item.get("name", ""),
                            change_pct=float(item.get("change", 0)),
                            volume=int(item.get("volume", 0)),
                            category="top_mover",
                            reason=f"Trading 212 top mover: {item.get('change', 0):+.2f}%"
                        ))

            except json.JSONDecodeError:
                pass

        return stocks

    def _parse_html_table(self, soup: BeautifulSoup, limit: int) -> List[Trading212Stock]:
        """Parse HTML table structure if found."""
        stocks = []

        # Look for stock rows
        rows = soup.find_all("tr", class_=re.compile(r"stock|instrument|row"))

        for row in rows[:limit]:
            cells = row.find_all(["td", "th"])
            if len(cells) >= 3:
                ticker = cells[0].get_text(strip=True).upper()
                name = cells[1].get_text(strip=True)
                change_text = cells[2].get_text(strip=True)

                # Parse percentage
                change_pct = 0.0
                try:
                    change_pct = float(change_text.replace("%", "").replace(",", ""))
                except ValueError:
                    pass

                if ticker and re.match(r'^[A-Z]{1,5}$', ticker):
                    stocks.append(Trading212Stock(
                        ticker=ticker,
                        name=name,
                        change_pct=change_pct,
                        category="top_mover",
                        reason=f"Trading 212: {change_pct:+.2f}%"
                    ))

        return stocks

    async def _fetch_from_alternative(self, limit: int) -> List[Trading212Stock]:
        """
        Fallback: Use alternative data source when Trading 212 blocks scraping.
        Uses Yahoo Finance trending as proxy for "popular" stocks.
        """
        logger.info("Using alternative source for popular stocks")

        try:
            # Yahoo Finance trending tickers as proxy
            url = "https://finance.yahoo.com/trending-tickers"
            response = await self.client.get(url)
            response.raise_for_status()

            soup = BeautifulSoup(response.text, "lxml")
            stocks = []

            # Find ticker rows
            rows = soup.find_all("tr", class_=re.compile(r"data-row"))

            for row in rows[:limit]:
                ticker_elem = row.find("td", attrs={"aria-label": "Symbol"})
                if ticker_elem:
                    ticker = ticker_elem.get_text(strip=True).upper()
                    change_elem = row.find("td", attrs={"aria-label": re.compile(r"% Change")})
                    change_pct = 0.0
                    if change_elem:
                        try:
                            change_text = change_elem.get_text(strip=True).replace("%", "").replace(",", "")
                            change_pct = float(change_text)
                        except ValueError:
                            pass

                    if ticker:
                        stocks.append(Trading212Stock(
                            ticker=ticker,
                            name="",
                            change_pct=change_pct,
                            category="trending",
                            reason=f"Yahoo trending: {change_pct:+.2f}%"
                        ))

            return stocks

        except Exception as exc:
            logger.error("Alternative fetch failed: %s", exc)
            return []

    async def fetch_most_traded(self, limit: int = 20) -> List[Trading212Stock]:
        """Fetch most traded stocks."""
        # Trading 212 doesn't expose this publicly, use volume leaders from Yahoo
        return await self._fetch_volume_leaders(limit)

    async def _fetch_volume_leaders(self, limit: int) -> List[Trading212Stock]:
        """Fetch high volume stocks as proxy for 'most traded'."""
        try:
            url = "https://finance.yahoo.com/most-active"
            response = await self.client.get(url)
            response.raise_for_status()

            soup = BeautifulSoup(response.text, "lxml")
            stocks = []

            rows = soup.find_all("tr", class_=re.compile(r"data-row"))

            for row in rows[:limit]:
                ticker_elem = row.find("td", attrs={"aria-label": "Symbol"})
                if ticker_elem:
                    ticker = ticker_elem.get_text(strip=True).upper()
                    vol_elem = row.find("td", attrs={"aria-label": re.compile(r"Volume")})
                    volume = 0
                    if vol_elem:
                        vol_text = vol_elem.get_text(strip=True).replace("M", "000000").replace("K", "000").replace(",", "")
                        try:
                            volume = int(float(vol_text))
                        except ValueError:
                            pass

                    if ticker:
                        stocks.append(Trading212Stock(
                            ticker=ticker,
                            name="",
                            change_pct=0.0,
                            volume=volume,
                            category="most_traded",
                            reason=f"High volume: {volume:,}"
                        ))

            return stocks

        except Exception as exc:
            logger.error("Volume leaders fetch failed: %s", exc)
            return []

    async def close(self):
        """Close HTTP client."""
        if self.client:
            await self.client.aclose()


# Convenience functions for use in DiscoveryEngine

async def fetch_trading212_top_movers(limit: int = 20) -> List[Trading212Stock]:
    """Fetch Trading 212 top movers."""
    scraper = Trading212Scraper()
    try:
        return await scraper.fetch_top_movers(limit)
    finally:
        await scraper.close()


async def fetch_trading212_most_traded(limit: int = 20) -> List[Trading212Stock]:
    """Fetch Trading 212 most traded stocks."""
    scraper = Trading212Scraper()
    try:
        return await scraper.fetch_most_traded(limit)
    finally:
        await scraper.close()
