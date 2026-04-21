"""HTF-Aware Scanner — V9"""
import logging
from dataclasses import dataclass
from typing import List, Optional, Callable
from enum import Enum
from src.core.higher_timeframe_bias import HigherTimeframeBiasDetector, HTFBiasResult
from src.models.schemas import ScannedStock
from src.services.market_data import YFinanceProvider, IMarketDataProvider

logger = logging.getLogger(__name__)

class HTFFilterMode(Enum):
    INCLUDE_ALL = "include_all"
    PREFER_BULLISH = "prefer_htf_bullish"
    ONLY_BULLISH = "only_htf_bullish"
    INCLUDE_REVERSALS = "include_counter_trend_reversals"

@dataclass
class HTFScanResult:
    stocks: List[ScannedStock]
    htf_filter_mode: HTFFilterMode
    total_candidates: int
    blocked_by_htf: int
    boosted_by_htf: int

class HTFAwareScanner:
    """Wraps base scanner with HTF evaluation."""
    
    def __init__(self, base_scanner: Callable, market_data: Optional[IMarketDataProvider] = None):
        self.base_scanner = base_scanner
        self.market_data = market_data or YFinanceProvider()
        self.htf_detector = HigherTimeframeBiasDetector()
    
    def scan(self, htf_filter_mode: HTFFilterMode = HTFFilterMode.PREFER_BULLISH,
             min_htf_strength: float = 40.0, max_results: int = 20, **kwargs) -> HTFScanResult:
        """Run HTF-aware scan."""
        import time
        start = time.time()
        
        # Run base scanner
        base_results = self.base_scanner(**kwargs)
        if not base_results:
            return HTFScanResult([], htf_filter_mode, 0, 0, 0)
        
        # Evaluate HTF for each
        annotated = []
        for stock in base_results:
            try:
                daily_bars = self.market_data.get_ohlcv(stock.ticker, period="3mo", interval="1d")
                if len(daily_bars) >= 50:
                    htf = self.htf_detector.detect_bias(stock.ticker, daily_bars)
                    stock = self._annotate(stock, htf, min_htf_strength)
                else:
                    stock.scanner_htf_status = "NEUTRAL"
                    stock.scanner_htf_reason = "Insufficient data"
            except Exception as e:
                stock.scanner_htf_status = "NEUTRAL"
                stock.scanner_htf_reason = f"Error: {str(e)[:30]}"
            annotated.append(stock)
        
        # Apply filter
        filtered = self._filter(annotated, htf_filter_mode, min_htf_strength)
        blocked = sum(1 for s in filtered if s.scanner_htf_status == "BLOCKED")
        boosted = sum(1 for s in filtered if (s.htf_rank_boost or 0) > 0)
        
        # Sort by score + boost
        filtered.sort(key=lambda s: (s.final_score or 0) + (s.htf_rank_boost or 0), reverse=True)
        
        return HTFScanResult(
            stocks=filtered[:max_results],
            htf_filter_mode=htf_filter_mode,
            total_candidates=len(base_results),
            blocked_by_htf=blocked,
            boosted_by_htf=boosted
        )
    
    def _annotate(self, stock: ScannedStock, htf: Optional[HTFBiasResult], min_strength: float) -> ScannedStock:
        """Add HTF fields to stock."""
        if not htf:
            stock.htf_bias = "NEUTRAL"
            stock.htf_strength_score = 50.0
            stock.scanner_htf_status = "NEUTRAL"
            stock.htf_rank_boost = 0.0
            return stock
        
        stock.htf_bias = htf.bias.value
        stock.htf_strength_score = htf.strength_score
        stock.htf_structure_score = htf.structure_score
        stock.htf_ema_score = htf.ema_alignment_score
        stock.htf_momentum_score = htf.momentum_score
        stock.htf_adx_score = htf.adx_score
        
        # Determine status
        if htf.bias.value == "BULLISH" and htf.strength_score >= min_strength:
            stock.scanner_htf_status = "ALIGNED"
            stock.htf_rank_boost = 15.0 * (htf.strength_score / 100)
            stock.scanner_htf_reason = f"HTF BULLISH ({htf.strength_score:.0f}/100) - Boosted"
        elif htf.bias.value == "BEARISH":
            stock.scanner_htf_status = "BLOCKED"
            stock.htf_rank_boost = -20.0
            stock.scanner_htf_reason = f"HTF BEARISH ({htf.strength_score:.0f}/100) - Counter-trend long blocked"
        else:
            stock.scanner_htf_status = "NEUTRAL"
            stock.htf_rank_boost = 0.0
            stock.scanner_htf_reason = f"HTF {htf.bias.value} ({htf.strength_score:.0f}/100) - Neutral"
        
        stock.htf_alignment_readiness = "ready" if stock.scanner_htf_status == "ALIGNED" else "blocked"
        return stock
    
    def _filter(self, stocks: List[ScannedStock], mode: HTFFilterMode, min_strength: float) -> List[ScannedStock]:
        """Apply HTF filtering based on mode."""
        if mode == HTFFilterMode.INCLUDE_ALL:
            return stocks
        
        if mode == HTFFilterMode.ONLY_BULLISH:
            return [s for s in stocks if s.htf_bias == "BULLISH" and (s.htf_strength_score or 0) >= min_strength]
        
        if mode == HTFFilterMode.PREFER_BULLISH:
            # Keep all but bearish gets downranked (already in rank_boost)
            return [s for s in stocks if s.scanner_htf_status != "BLOCKED" or (s.htf_strength_score or 0) < 60]
        
        if mode == HTFFilterMode.INCLUDE_REVERSALS:
            # Allow BEARISH if strength is low (potential reversal)
            return [s for s in stocks if s.scanner_htf_status != "BLOCKED" or (s.htf_strength_score or 0) < 50]
        
        return stocks

def create_htf_aware_scanner(base_scanner, market_data=None):
    """Factory function to wrap any scanner with HTF awareness."""
    return HTFAwareScanner(base_scanner, market_data)
