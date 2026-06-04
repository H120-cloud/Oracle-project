"""
Agentic Ticker Validator — V1

Cross-checks "delisted" warnings from yfinance against StockTwits
public API before permanently blacklisting a ticker.

StockTwits search endpoint requires no API key for basic symbol lookup.
If a ticker exists on StockTwits, it is almost certainly still active/listed
(even if yfinance lacks intraday data for thinly-traded names).
"""

import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

STOCKTWITS_SEARCH = "https://api.stocktwits.com/api/2/search/symbols.json"
TIMEOUT = 5.0


def is_ticker_active_on_stocktwits(ticker: str) -> Optional[bool]:
    """
    Check whether a ticker exists on StockTwits.
    Returns:
        True  — symbol found (ticker is active)
        False — symbol not found (likely delisted / invalid)
        None  — network error / rate limit (inconclusive)
    """
    try:
        with httpx.Client(timeout=TIMEOUT) as client:
            r = client.get(
                STOCKTWITS_SEARCH,
                params={"q": ticker.upper()},
                headers={
                    "User-Agent": "Mozilla/5.0 (compatible; OracleScanner/1.0)",
                },
            )
            if r.status_code == 429:
                logger.debug("StockTwits rate limit for %s", ticker)
                return None
            if r.status_code != 200:
                logger.debug("StockTwits returned %s for %s", r.status_code, ticker)
                return None

            data = r.json()
            symbols = data.get("symbols", [])
            # StockTwits returns fuzzy matches — confirm exact ticker
            for sym in symbols:
                if sym.get("symbol", "").upper() == ticker.upper():
                    logger.debug("StockTwits confirms %s is active", ticker)
                    return True
            logger.debug("StockTwits: %s not found", ticker)
            return False

    except httpx.TimeoutException:
        logger.debug("StockTwits timeout for %s", ticker)
        return None
    except Exception as e:
        logger.debug("StockTwits error for %s: %s", ticker, e)
        return None


def validate_ticker_before_blacklist(ticker: str) -> bool:
    """
    Should a ticker be blacklisted after yfinance reported it as delisted?
    Returns True if the blacklist is justified (StockTwits also says it's gone).
    Returns False if we should NOT blacklist (StockTwits confirms it's active).
    """
    active = is_ticker_active_on_stocktwits(ticker)
    if active is True:
        logger.info(
            "Ticker %s flagged by yfinance but active on StockTwits — NOT blacklisting",
            ticker,
        )
        return False
    if active is False:
        logger.info(
            "Ticker %s not found on StockTwits either — safe to blacklist",
            ticker,
        )
        return True
    # Inconclusive (network error / rate limit) — be conservative, do NOT blacklist
    logger.info(
        "StockTwits inconclusive for %s — deferring blacklist decision",
        ticker,
    )
    return False


if __name__ == "__main__":
    # Quick sanity-check
    import sys
    t = sys.argv[1] if len(sys.argv) > 1 else "AAPL"
    result = is_ticker_active_on_stocktwits(t)
    print(f"StockTwits check for {t}: {result}")
