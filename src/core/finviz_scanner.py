"""
Finviz Scanner — Scrapes top gainers from Finviz.com

Fetches the top 20 gainers from Finviz's screener page, extracts ticker
symbols, then pulls live market data via Yahoo Finance for each ticker.
"""

import json
import logging
import os
import re
from typing import Optional

from src.utils.atomic_json import save_json_file

import httpx
from bs4 import BeautifulSoup
import yfinance as yf

from src.models.schemas import ScannedStock
from src.utils.yfinance_cache import configure_yfinance_cache

configure_yfinance_cache(yf)

logger = logging.getLogger(__name__)

FINVIZ_GAINERS_URL = "https://finviz.com/screener?v=111&s=ta_topgainers"
FINVIZ_UNDER2_URL = "https://finviz.com/screener?v=111&f=sh_curvol_o10000%2Csh_price_u2"


class FinvizScanner:
    """Scrapes Finviz top gainers and fetches market data via Yahoo Finance."""

    # Shared bad-ticker cache path (same file CatalystScanner uses)
    _BAD_TICKERS_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "data", "agentic", "bad_tickers.json")

    def __init__(self, max_results: int = 20):
        self.max_results = max_results
        self._bad_tickers: set[str] = set()
        self._load_bad_tickers()

    def _load_bad_tickers(self):
        try:
            path = os.path.normpath(self._BAD_TICKERS_PATH)
            if os.path.exists(path):
                with open(path) as f:
                    self._bad_tickers = set(json.load(f))
                logger.debug("FinvizScanner: loaded %d bad tickers", len(self._bad_tickers))
        except Exception as exc:
            logger.debug("Failed to load bad tickers: %s", exc)

    def _save_bad_tickers(self):
        try:
            path = os.path.normpath(self._BAD_TICKERS_PATH)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            save_json_file(path, sorted(self._bad_tickers))
        except Exception as exc:
            logger.debug("Failed to save bad tickers: %s", exc)

    def _validate_tickers(self, tickers: list[str]) -> list[str]:
        """Quick yfinance validation to strip false positives.

        Only permanently cache tickers that have no price data (genuinely
        invalid / delisted). Transient errors (rate limits, network issues)
        are NOT cached so they are retried on the next scan.
        """
        valid = []
        for t in tickers:
            if t in self._bad_tickers:
                continue
            try:
                # Use history() instead of fast_info — much more reliable
                hist = yf.Ticker(t).history(period="5d", interval="1d")
                if not hist.empty:
                    valid.append(t)
                else:
                    # No price history — genuinely invalid/delisted ticker
                    self._bad_tickers.add(t)
            except Exception as exc:
                err = str(exc).lower()
                # Only blacklist on clear "not found" errors
                if any(k in err for k in ("delisted", "not found", "invalid symbol", "no data found")):
                    self._bad_tickers.add(t)
                    logger.debug("Blacklisted %s: %s", t, exc)
                else:
                    # Transient error — retry next scan
                    logger.debug("Ticker validation transient fail for %s: %s", t, exc)
        if len(valid) != len(tickers):
            self._save_bad_tickers()
            logger.info("Filtered %d invalid tickers", len(tickers) - len(valid))
        return valid

    def scan_gainers(self) -> list[ScannedStock]:
        """Fetch top gainers from Finviz, then get live data from Yahoo Finance."""
        tickers = self._scrape_finviz_tickers()
        if not tickers:
            logger.warning("No tickers scraped from Finviz")
            return []

        tickers = tickers[: self.max_results]
        logger.info("Scraped %d tickers from Finviz: %s", len(tickers), tickers)
        return self._fetch_market_data(tickers)

    def _scrape_finviz_tickers(
        self,
        url: str = FINVIZ_GAINERS_URL,
        validate: bool = True,
    ) -> list[str]:
        """Scrape ticker symbols from a Finviz screener page."""
        try:
            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                )
            }
            response = httpx.get(url, headers=headers, timeout=30, follow_redirects=True)
            response.raise_for_status()

            soup = BeautifulSoup(response.text, "lxml")

            # Find all ticker links anywhere on the page. Finviz has used
            # multiple URL shapes over time:
            #   old: quote.ashx?t=ASTC
            #   old: quote?t=ASTC
            #   new: stock?t=ASTC&ty=c&p=d&b=1
            # It also carries data-boxover-ticker on the ticker cell.
            tickers = []
            ticker_re = re.compile(r"(?:[?&]t=)([A-Z][A-Z0-9.]{0,7})(?:&|$)")
            for link in soup.find_all("a", href=True):
                href = link.get("href", "")
                ticker = ""
                if "quote?t=" in href or "quote.ashx?t=" in href or "stock?t=" in href:
                    match = ticker_re.search(href)
                    ticker = match.group(1) if match else link.text.strip()
                if (
                    ticker
                    and ticker.replace(".", "").isalnum()
                    and ticker.upper() == ticker
                    and 1 <= len(ticker) <= 5
                ):
                    tickers.append(ticker)

            for el in soup.find_all(attrs={"data-boxover-ticker": True}):
                ticker = (el.get("data-boxover-ticker") or "").strip().upper()
                if (
                    ticker
                    and ticker.replace(".", "").isalnum()
                    and 1 <= len(ticker) <= 5
                ):
                    tickers.append(ticker)

            # De-duplicate while preserving order
            seen = set()
            unique = []
            for t in tickers:
                if t not in seen:
                    seen.add(t)
                    unique.append(t)

            logger.info("Found %d tickers from Finviz", len(unique))
            if not validate:
                return unique
            return self._validate_tickers(unique)

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
