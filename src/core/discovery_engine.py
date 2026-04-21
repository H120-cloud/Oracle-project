"""
Market Discovery Engine — feeds candidate tickers into the 19-layer scanner.

Modules:
1. Finviz broad universe (gainers, active, unusual volume)
2. News-based ticker discovery (Yahoo Finance RSS)
3. Premarket gap scanning
4. Market-wide stocks in play (RVOL + momentum)

Architecture rule: Discovery ONLY outputs a list of candidate tickers.
It does NOT run the 19-layer scanner — that's the caller's job.
"""

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

# ── Finviz URLs ──────────────────────────────────────────────────────────────

FINVIZ_URLS = {
    "gainers": "https://finviz.com/screener.ashx?v=111&s=ta_topgainers",
    "active": "https://finviz.com/screener.ashx?v=111&s=ta_mostactive",
    "unusual_volume": "https://finviz.com/screener.ashx?v=111&s=ta_unusualvolume",
    "new_high": "https://finviz.com/screener.ashx?v=111&s=ta_newhigh",
    "overbought": "https://finviz.com/screener.ashx?v=111&s=ta_overbought",
    "most_volatile": "https://finviz.com/screener.ashx?v=111&s=ta_mostvolatile",
    "under5_active": "https://finviz.com/screener.ashx?v=111&f=sh_curvol_o500000%2Csh_price_u5",
    "under2_volume": "https://finviz.com/screener.ashx?v=111&f=sh_curvol_o10000%2Csh_price_u2",
    "penny_movers": "https://finviz.com/screener.ashx?v=111&f=sh_curvol_o50000%2Csh_price_u1",
}

# ── Yahoo Finance News URL ──────────────────────────────────────────────────

YAHOO_NEWS_URL = "https://finance.yahoo.com/news/"
YAHOO_TRENDING_URL = "https://finance.yahoo.com/trending-tickers/"


@dataclass
class DiscoveredTicker:
    """A ticker discovered by a discovery module."""
    ticker: str
    source: str  # finviz_gainers, news, premarket_gap, rvol_spike, etc.
    reason: str  # why this ticker was discovered
    catalyst: Optional[str] = None
    gap_percent: Optional[float] = None
    volume_ratio: Optional[float] = None
    discovered_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class DiscoveryResult:
    """Aggregated discovery result."""
    tickers: list[str]
    details: list[DiscoveredTicker]
    stats: dict  # fetched, filtered, passed


class DiscoveryEngine:
    """
    Aggregates multiple discovery modules to produce a broad universe
    of candidate tickers for the 19-layer professional scanner.
    """

    def __init__(self, max_per_source: int = 50, max_total: int = 100):
        self.max_per_source = max_per_source
        self.max_total = max_total

    def discover(self, sources: list[str] = None) -> DiscoveryResult:
        """
        Run discovery across all specified sources.
        
        sources: list of source names. Default = all available.
            Options: finviz_gainers, finviz_active, finviz_unusual_volume,
                     finviz_volatile, finviz_penny, news, trending, premarket
        """
        if sources is None:
            sources = ["finviz_gainers", "finviz_active", "finviz_unusual_volume", "news"]
        
        logger.info(f"DiscoveryEngine.discover called with sources: {sources}")

        all_discovered: list[DiscoveredTicker] = []
        stats = {"sources_queried": len(sources), "fetched_per_source": {}}

        for source in sources:
            try:
                discovered = self._run_source(source)
                stats["fetched_per_source"][source] = len(discovered)
                all_discovered.extend(discovered)
                logger.info("Discovery [%s]: found %d tickers", source, len(discovered))
            except Exception as exc:
                logger.error("Discovery [%s] failed: %s", source, exc)
                stats["fetched_per_source"][source] = 0

        # De-duplicate by ticker, keeping first occurrence (preserves priority)
        seen = set()
        unique: list[DiscoveredTicker] = []
        for d in all_discovered:
            if d.ticker not in seen:
                seen.add(d.ticker)
                unique.append(d)

        # Cap total
        final = unique[: self.max_total]
        tickers = [d.ticker for d in final]

        stats["total_fetched"] = len(all_discovered)
        stats["unique_tickers"] = len(unique)
        stats["passed_to_scanner"] = len(final)

        logger.info(
            "Discovery complete: %d fetched, %d unique, %d passed to scanner",
            stats["total_fetched"], stats["unique_tickers"], stats["passed_to_scanner"],
        )

        return DiscoveryResult(tickers=tickers, details=final, stats=stats)

    def _run_source(self, source: str) -> list[DiscoveredTicker]:
        """Dispatch to appropriate discovery module."""
        logger.info(f"_run_source called with source: {source}")
        # Finviz sources
        finviz_map = {
            "finviz_gainers": ("gainers", "Top gainer on Finviz"),
            "finviz_active": ("active", "Most active on Finviz"),
            "finviz_unusual_volume": ("unusual_volume", "Unusual volume on Finviz"),
            "finviz_volatile": ("most_volatile", "Most volatile on Finviz"),
            "finviz_new_high": ("new_high", "New 52w high on Finviz"),
            "finviz_penny": ("penny_movers", "Penny stock mover on Finviz"),
            "finviz_under5": ("under5_active", "Active stock under $5 on Finviz"),
        }

        if source in finviz_map:
            url_key, reason = finviz_map[source]
            return self._discover_finviz(FINVIZ_URLS[url_key], source, reason)
        elif source == "news":
            return self._discover_from_news()
        elif source == "trending":
            return self._discover_trending()
        elif source == "premarket":
            return self._discover_premarket_gaps()
        elif source == "trading212_movers":
            return self._discover_trading212_movers()
        elif source == "trading212_popular":
            return self._discover_trading212_popular()
        else:
            logger.warning("Unknown discovery source: %s", source)
            return []

    # ── Finviz Discovery ─────────────────────────────────────────────────────

    def _discover_finviz(self, url: str, source: str, reason: str) -> list[DiscoveredTicker]:
        """Scrape tickers from a Finviz screener page."""
        try:
            response = httpx.get(url, headers=HEADERS, timeout=30)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "lxml")

            tickers = []
            for link in soup.find_all("a", href=True):
                href = link.get("href", "")
                if "quote.ashx?t=" in href:
                    ticker = link.text.strip()
                    if ticker and ticker.isalpha() and 1 <= len(ticker) <= 5:
                        tickers.append(ticker.upper())

            # De-duplicate
            seen = set()
            unique = []
            for t in tickers:
                if t not in seen:
                    seen.add(t)
                    unique.append(t)

            return [
                DiscoveredTicker(ticker=t, source=source, reason=reason)
                for t in unique[: self.max_per_source]
            ]

        except Exception as exc:
            logger.error("Finviz scrape failed [%s]: %s", source, exc)
            return []

    # ── News Discovery ───────────────────────────────────────────────────────

    def _discover_from_news(self) -> list[DiscoveredTicker]:
        """Extract tickers mentioned in Yahoo Finance news headlines."""
        discovered = []
        try:
            response = httpx.get(YAHOO_NEWS_URL, headers=HEADERS, timeout=30)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "lxml")

            # Extract headlines
            headlines = []
            for tag in soup.find_all(["h3", "h2", "a"]):
                text = tag.get_text(strip=True)
                if len(text) > 20:
                    headlines.append(text)

            # Extract tickers from headlines (look for $TICKER or known patterns)
            ticker_pattern = re.compile(r'\$([A-Z]{1,5})\b')
            # Also look for "TICKER:" or "(TICKER)" patterns
            paren_pattern = re.compile(r'\(([A-Z]{1,5})\)')
            colon_pattern = re.compile(r'\b([A-Z]{2,5}):\s')

            seen = set()
            for headline in headlines:
                for pattern in [ticker_pattern, paren_pattern, colon_pattern]:
                    matches = pattern.findall(headline)
                    for t in matches:
                        t = t.upper()
                        if t not in seen and len(t) >= 2 and t not in _COMMON_WORDS:
                            seen.add(t)
                            catalyst = _classify_catalyst(headline)
                            discovered.append(DiscoveredTicker(
                                ticker=t,
                                source="news",
                                reason=f"News mention: {headline[:80]}",
                                catalyst=catalyst,
                            ))

        except Exception as exc:
            logger.error("News discovery failed: %s", exc)

        return discovered[: self.max_per_source]

    # ── Trending Tickers ─────────────────────────────────────────────────────

    def _discover_trending(self) -> list[DiscoveredTicker]:
        """Fetch trending tickers from Yahoo Finance."""
        discovered = []
        try:
            response = httpx.get(YAHOO_TRENDING_URL, headers=HEADERS, timeout=30)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "lxml")

            # Look for ticker symbols in the trending table
            for link in soup.find_all("a", href=True):
                href = link.get("href", "")
                if "/quote/" in href:
                    ticker = href.split("/quote/")[-1].split("?")[0].split("/")[0]
                    ticker = ticker.upper().strip()
                    if ticker and ticker.isalpha() and 1 <= len(ticker) <= 5:
                        discovered.append(DiscoveredTicker(
                            ticker=ticker,
                            source="trending",
                            reason="Yahoo Finance trending ticker",
                        ))

        except Exception as exc:
            logger.error("Trending discovery failed: %s", exc)

        # De-duplicate
        seen = set()
        unique = []
        for d in discovered:
            if d.ticker not in seen:
                seen.add(d.ticker)
                unique.append(d)

        return unique[: self.max_per_source]

    # ── Premarket Gap Scanner ────────────────────────────────────────────────

    def _discover_premarket_gaps(self) -> list[DiscoveredTicker]:
        """
        Discover stocks with significant premarket gaps using Finviz.
        Uses the 'gap up' and 'gap down' screeners.
        """
        gap_up_url = "https://finviz.com/screener.ashx?v=111&s=ta_topgainers&f=sh_curvol_o100000"
        discovered = self._discover_finviz(gap_up_url, "premarket", "Premarket gap detected")
        
        # Tag with gap info
        for d in discovered:
            d.source = "premarket"
            d.reason = "Pre-market gap / mover"

        return discovered

    # ── Trading 212 Discovery ────────────────────────────────────────────────

    def _discover_trading212_movers(self) -> list[DiscoveredTicker]:
        """Fetch top movers from Trading 212 (or fallback to Yahoo/Finviz)."""
        discovered = []
        
        # Try multiple sources in order
        sources_to_try = [
            ("Yahoo Trending", "https://finance.yahoo.com/trending-tickers"),
            ("Yahoo Most Active", "https://finance.yahoo.com/most-active"),
            ("Yahoo Gainers", "https://finance.yahoo.com/gainers"),
        ]
        
        for source_name, url in sources_to_try:
            try:
                logger.info(f"Trying {source_name}: {url}")
                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.5",
                    "Accept-Encoding": "gzip, deflate, br",
                    "DNT": "1",
                    "Connection": "keep-alive",
                }
                response = httpx.get(url, headers=headers, timeout=30, follow_redirects=True)
                logger.info(f"Response status: {response.status_code}, length: {len(response.text)}")
                
                if response.status_code != 200:
                    continue
                    
                soup = BeautifulSoup(response.text, "html.parser")
                
                # Try multiple selector patterns
                rows = soup.find_all("tr", class_=re.compile(r"data-row"))
                if not rows:
                    rows = soup.find_all("tr", attrs={"data-test": "quote-list-item"})
                if not rows:
                    # Try finding any table rows with ticker symbols
                    all_rows = soup.find_all("tr")
                    rows = [r for r in all_rows if r.find("a", href=re.compile(r"/quote/"))]
                
                logger.info(f"Found {len(rows)} rows on {source_name}")
                
                if len(rows) == 0:
                    continue
                
                # Process rows
                for row in rows[:self.max_per_source]:
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
                        
                        if ticker and re.match(r'^[A-Z]{1,5}$', ticker) and ticker not in [d.ticker for d in discovered]:
                            discovered.append(DiscoveredTicker(
                                ticker=ticker,
                                source="trading212_movers",
                                reason=f"Top mover: {change_pct:+.2f}%",
                                gap_percent=change_pct,
                            ))
                
                logger.info(f"Discovered {len(discovered)} tickers from {source_name}")
                
                if len(discovered) >= 5:
                    break  # Got enough tickers, stop trying other sources
                    
            except Exception as exc:
                logger.error(f"{source_name} failed: {exc}")
                continue
        
        # Final fallback: use hardcoded popular tickers if nothing found
        if len(discovered) == 0:
            logger.warning("All Yahoo sources failed, using fallback popular tickers")
            fallback_tickers = ["AAPL", "MSFT", "GOOGL", "AMZN", "TSLA", "NVDA", "META", "NFLX", "AMD", "COIN"]
            for ticker in fallback_tickers:
                discovered.append(DiscoveredTicker(
                    ticker=ticker,
                    source="trading212_movers",
                    reason="Popular stock (fallback)",
                    gap_percent=0.0,
                ))
        
        logger.info(f"Total discovered: {len(discovered)} tickers")
        return discovered

    def _discover_trading212_popular(self) -> list[DiscoveredTicker]:
        """Fetch popular/most traded from Trading 212 (or fallback to Yahoo most active)."""
        discovered = []
        try:
            # Use Yahoo most active as proxy
            url = "https://finance.yahoo.com/most-active"
            response = httpx.get(url, headers=HEADERS, timeout=30)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "lxml")

            rows = soup.find_all("tr", class_=re.compile(r"data-row"))

            for row in rows[:self.max_per_source]:
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

                    if ticker and re.match(r'^[A-Z]{1,5}$', ticker):
                        discovered.append(DiscoveredTicker(
                            ticker=ticker,
                            source="trading212_popular",
                            reason=f"Trading 212 popular: {volume:,} volume",
                        ))

        except Exception as exc:
            logger.error("Trading 212 popular discovery failed: %s", exc)

        return discovered


# ── Helpers ──────────────────────────────────────────────────────────────────

# Common words that look like tickers but aren't
_COMMON_WORDS = {
    "THE", "FOR", "AND", "ARE", "BUT", "NOT", "YOU", "ALL", "CAN", "HER",
    "WAS", "ONE", "OUR", "OUT", "DAY", "GET", "HAS", "HIM", "HIS", "HOW",
    "ITS", "MAY", "NEW", "NOW", "OLD", "SEE", "WAY", "WHO", "BOY", "DID",
    "CEO", "CFO", "IPO", "SEC", "FDA", "USA", "GDP", "CPI", "ETF", "EPS",
    "NYSE", "GDP", "AI", "EV", "PE", "CEO", "UP", "IT", "US", "AT", "BY",
    "TO", "IN", "ON", "OR", "AN", "AS", "IS", "IF", "DO", "NO", "SO",
    "AM", "PM", "VS", "GO", "BE",
}


def _classify_catalyst(headline: str) -> str:
    """Classify a news headline into a catalyst tier."""
    headline_lower = headline.lower()

    # Tier 1 — high impact
    tier1_keywords = [
        "earnings", "revenue", "profit", "fda", "approval", "approved",
        "acquisition", "merger", "buyout", "legal", "lawsuit", "settlement",
        "contract", "billion", "million deal",
    ]
    for kw in tier1_keywords:
        if kw in headline_lower:
            return "tier_1"

    # Tier 2 — medium impact
    tier2_keywords = [
        "partnership", "analyst", "upgrade", "downgrade", "price target",
        "rating", "initiat", "coverage", "guidance", "forecast",
    ]
    for kw in tier2_keywords:
        if kw in headline_lower:
            return "tier_2"

    # Tier 3 — low impact
    return "tier_3"
