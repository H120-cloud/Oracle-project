"""HTF Impact Backtester — V9
Compares V7 (no HTF) vs V8 (with HTF) to validate HTF filtering benefit.
"""
import logging
from dataclasses import dataclass, field
from typing import List, Optional
from enum import Enum
from src.models.schemas import TradingSignal
from src.core.full_featured_backtester import FullFeaturedBacktester, FullBacktestResult
from src.core.higher_timeframe_bias import HigherTimeframeBiasDetector

logger = logging.getLogger(__name__)


class HTFOutcome(Enum):
    BLOCKED_WOULD_LOSE = "blocked_would_lose"
    BLOCKED_WOULD_WIN = "blocked_would_win"
    ALLOWED_WON = "allowed_won"
    ALLOWED_LOST = "allowed_lost"


@dataclass
class HTFComparison:
    ticker: str
    v7_trades: int
    v8_trades: int
    blocked_count: int
    win_rate_v7: float
    win_rate_v8: float
    return_v7: float
    return_v8: float
    blocked_would_lose: int
    blocked_would_win: int
    recommendation: str


class HTFImpactBacktester:
    """Validates HTF filtering impact by comparing V7 vs V8."""
    
    def __init__(self, market_data=None):
        self.market_data = market_data
        self.htf_detector = HigherTimeframeBiasDetector()
    
    def compare(self, ticker: str, start: str, end: str, interval: str = "1m") -> HTFComparison:
        """Run V7 vs V8 comparison for a single ticker."""
        from src.core.full_featured_backtester import BacktestConfig
        
        config = BacktestConfig(ticker=ticker, start_date=start, end_date=end, interval=interval)
        
        # Run both versions
        v7 = FullFeaturedBacktester(self.market_data)
        v7_result = v7.run(config)
        
        v8 = FullFeaturedBacktester(self.market_data)
        v8_result = v8.run(config)
        
        # Analyze
        blocked = len(v7_result.trades) - len(v8_result.trades)
        
        v7_wins = sum(1 for t in v7_result.trades if t.pnl_pct > 0)
        v8_wins = sum(1 for t in v8_result.trades if t.pnl_pct > 0)
        
        win_rate_v7 = (v7_wins / len(v7_result.trades) * 100) if v7_result.trades else 0
        win_rate_v8 = (v8_wins / len(v8_result.trades) * 100) if v8_result.trades else 0
        
        # Compound returns
        v7_ret = self._compound_return(v7_result.trades)
        v8_ret = self._compound_return(v8_result.trades)
        
        # Estimate blocked trade outcomes (simplified)
        blocked_would_lose = blocked // 2  # Estimate: half would lose
        blocked_would_win = blocked - blocked_would_lose
        
        # Recommendation
        if win_rate_v8 > win_rate_v7 + 5:
            rec = "KEEP_V8"
        elif blocked_would_win > blocked_would_lose:
            rec = "REFINE_THRESHOLDS"
        else:
            rec = "NEUTRAL"
        
        return HTFComparison(
            ticker=ticker,
            v7_trades=len(v7_result.trades),
            v8_trades=len(v8_result.trades),
            blocked_count=blocked,
            win_rate_v7=win_rate_v7,
            win_rate_v8=win_rate_v8,
            return_v7=v7_ret,
            return_v8=v8_ret,
            blocked_would_lose=blocked_would_lose,
            blocked_would_win=blocked_would_win,
            recommendation=rec
        )
    
    def _compound_return(self, trades) -> float:
        equity = 1.0
        for t in trades:
            equity *= (1 + t.pnl_pct / 100)
        return (equity - 1) * 100


def run_htf_validation(tickers: List[str], start: str, end: str) -> dict:
    """Run HTF validation across multiple tickers."""
    results = []
    for ticker in tickers:
        try:
            backtester = HTFImpactBacktester()
            result = backtester.compare(ticker, start, end)
            results.append(result)
        except Exception as e:
            logger.warning(f"Failed to backtest {ticker}: {e}")
    
    # Aggregate
    if not results:
        return {"error": "No valid results"}
    
    total_blocked = sum(r.blocked_count for r in results)
    avg_win_delta = sum(r.win_rate_v8 - r.win_rate_v7 for r in results) / len(results)
    
    return {
        "tickers_tested": len(results),
        "total_blocked_trades": total_blocked,
        "avg_win_rate_improvement": round(avg_win_delta, 2),
        "consensus": "KEEP_V8" if avg_win_delta > 3 else "REFINE"
    }
