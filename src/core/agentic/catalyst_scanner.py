"""
Agentic Discovery Engine — Part 2

Scans for catalyst-driven momentum candidates from:
- Finviz news feed (already integrated)
- Stock Titan news feed (stocktitan.net)
- Unusual volume (RVOL) screening
- Premarket gappers

Reuses Oracle's existing FinvizNewsScraper, adds StockTitanScraper.
"""

import json
import logging
import os
import re
from datetime import datetime, timezone, timedelta
from typing import Optional

from src.utils.atomic_json import save_json_file

import yfinance as yf

from src.core.finviz_news import FinvizNewsScraper
from src.core.stocktitan_news import StockTitanScraper
from src.services.market_data import get_market_data_provider
from src.core.agentic.models import (
    CatalystInfo, CatalystType, AgenticCandidate,
)

logger = logging.getLogger(__name__)

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "..", "data", "agentic")

# Pre-filter regex: skip foreign OTC (ends in F/FF), SPAC units (U), warrants (W/WS)
_SKIP_TICKER_RE = re.compile(
    r"^[A-Z]{2,5}(F|FF|U|WS|W)$",  # e.g. UNFYF, EDVMF, HCAXU, GCGRW
    re.IGNORECASE,
)

# ── Catalyst keyword classification ──────────────────────────────────────────

CATALYST_KEYWORDS: dict[CatalystType, list[str]] = {
    CatalystType.SEC_FILING: ["sec filing", "pre 14a", "8-k", "s-1", "s-3", "10-k", "10-q", "proxy", "13f", "13d"],
    CatalystType.SPAC_EXTENSION: ["spac", "extension", "merger deadline", "trust", "redemption", "business combination", "de-spac"],
    CatalystType.MERGER: ["merger", "acquisition", "buyout", "takeover", "deal", "combined entity"],
    CatalystType.LEGAL_PATENT: ["patent", "lawsuit", "settlement", "ruling", "court", "litigation", "fda approval"],
    CatalystType.FDA: ["fda", "approval", "clinical trial", "phase 3", "phase 2", "drug", "therapeutic"],
    CatalystType.CONTRACT: ["contract", "partnership", "agreement", "awarded", "defense contract"],
    CatalystType.EARNINGS: ["earnings", "revenue", "eps", "guidance", "beat", "miss", "quarterly"],
    CatalystType.OFFERING: ["offering", "dilution", "shares registered", "shelf registration", "atm"],
}

CATALYST_STRENGTH: dict[CatalystType, float] = {
    CatalystType.FDA: 85,
    CatalystType.MERGER: 80,
    CatalystType.SPAC_EXTENSION: 70,
    CatalystType.SEC_FILING: 65,
    CatalystType.LEGAL_PATENT: 65,
    CatalystType.CONTRACT: 60,
    CatalystType.EARNINGS: 55,
    CatalystType.OFFERING: 30,  # Often dilutive — bearish catalyst
    CatalystType.OTHER: 40,
}


def classify_catalyst(headline: str) -> tuple[CatalystType, float]:
    """Classify a news headline into a catalyst type and base strength."""
    h = headline.lower()
    for cat_type, keywords in CATALYST_KEYWORDS.items():
        for kw in keywords:
            if kw in h:
                return cat_type, CATALYST_STRENGTH[cat_type]
    return CatalystType.OTHER, CATALYST_STRENGTH[CatalystType.OTHER]


def compute_catalyst_freshness(discovered_at: datetime) -> float:
    """Freshness score: 100 = just discovered, decays over 4 hours."""
    age_minutes = (datetime.now(timezone.utc) - discovered_at).total_seconds() / 60
    if age_minutes < 15:
        return 100.0
    if age_minutes < 60:
        return max(0, 100 - (age_minutes - 15) * 1.5)
    if age_minutes < 240:
        return max(0, 35 - (age_minutes - 60) * 0.15)
    return 0.0


class CatalystScanner:
    """
    Discovers catalyst-momentum candidates by combining:
    1. Finviz news for fresh headlines with tickers
    2. Stock Titan news for additional catalyst coverage
    3. Live market data for RVOL and gap checks
    """

    def __init__(self):
        self._news_scraper = FinvizNewsScraper()
        self._stocktitan_scraper = StockTitanScraper()
        self._provider = get_market_data_provider()
        # Cache tickers that yfinance can't resolve to skip on future scans
        self._bad_tickers: set[str] = set()
        self._load_bad_tickers()

    def scan(self, min_change_pct: float = 5.0, min_rvol: float = 2.0) -> list[AgenticCandidate]:
        """
        Scan for catalyst candidates.

        Returns a list of AgenticCandidate with catalyst info populated.
        Downstream engines fill in float, momentum, second_leg, etc.
        """
        candidates: dict[str, AgenticCandidate] = {}

        # ── 1. News-driven discovery (Finviz + Stock Titan) ────────────
        all_items = []
        try:
            news_summary = self._news_scraper.fetch_all_sync()
            all_items.extend(news_summary.news_items + news_summary.blog_items)
            logger.info("CatalystScanner: %d items from Finviz", len(news_summary.news_items) + len(news_summary.blog_items))
        except Exception as e:
            logger.error("CatalystScanner Finviz scan failed: %s", e)

        try:
            st_summary = self._stocktitan_scraper.fetch_all_sync()
            all_items.extend(st_summary.news_items)
            logger.info("CatalystScanner: %d items from StockTitan", len(st_summary.news_items))
        except Exception as e:
            logger.error("CatalystScanner StockTitan scan failed: %s", e)

        # Deduplicate across sources before processing
        try:
            from src.core.agentic.news_momentum_utils import deduplicate_news_items
            all_items = deduplicate_news_items(all_items)
            logger.info("CatalystScanner: %d items after deduplication", len(all_items))
        except Exception as e:
            logger.debug("CatalystScanner deduplication failed: %s", e)

        try:
            for item in all_items:
                if not item.tickers:
                    continue

                cat_type, base_strength = classify_catalyst(item.headline)
                freshness = compute_catalyst_freshness(
                    item.timestamp or datetime.now(timezone.utc)
                )
                # Boost strength by freshness
                strength = min(100, base_strength * (0.5 + 0.5 * freshness / 100))

                for ticker in item.tickers:
                    ticker = ticker.upper().strip()
                    if not ticker or len(ticker) > 5:
                        continue
                    if ticker in candidates:
                        # Keep strongest catalyst
                        if strength > candidates[ticker].catalyst.strength_score:
                            candidates[ticker].catalyst = CatalystInfo(
                                catalyst_type=cat_type,
                                headline=item.headline,
                                source=item.source or "",
                                url=item.url or "",
                                discovered_at=item.timestamp or datetime.now(timezone.utc),
                                freshness_minutes=freshness,
                                strength_score=strength,
                                sentiment=item.sentiment,
                            )
                    else:
                        cand = AgenticCandidate(ticker=ticker)
                        cand.catalyst = CatalystInfo(
                            catalyst_type=cat_type,
                            headline=item.headline,
                            source=item.source or "",
                            url=item.url or "",
                            discovered_at=item.timestamp or datetime.now(timezone.utc),
                            freshness_minutes=freshness,
                            strength_score=strength,
                            sentiment=item.sentiment,
                        )
                        candidates[ticker] = cand
        except Exception as e:
            logger.error("CatalystScanner news scan failed: %s", e)

        # ── 2. Live market filter: only keep stocks with real moves ──────
        result = []
        for ticker, cand in candidates.items():
            if ticker in self._bad_tickers:
                continue
            # Pre-filter: skip foreign OTC, SPAC units, warrants
            if _SKIP_TICKER_RE.match(ticker):
                self._bad_tickers.add(ticker)
                continue
            try:
                # Use the configured provider for real-time price data
                quote = self._provider.get_live_quote(ticker)
                price = float(quote.get("price", 0) or 0)
                prev_close = float(quote.get("previous_close", 0) or 0)
                volume = float(quote.get("volume", 0) or 0)
                day_high = float(quote.get("day_high", 0) or 0)

                if price <= 0 or prev_close <= 0:
                    self._bad_tickers.add(ticker)
                    continue

                # Use premarket price if available and more recent
                pm_data = quote.get("premarket", {})
                pm_high = float(pm_data.get("high", 0) or 0)
                if pm_high > 0 and pm_high > day_high:
                    day_high = pm_high

                change_pct = float(quote.get("change_pct", 0) or 0)
                if change_pct == 0 and prev_close > 0:
                    change_pct = ((price - prev_close) / prev_close) * 100

                # Get avg volume + float data from yfinance (providers don't have these)
                avg_volume = 0.0
                market_cap = float(quote.get("market_cap", 0) or 0)
                shares_out = 0.0
                try:
                    fi = yf.Ticker(ticker).fast_info
                    avg_volume = float(getattr(fi, "ten_day_average_volume", 0) or 0)
                    if market_cap == 0:
                        market_cap = float(getattr(fi, "market_cap", 0) or 0)
                    shares_out = float(getattr(fi, "shares", 0) or 0)
                except Exception:
                    pass

                rvol = (volume / avg_volume) if avg_volume > 0 else 0

                # Filter: must have a meaningful price reaction
                if abs(change_pct) < min_change_pct and rvol < min_rvol:
                    continue

                cand.last_price = price
                cand.last_volume = volume
                cand.momentum.price = price
                cand.momentum.high_of_day = day_high if day_high > 0 else price

                # Pre-populate float_intel with fast_info data
                cand.float_intel.market_cap = market_cap
                cand.float_intel.shares_outstanding = shares_out

                result.append(cand)

            except Exception as e:
                logger.debug("CatalystScanner skip %s: %s", ticker, e)
                # Only permanently cache as bad if error clearly indicates invalid/delisted ticker.
                # Transient network/timeout/yfinance errors should NOT blacklist a valid ticker.
                err_str = str(e).lower()
                if any(kw in err_str for kw in ("delisted", "not found", "invalid symbol", "no data found", "symbol may be")):
                    # Cross-check with StockTwits before permanently blacklisting
                    from src.core.agentic.ticker_validator import validate_ticker_before_blacklist
                    if validate_ticker_before_blacklist(ticker):
                        self._bad_tickers.add(ticker)
                        logger.info("CatalystScanner: cached %s as bad ticker (%s)", ticker, e)
                    else:
                        logger.info("CatalystScanner: %s flagged by yfinance but active on StockTwits — skipping blacklist", ticker)
                continue

        logger.info("CatalystScanner: %d news tickers → %d candidates after market filter (skipped %d bad)", len(candidates), len(result), len(self._bad_tickers))
        self._save_bad_tickers()
        return result

    # ── Bad ticker persistence ────────────────────────────────────────────────

    def _load_bad_tickers(self):
        try:
            path = os.path.join(DATA_DIR, "bad_tickers.json")
            if os.path.exists(path):
                with open(path) as f:
                    self._bad_tickers = set(json.load(f))
                logger.info("CatalystScanner: loaded %d cached bad tickers", len(self._bad_tickers))
        except Exception as exc:
            logger.debug("Failed to load bad tickers: %s", exc)

    def _save_bad_tickers(self):
        try:
            os.makedirs(DATA_DIR, exist_ok=True)
            path = os.path.join(DATA_DIR, "bad_tickers.json")
            save_json_file(path, sorted(self._bad_tickers))
        except Exception as exc:
            logger.debug("Failed to save bad tickers: %s", exc)
