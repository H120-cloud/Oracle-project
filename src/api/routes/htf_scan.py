"""HTF-Aware Scan API Routes — V9"""
from fastapi import APIRouter, Query

router = APIRouter(prefix="/htf-scan", tags=["V9 HTF Scanner"])


@router.post("/run")
def htf_aware_scan(
    mode: str = Query("prefer_bullish", enum=["prefer_bullish", "only_bullish", "include_reversals"]),
    max_results: int = Query(15, ge=5, le=30),
    min_htf_strength: float = Query(40.0, ge=0, le=100),
):
    """V9: Run HTF-aware professional scan."""
    from src.core.htf_aware_scanner import HTFAwareScanner, HTFFilterMode
    from src.core.professional_scanner import ProfessionalScanner
    from src.services.market_data import YFinanceProvider
    
    mode_map = {
        "prefer_bullish": HTFFilterMode.PREFER_BULLISH,
        "only_bullish": HTFFilterMode.ONLY_BULLISH,
        "include_reversals": HTFFilterMode.INCLUDE_REVERSALS,
    }
    
    universe = ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "TSLA", "META", "NFLX", "AMD"]
    
    scanner = HTFAwareScanner(
        lambda: ProfessionalScanner(max_results=30).scan_universe(universe),
        YFinanceProvider()
    )
    
    result = scanner.scan(
        htf_filter_mode=mode_map.get(mode, HTFFilterMode.PREFER_BULLISH),
        min_htf_strength=min_htf_strength,
        max_results=max_results
    )
    
    return {
        "scan_mode": mode,
        "total_candidates": result.total_candidates,
        "htf_blocked": result.blocked_by_htf,
        "htf_boosted": result.boosted_by_htf,
        "stocks": [
            {
                "ticker": s.ticker,
                "price": s.price,
                "htf_bias": s.htf_bias,
                "htf_strength": s.htf_strength_score,
                "htf_status": s.scanner_htf_status,
                "htf_reason": s.scanner_htf_reason,
                "rank_boost": s.htf_rank_boost,
                "final_score": (s.final_score or 0) + (s.htf_rank_boost or 0),
            }
            for s in result.stocks
        ]
    }


@router.get("/status")
def htf_scanner_status():
    """Get HTF scanner status."""
    return {
        "status": "active",
        "version": "V9",
        "features": [
            "htf_aware_scanning",
            "bias_classification",
            "strength_scoring",
            "rank_boosting",
            "counter_trend_filtering"
        ],
        "modes": ["prefer_bullish", "only_bullish", "include_reversals"]
    }
