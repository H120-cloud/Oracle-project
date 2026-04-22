"""
Scanner API routes — scan market for active stocks.
"""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from src.db.session import get_db
from src.core.finviz_scanner import FinvizScanner
from src.core.scanner import MarketScanner
from src.core.professional_scanner import ProfessionalScanner, to_scanned_stock
from src.core.discovery_engine import DiscoveryEngine
from src.models.schemas import ScanFilter, ScanResponse
from src.services.market_data import get_market_data_provider

router = APIRouter(prefix="/scanner", tags=["scanner"])


@router.get("/volume", response_model=ScanResponse)
def scan_by_volume(
    min_price: float = Query(1.0),
    max_price: float = Query(500.0),
    min_volume: int = Query(500_000),
    max_results: int = Query(20),
):
    """Scan top stocks by raw volume."""
    provider = get_market_data_provider()
    df = provider.get_scan_universe()
    scanner = MarketScanner(
        ScanFilter(
            min_price=min_price,
            max_price=max_price,
            min_volume=min_volume,
            max_results=max_results,
        )
    )
    stocks = scanner.scan_top_volume(df)
    return ScanResponse(stocks=stocks, scanned_at=datetime.utcnow(), scan_type="volume")


@router.get("/rvol", response_model=ScanResponse)
def scan_by_rvol(
    min_price: float = Query(1.0),
    max_price: float = Query(500.0),
    min_volume: int = Query(500_000),
    max_results: int = Query(20),
):
    """Scan top stocks by relative volume."""
    provider = get_market_data_provider()
    df = provider.get_scan_universe()
    scanner = MarketScanner(
        ScanFilter(
            min_price=min_price,
            max_price=max_price,
            min_volume=min_volume,
            max_results=max_results,
        )
    )
    stocks = scanner.scan_top_rvol(df)
    return ScanResponse(stocks=stocks, scanned_at=datetime.utcnow(), scan_type="rvol")


@router.get("/gainers", response_model=ScanResponse)
def scan_by_gainers(
    min_price: float = Query(1.0),
    max_price: float = Query(500.0),
    min_volume: int = Query(500_000),
    max_results: int = Query(20),
):
    """Scan top % gainers."""
    provider = get_market_data_provider()
    df = provider.get_scan_universe()
    scanner = MarketScanner(
        ScanFilter(
            min_price=min_price,
            max_price=max_price,
            min_volume=min_volume,
            max_results=max_results,
        )
    )
    stocks = scanner.scan_top_gainers(df)
    return ScanResponse(stocks=stocks, scanned_at=datetime.utcnow(), scan_type="gainers")


@router.get("/finviz", response_model=ScanResponse)
def scan_finviz_gainers(
    max_results: int = Query(20),
):
    """Scan top gainers from Finviz."""
    scanner = FinvizScanner(max_results=max_results)
    stocks = scanner.scan_gainers()
    return ScanResponse(stocks=stocks, scanned_at=datetime.utcnow(), scan_type="finviz_gainers")


@router.get("/finviz-under2", response_model=ScanResponse)
def scan_finviz_under_2(
    max_results: int = Query(30),
):
    """Scan stocks under $2 from Finviz (volume >10k)."""
    scanner = FinvizScanner(max_results=max_results)
    stocks = scanner.scan_under_2()
    return ScanResponse(stocks=stocks, scanned_at=datetime.utcnow(), scan_type="finviz_under2")


@router.get("/professional", response_model=ScanResponse)
def scan_professional(
    universe: str = Query("default", description="Stock universe: default, finviz, penny, discovery, all"),
    max_results: int = Query(15, description="Max results to return"),
):
    """
    Professional-grade stock discovery scan with 19-layer analysis.
    
    Universes:
      - default: hardcoded large-cap list (~30 tickers)
      - finviz: Finviz top gainers (~50 tickers)
      - penny: Finviz penny + under-$5 movers
      - discovery: Full discovery engine (gainers + active + unusual volume + news)
      - all: Every discovery source combined (~100+ tickers)
    """
    from src.services.market_data import DEFAULT_SCAN_UNIVERSE
    import logging
    log = logging.getLogger("scanner.professional")

    # Phase 1: Get universe via discovery engine
    if universe == "discovery":
        engine = DiscoveryEngine(max_per_source=40, max_total=80)
        result = engine.discover(["finviz_gainers", "finviz_active", "finviz_unusual_volume", "news"])
        tickers = result.tickers
        log.info("Discovery stats: %s", result.stats)
    elif universe == "all":
        engine = DiscoveryEngine(max_per_source=30, max_total=120)
        result = engine.discover([
            "finviz_gainers", "finviz_active", "finviz_unusual_volume",
            "finviz_volatile", "finviz_penny", "news", "trending",
        ])
        tickers = result.tickers
        log.info("Full discovery stats: %s", result.stats)
    elif universe == "finviz":
        finviz = FinvizScanner(max_results=50)
        tickers = [s.ticker for s in finviz.scan_gainers()]
    elif universe == "penny":
        engine = DiscoveryEngine(max_per_source=40, max_total=60)
        result = engine.discover(["finviz_penny", "finviz_under5"])
        tickers = result.tickers
    else:
        tickers = DEFAULT_SCAN_UNIVERSE[:30]

    log.info("Professional scan: %d tickers in universe '%s'", len(tickers), universe)

    # Phase 2: Run 19-layer scanner on discovered tickers
    scanner = ProfessionalScanner(max_results=max_results)
    professional_stocks = scanner.scan_universe(tickers)

    # Convert to ScannedStock format
    stocks = [to_scanned_stock(s) for s in professional_stocks]

    log.info("Professional scan complete: %d results from %d candidates", len(stocks), len(tickers))

    return ScanResponse(
        stocks=stocks,
        scanned_at=datetime.utcnow(),
        scan_type=f"professional_{universe}",
    )


@router.get("/discover")
def discover_tickers(
    sources: str = Query("finviz_gainers,finviz_active,news", description="Comma-separated sources"),
    max_total: int = Query(80, description="Max tickers to return"),
):
    """
    Run discovery engine only — returns candidate tickers without 19-layer analysis.
    Useful for previewing what the discovery engine finds before running full scan.
    """
    source_list = [s.strip() for s in sources.split(",") if s.strip()]
    engine = DiscoveryEngine(max_per_source=40, max_total=max_total)
    result = engine.discover(source_list)

    return {
        "tickers": result.tickers,
        "count": len(result.tickers),
        "stats": result.stats,
        "details": [
            {
                "ticker": d.ticker,
                "source": d.source,
                "reason": d.reason,
                "catalyst": d.catalyst,
            }
            for d in result.details
        ],
    }


@router.get("/discover/trading212")
def discover_trading212(
    type: str = Query("movers", description="Type: movers or popular"),
    max_total: int = Query(20, description="Max tickers to return"),
):
    """
    Discover stocks from Trading 212 top movers or popular stocks.
    Uses Yahoo Finance as fallback since Trading 212 blocks scraping.
    """
    from src.core.discovery_engine import DiscoveryEngine
    import logging
    logger = logging.getLogger(__name__)

    logger.info(f"Trading 212 API called: type={type}, max_total={max_total}")
    source = "trading212_movers" if type == "movers" else "trading212_popular"
    engine = DiscoveryEngine(max_per_source=20, max_total=max_total)
    result = engine.discover([source])
    logger.info(f"Trading 212 discovery result: {len(result.tickers)} tickers, {len(result.details)} details")
    logger.info(f"Trading 212 raw details: {[d.ticker for d in result.details]}")

    return {
        "source": "trading212",
        "type": type,
        "tickers": result.tickers,
        "count": len(result.tickers),
        "details": [
            {
                "ticker": d.ticker,
                "reason": d.reason,
                "gap_percent": d.gap_percent,
            }
            for d in result.details
        ],
    }
