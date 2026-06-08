"""
Strategic Finviz discovery helpers for News Momentum and Pre-News.

This module owns the lightweight Finviz dependencies that strategic systems
need so they no longer import the legacy scanner route/service module.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import logging
import os
import re

import httpx
from bs4 import BeautifulSoup
import yfinance as yf

from src.utils.atomic_json import save_json_file
from src.utils.yfinance_cache import configure_yfinance_cache

configure_yfinance_cache(yf)

logger = logging.getLogger(__name__)

FINVIZ_GAINERS_URL = "https://finviz.com/screener?v=111&s=ta_topgainers"
FINVIZ_UNDER2_URL = "https://finviz.com/screener?v=111&f=sh_curvol_o10000%2Csh_price_u2"
FINVIZ_ACTIVE_URL = "https://finviz.com/screener?v=111&s=ta_mostactive"
FINVIZ_UNUSUAL_VOLUME_URL = "https://finviz.com/screener?v=111&s=ta_unusualvolume"
FINVIZ_MOST_VOLATILE_URL = "https://finviz.com/screener?v=111&s=ta_mostvolatile"
FINVIZ_UNDER5_ACTIVE_URL = "https://finviz.com/screener?v=111&f=sh_curvol_o500000%2Csh_price_u5"
FINVIZ_PENNY_MOVERS_URL = "https://finviz.com/screener?v=111&f=sh_curvol_o50000%2Csh_price_u1"

_BAD_TICKERS_PATH = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "data", "agentic", "bad_tickers.json")
)


@dataclass(frozen=True)
class FinvizMoverSnapshot:
    ticker: str
    price: float
    volume: float
    rvol: float | None = None
    change_percent: float | None = None
    market_cap: float | None = None
    float_shares: float | None = None
    source: str = "finviz_gainers"


def parse_finviz_tickers_from_html(html: str) -> list[str]:
    """Parse ticker symbols from current and historical Finviz markup."""
    soup = BeautifulSoup(html, "lxml")
    tickers: list[str] = []
    ticker_re = re.compile(r"(?:[?&]t=)([A-Z][A-Z0-9.]{0,7})(?:&|$)")

    for link in soup.find_all("a", href=True):
        href = link.get("href", "")
        ticker = ""
        if "quote?t=" in href or "quote.ashx?t=" in href or "stock?t=" in href:
            match = ticker_re.search(href)
            ticker = match.group(1) if match else link.text.strip()
        if _looks_like_ticker(ticker):
            tickers.append(ticker)

    for el in soup.find_all(attrs={"data-boxover-ticker": True}):
        ticker = (el.get("data-boxover-ticker") or "").strip().upper()
        if _looks_like_ticker(ticker):
            tickers.append(ticker)

    seen: set[str] = set()
    unique: list[str] = []
    for ticker in tickers:
        if ticker not in seen:
            seen.add(ticker)
            unique.append(ticker)
    return unique


def scrape_finviz_tickers(
    url: str = FINVIZ_GAINERS_URL,
    *,
    validate: bool = True,
) -> list[str]:
    """Fetch a Finviz screener page and return ticker symbols."""
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
        tickers = parse_finviz_tickers_from_html(response.text)
        logger.info("Found %d tickers from Finviz", len(tickers))
        return _validate_tickers(tickers) if validate else tickers
    except Exception as exc:
        logger.error("Failed to scrape Finviz: %s", exc)
        return []


def fetch_finviz_top_gainer_tickers(
    *,
    max_results: int | None = None,
    validate: bool = True,
) -> list[str]:
    tickers = scrape_finviz_tickers(FINVIZ_GAINERS_URL, validate=validate)
    return tickers[:max_results] if max_results else tickers


def fetch_finviz_under2_high_volume_tickers(
    *,
    max_results: int | None = None,
    validate: bool = True,
) -> list[str]:
    tickers = scrape_finviz_tickers(FINVIZ_UNDER2_URL, validate=validate)
    return tickers[:max_results] if max_results else tickers


def fetch_finviz_most_active_tickers(
    *,
    max_results: int | None = None,
    validate: bool = True,
) -> list[str]:
    tickers = scrape_finviz_tickers(FINVIZ_ACTIVE_URL, validate=validate)
    return tickers[:max_results] if max_results else tickers


def fetch_finviz_unusual_volume_tickers(
    *,
    max_results: int | None = None,
    validate: bool = True,
) -> list[str]:
    tickers = scrape_finviz_tickers(FINVIZ_UNUSUAL_VOLUME_URL, validate=validate)
    return tickers[:max_results] if max_results else tickers


def fetch_finviz_most_volatile_tickers(
    *,
    max_results: int | None = None,
    validate: bool = True,
) -> list[str]:
    tickers = scrape_finviz_tickers(FINVIZ_MOST_VOLATILE_URL, validate=validate)
    return tickers[:max_results] if max_results else tickers


def fetch_finviz_under5_active_tickers(
    *,
    max_results: int | None = None,
    validate: bool = True,
) -> list[str]:
    tickers = scrape_finviz_tickers(FINVIZ_UNDER5_ACTIVE_URL, validate=validate)
    return tickers[:max_results] if max_results else tickers


def fetch_finviz_penny_mover_tickers(
    *,
    max_results: int | None = None,
    validate: bool = True,
) -> list[str]:
    tickers = scrape_finviz_tickers(FINVIZ_PENNY_MOVERS_URL, validate=validate)
    return tickers[:max_results] if max_results else tickers


def fetch_finviz_top_gainers_snapshot(max_results: int = 30) -> list[FinvizMoverSnapshot]:
    """Fetch Finviz top gainers and enrich them with same-day market data."""
    tickers = fetch_finviz_top_gainer_tickers(max_results=max_results, validate=True)
    if not tickers:
        logger.warning("No tickers scraped from Finviz")
        return []
    return _fetch_market_snapshots(tickers)


def _looks_like_ticker(ticker: str) -> bool:
    ticker = (ticker or "").strip()
    return bool(
        ticker
        and ticker.replace(".", "").isalnum()
        and ticker.upper() == ticker
        and 1 <= len(ticker) <= 5
    )


def _load_bad_tickers() -> set[str]:
    try:
        if os.path.exists(_BAD_TICKERS_PATH):
            with open(_BAD_TICKERS_PATH, encoding="utf-8") as f:
                return set(json.load(f))
    except Exception as exc:
        logger.debug("Failed to load bad tickers: %s", exc)
    return set()


def _save_bad_tickers(tickers: set[str]) -> None:
    try:
        os.makedirs(os.path.dirname(_BAD_TICKERS_PATH), exist_ok=True)
        save_json_file(_BAD_TICKERS_PATH, sorted(tickers))
    except Exception as exc:
        logger.debug("Failed to save bad tickers: %s", exc)


def _validate_tickers(tickers: list[str]) -> list[str]:
    bad_tickers = _load_bad_tickers()
    valid: list[str] = []
    for ticker in tickers:
        if ticker in bad_tickers:
            continue
        try:
            hist = yf.Ticker(ticker).history(period="5d", interval="1d")
            if not hist.empty:
                valid.append(ticker)
            else:
                bad_tickers.add(ticker)
        except Exception as exc:
            err = str(exc).lower()
            if any(k in err for k in ("delisted", "not found", "invalid symbol", "no data found")):
                bad_tickers.add(ticker)
                logger.debug("Blacklisted %s: %s", ticker, exc)
            else:
                logger.debug("Ticker validation transient fail for %s: %s", ticker, exc)
    if len(valid) != len(tickers):
        _save_bad_tickers(bad_tickers)
        logger.info("Filtered %d invalid tickers", len(tickers) - len(valid))
    return valid


def _fetch_market_snapshots(tickers: list[str]) -> list[FinvizMoverSnapshot]:
    if not tickers:
        return []

    snapshots: list[FinvizMoverSnapshot] = []
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
                change_pct = ((price - open_price) / open_price) * 100 if open_price else 0
                avg_vol = getattr(info, "three_month_average_volume", None)
                rvol = volume / avg_vol if avg_vol and avg_vol > 0 else None

                snapshots.append(
                    FinvizMoverSnapshot(
                        ticker=symbol,
                        price=price,
                        volume=volume,
                        rvol=rvol,
                        change_percent=round(change_pct, 2),
                        market_cap=getattr(info, "market_cap", None),
                        float_shares=getattr(info, "shares", None),
                    )
                )
            except Exception as exc:
                logger.warning("Failed to fetch data for %s: %s", symbol, exc)
    except Exception as exc:
        logger.error("Failed to fetch market data batch: %s", exc)

    return snapshots
