"""
Finviz Scanner — Scrapes top gainers from Finviz.com

Fetches the top 20 gainers from Finviz's screener page, extracts ticker
symbols, then pulls live market data via Yahoo Finance for each ticker.
"""

import logging
from typing import Optional

import httpx
from bs4 import BeautifulSoup
import yfinance as yf

from src.models.schemas import ScannedStock

logger = logging.getLogger(__name__)

FINVIZ_GAINERS_URL = "https://finviz.com/screener.ashx?v=111&s=ta_topgainers"
FINVIZ_UNDER2_URL = "https://finviz.com/screener.ashx?v=111&f=sh_curvol_o10000%2Csh_price_u2"


class FinvizScanner:
    """Scrapes Finviz top gainers and fetches market data via Yahoo Finance."""

    def __init__(self, max_results: int = 20):
        self.max_results = max_results

    def scan_gainers(self) -> list[ScannedStock]:
        """Fetch top gainers from Finviz, then get live data from Yahoo Finance."""
        tickers = self._scrape_finviz_tickers()
        if not tickers:
            logger.warning("No tickers scraped from Finviz")
            return []

        tickers = tickers[: self.max_results]
        logger.info("Scraped %d tickers from Finviz: %s", len(tickers), tickers)
        return self._fetch_market_data(tickers)

    def _scrape_finviz_tickers(self, url: str = FINVIZ_GAINERS_URL) -> list[str]:
        """Scrape ticker symbols from a Finviz screener page."""
        try:
            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                )
            }
            response = httpx.get(url, headers=headers, timeout=30)
            response.raise_for_status()

            soup = BeautifulSoup(response.text, "lxml")

            # Find all links that point to quote.ashx?t=TICKER
            tickers = []
            for link in soup.find_all("a", href=True):
                href = link.get("href", "")
                if "quote.ashx?t=" in href:
                    ticker = link.text.strip()
                    if ticker and ticker.isalpha() and len(ticker) <= 5:
                        tickers.append(ticker.upper())

            # De-duplicate while preserving order
            seen = set()
            unique = []
            for t in tickers:
                if t not in seen:
                    seen.add(t)
                    unique.append(t)

            logger.info("Found %d tickers from Finviz", len(unique))
            return unique

        except Exception as exc:
            logger.error("Failed to scrape Finviz: %s", exc)
            return []

    def scan_under_2(self) -> list[ScannedStock]:
        """Fetch stocks under $2 from Finviz (with volume >10k), then get live data."""
        tickers = self._scrape_finviz_tickers(FINVIZ_UNDER2_URL)
        if not tickers:
            logger.warning("No tickers scraped from Finviz under $2")
            return []

        tickers = tickers[: self.max_results]
        logger.info("Scraped %d tickers under $2 from Finviz: %s", len(tickers), tickers)
        stocks = self._fetch_market_data(tickers)
        # Filter to only include stocks actually under $2
        return [s for s in stocks if s.price is not None and s.price < 2.0]

    def _fetch_market_data(self, tickers: list[str]) -> list[ScannedStock]:
        """Fetch live market data for the given tickers via Yahoo Finance."""
        if not tickers:
            return []

        stocks: list[ScannedStock] = []
        try:
            tickers_obj = yf.Tickers(" ".join(tickers))

            for symbol in tickers:
                try:
                    tkr = tickers_obj.tickers.get(symbol)
                    if tkr is None:
                        continue

                    info = tkr.fast_info
                    hist = tkr.history(period="1d", interval="1m")
                    if hist.empty:
                        continue

                    price = float(hist["Close"].iloc[-1])
                    volume = float(hist["Volume"].sum())
                    open_price = float(hist["Open"].iloc[0])
                    change_pct = (
                        ((price - open_price) / open_price) * 100
                        if open_price
                        else 0
                    )

                    avg_vol = getattr(info, "three_month_average_volume", None)
                    rvol = volume / avg_vol if avg_vol and avg_vol > 0 else None

                    stocks.append(
                        ScannedStock(
                            ticker=symbol,
                            price=price,
                            volume=volume,
                            rvol=rvol,
                            change_percent=round(change_pct, 2),
                            market_cap=getattr(info, "market_cap", None),
                            float_shares=getattr(info, "shares", None),
                            scan_type="finviz_gainers",
                        )
                    )
                except Exception as exc:
                    logger.warning("Failed to fetch data for %s: %s", symbol, exc)

        except Exception as exc:
            logger.error("Failed to fetch market data batch: %s", exc)

        return stocks
