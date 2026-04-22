"""
Regime-Aware Backtester (V6)

Fully integrated backtester that:
1. Uses DecisionEngine with price bars for regime detection
2. Tracks regime classification for every trade
3. Records regime filter decisions (allowed/blocked)
4. Provides regime-based performance analytics

Goal: Prove whether regime filter improves results by reducing losing trades in bearish markets.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional, List, Dict
from enum import Enum
import logging

from src.models.schemas import (
    BacktestConfig,
    OHLCVBar,
    ScannedStock,
    StockClassification,
    DipResult,
    DipPhase,
    DipFeatures,
    BounceResult,
    BounceFeatures,
    ICTFeatures,
    VolumeProfileData,
    TradingSignal,
    SignalAction,
    MarketTrendRegime,
)
from src.core.decision_engine import DecisionEngine
from src.core.market_trend_regime_detector import MarketTrendRegimeDetector, RegimeFilterResult
from src.services.market_data import get_market_data_provider

logger = logging.getLogger(__name__)


@dataclass
class RegimeAwareBacktestTrade:
    """Extended trade record with full regime tracking."""
    # Basic trade info
    entry_date: str
    exit_date: str
    entry_price: float
    exit_price: float
    action: str  # TARGET_HIT, STOP_LOSS, OPEN_CLOSE
    pnl_pct: float
    
    # Regime classification at entry
    market_regime: str  # STRONG_TREND, CHOPPY, BEARISH
    regime_confidence_score: float
    regime_reason: str
    
    # Regime filter decisions
    regime_blocked: bool  # True if BEARISH regime blocked this trade
    regime_downgrade_applied: bool  # True if CHOPPY downgraded confidence
    
    # Confidence tracking
    confidence_before_regime: int  # Original confidence from risk scorer
    confidence_after_regime: int  # Final confidence after regime adjustment
    
    # Signal details
    signal_action: str  # What the signal actually was
    signal_reason: List[str] = field(default_factory=list)


@dataclass
class RegimePerformanceStats:
    """Performance statistics broken down by market regime."""
    regime: str
    total_signals: int = 0
    trades_allowed: int = 0
    trades_blocked: int = 0
    
    # Allowed trades performance
    winning_trades: int = 0
    losing_trades: int = 0
    total_return_pct: float = 0.0
    avg_trade_return: float = 0.0
    
    # Win rate for allowed trades
    @property
    def win_rate(self) -> float:
        total = self.winning_trades + self.losing_trades
        return (self.winning_trades / total * 100) if total > 0 else 0.0


@dataclass
class RegimeAwareBacktestResult:
    """Complete backtest results with regime analytics."""
    config: BacktestConfig
    
    # All trades with regime info
    trades: List[RegimeAwareBacktestTrade] = field(default_factory=list)
    
    # Regime breakdown
    strong_trend_stats: RegimePerformanceStats = field(
        default_factory=lambda: RegimePerformanceStats(regime="STRONG_TREND")
    )
    choppy_stats: RegimePerformanceStats = field(
        default_factory=lambda: RegimePerformanceStats(regime="CHOPPY")
    )
    bearish_stats: RegimePerformanceStats = field(
        default_factory=lambda: RegimePerformanceStats(regime="BEARISH")
    )
    
    # Overall totals
    total_signals_generated: int = 0
    total_trades_allowed: int = 0
    total_trades_blocked: int = 0
    
    @property
    def total_trades(self) -> int:
        return len(self.trades)
    
    @property
    def winning_trades(self) -> int:
        return sum(1 for t in self.trades if t.pnl_pct > 0)
    
    @property
    def losing_trades(self) -> int:
        return sum(1 for t in self.trades if t.pnl_pct <= 0)
    
    @property
    def win_rate(self) -> float:
        total = self.winning_trades + self.losing_trades
        return (self.winning_trades / total * 100) if total > 0 else 0.0
    
    @property
    def total_return_pct(self) -> float:
        if not self.trades:
            return 0.0
        # Compound return calculation
        equity = 1.0
        for trade in self.trades:
            equity *= (1 + trade.pnl_pct / 100)
        return (equity - 1) * 100
    
    @property
    def max_drawdown_pct(self) -> float:
        """Calculate max drawdown from equity curve."""
        if not self.trades:
            return 0.0
        
        equity = 1.0
        peak = equity
        max_dd = 0.0
        
        for trade in self.trades:
            equity *= (1 + trade.pnl_pct / 100)
            if equity > peak:
                peak = equity
            dd = (peak - equity) / peak * 100
            if dd > max_dd:
                max_dd = dd
        
        return max_dd
    
    @property
    def profit_factor(self) -> float:
        """Gross profits / Gross losses."""
        gross_profits = sum(t.pnl_pct for t in self.trades if t.pnl_pct > 0)
        gross_losses = abs(sum(t.pnl_pct for t in self.trades if t.pnl_pct <= 0))
        return gross_profits / gross_losses if gross_losses > 0 else 999.0
    
    def get_stats_by_regime(self, regime: str) -> RegimePerformanceStats:
        """Get stats for a specific regime."""
        if regime == "STRONG_TREND":
            return self.strong_trend_stats
        elif regime == "CHOPPY":
            return self.choppy_stats
        elif regime == "BEARISH":
            return self.bearish_stats
        return RegimePerformanceStats(regime=regime)


class RegimeAwareBacktester:
    """
    V6: Backtester that fully tests the regime filter.
    
    Uses DecisionEngine with real price bars to:
    - Generate signals with regime classification
    - Track which trades were blocked/allowed by regime filter
    - Compare performance across different market regimes
    """
    
    def __init__(self, market_data: Optional[IMarketDataProvider] = None):
        self.market_data = market_data or get_market_data_provider()
        self.regime_detector = MarketTrendRegimeDetector()
        
        # Initialize DecisionEngine
        self.decision_engine = DecisionEngine(
            account_equity=100000.0,
            use_liquidity_aware_sizing=True
        )
    
    def run(self, config: BacktestConfig) -> RegimeAwareBacktestResult:
        """
        Run a regime-aware backtest.
        
        For each bar, generate signals using DecisionEngine with full bars
        to enable regime detection.
        """
        logger.info(f"Starting regime-aware backtest: {config.ticker} {config.start_date} to {config.end_date}")
        
        # Fetch historical data
        bars = self.market_data.get_ohlcv(
            config.ticker,
            start=config.start_date,
            end=config.end_date,
            interval=config.interval,
        )
        
        if len(bars) < 50:
            logger.warning(f"Not enough bars ({len(bars)}) for backtest")
            return RegimeAwareBacktestResult(config=config)
        
        logger.info(f"Fetched {len(bars)} bars")
        
        # Initialize result
        result = RegimeAwareBacktestResult(config=config)
        
        # Simulate trading
        position = None  # (entry_price, entry_date, stop, target, entry_signal)
        equity = 100.0  # Start at 100 for percentage tracking
        
        MIN_BARS_NEEDED = 50  # Need enough bars for EMA50 calculation
        
        for i in range(MIN_BARS_NEEDED, len(bars)):
            current_bar = bars[i]
            
            # Get window for signal generation (last 50 bars up to current)
            window = bars[:i+1]
            
            # Check if in position
            if position:
                entry_price, entry_date, stop, target, entry_signal = position
                
                # Check stop loss
                if current_bar.low <= stop:
                    pnl_pct = ((stop - entry_price) / entry_price) * 100
                    
                    # Record trade with regime info from entry signal
                    self._record_trade(
                        result, entry_signal, entry_date, str(current_bar.timestamp),
                        entry_price, stop, pnl_pct, "STOP_LOSS"
                    )
                    
                    position = None
                    continue
                
                # Check target
                if current_bar.high >= target:
                    pnl_pct = ((target - entry_price) / entry_price) * 100
                    
                    self._record_trade(
                        result, entry_signal, entry_date, str(current_bar.timestamp),
                        entry_price, target, pnl_pct, "TARGET_HIT"
                    )
                    
                    position = None
                    continue
                
                # Still holding - check for time-based exit (optional)
                # For now, just continue holding
                continue
            
            # Not in position - look for entry signal
            # Generate signal using DecisionEngine with full bars
            signal = self._generate_signal(config.ticker, window, current_bar)
            result.total_signals_generated += 1
            
            # Track regime stats regardless of whether trade was taken
            if signal.market_regime:
                regime_stats = result.get_stats_by_regime(signal.market_regime)
                regime_stats.total_signals += 1
                
                if signal.regime_blocked:
                    regime_stats.trades_blocked += 1
                    result.total_trades_blocked += 1
                elif signal.action == SignalAction.BUY:
                    regime_stats.trades_allowed += 1
                    result.total_trades_allowed += 1
            
            # Take position if BUY signal
            if signal.action == SignalAction.BUY:
                entry_price = current_bar.close
                stop = entry_price * 0.98  # 2% stop
                target = entry_price * 1.04  # 4% target
                
                position = (entry_price, str(current_bar.timestamp), stop, target, signal)
        
        # Close any open position at last bar
        if position:
            entry_price, entry_date, _, _, entry_signal = position
            last_price = bars[-1].close
            pnl_pct = ((last_price - entry_price) / entry_price) * 100
            
            self._record_trade(
                result, entry_signal, entry_date, str(bars[-1].timestamp),
                entry_price, last_price, pnl_pct, "OPEN_CLOSE"
            )
        
        # Calculate regime-specific stats
        self._calculate_regime_stats(result)
        
        logger.info(f"Backtest complete: {len(result.trades)} trades, {result.win_rate:.1f}% win rate")
        
        return result
    
    def _generate_signal(
        self,
        ticker: str,
        bars: List[OHLCVBar],
        current_bar: OHLCVBar
    ) -> TradingSignal:
        """
        Generate trading signal using DecisionEngine with full bar history.
        This ensures regime detection works properly.
        """
        # Create minimal ScannedStock
        stock = ScannedStock(
            ticker=ticker,
            price=current_bar.close,
            volume=int(current_bar.volume),
            rvol=1.0,
            change_percent=((current_bar.close - bars[-2].close) / bars[-2].close * 100) if len(bars) > 1 else 0.0,
            market_cap=1e12,  # Default large cap
            float_shares=1e9,  # Default large float
            scan_type="backtest",  # Required field
        )
        
        # Simple dip/bounce detection
        recent_bars = bars[-10:]
        dip = self._detect_dip(recent_bars)
        bounce = self._detect_bounce(recent_bars)
        
        # Determine classification
        if dip and dip.probability > 50:
            classification = StockClassification.DIP_FORMING
        elif bounce and bounce.probability > 50:
            classification = StockClassification.BOUNCE_FORMING
        else:
            classification = StockClassification.DIP_BOUNCE_FORMING
        
        # Use DecisionEngine with full bars for regime detection
        # V8: Also pass daily_bars for HTF analysis (use same bars if interval is daily)
        daily_bars = bars if config.interval == "1d" else []
        signal = self.decision_engine.decide(
            stock=stock,
            classification=classification,
            dip=dip,
            bounce=bounce,
            ict=None,  # Simplified for backtest
            vol_profile=None,
            liquidity=None,
            bars=bars,  # Key: Pass full bars for regime detection
            daily_bars=daily_bars,  # V8: HTF analysis
        )
        
        return signal
    
    def _detect_dip(self, bars: List[OHLCVBar]) -> Optional[DipResult]:
        """Simple dip detection for backtesting."""
        if len(bars) < 5:
            return None
        
        # Check for recent decline
        price_decline = (bars[-1].close - bars[0].close) / bars[0].close * 100
        
        # If price dropped > 2% in recent bars, consider it a dip
        if price_decline < -2.0:
            return DipResult(
                ticker="BACKTEST",
                probability=min(70, int(abs(price_decline) * 20)),
                phase=DipPhase.EARLY,
                features=DipFeatures(
                    vwap_distance_pct=-1.5,
                    ema9_distance_pct=-2.0,
                    ema20_distance_pct=-1.8,
                    drop_from_high_pct=abs(price_decline),
                    consecutive_red_candles=3,
                    red_candle_volume_ratio=1.2,
                    lower_highs_count=sum(1 for i in range(1, len(bars)) if bars[i].high < bars[i-1].high),
                    momentum_decay=-0.15,
                ),
                is_valid_dip=True,
            )
        return None
    
    def _detect_bounce(self, bars: List[OHLCVBar]) -> Optional[BounceResult]:
        """Simple bounce detection for backtesting."""
        if len(bars) < 3:
            return None
        
        # Check for recent bounce
        if bars[-1].close > bars[-2].close and bars[-2].close < bars[-3].close:
            return BounceResult(
                ticker="BACKTEST",
                probability=55,
                entry_ready=True,
                trigger_price=bars[-1].close,
                features=BounceFeatures(
                    support_distance_pct=2.0,
                    selling_pressure_change=-0.1,
                    buying_pressure_ratio=1.2,
                    higher_low_formed=True,
                    key_level_reclaimed=False,
                ),
                is_valid_bounce=True,
            )
        return None
    
    def _record_trade(
        self,
        result: RegimeAwareBacktestResult,
        entry_signal: TradingSignal,
        entry_date: str,
        exit_date: str,
        entry_price: float,
        exit_price: float,
        pnl_pct: float,
        action: str
    ):
        """Record a trade with full regime tracking."""
        
        # Calculate confidence before/after regime
        confidence_before = entry_signal.confidence
        if entry_signal.regime_downgrade_applied:
            # Reverse the 20% downgrade to get original
            confidence_before = int(entry_signal.confidence / 0.80)
        
        trade = RegimeAwareBacktestTrade(
            entry_date=entry_date,
            exit_date=exit_date,
            entry_price=round(entry_price, 2),
            exit_price=round(exit_price, 2),
            action=action,
            pnl_pct=round(pnl_pct, 2),
            
            # Regime info
            market_regime=entry_signal.market_regime or "UNKNOWN",
            regime_confidence_score=entry_signal.regime_confidence_score or 0.0,
            regime_reason=entry_signal.regime_reason or "No regime data",
            
            # Regime filter decisions
            regime_blocked=entry_signal.regime_blocked,
            regime_downgrade_applied=entry_signal.regime_downgrade_applied,
            
            # Confidence tracking
            confidence_before_regime=confidence_before,
            confidence_after_regime=entry_signal.confidence,
            
            # Signal details
            signal_action=entry_signal.action.value,
            signal_reason=entry_signal.reason or [],
        )
        
        result.trades.append(trade)
        
        # Update regime-specific stats
        if entry_signal.market_regime:
            regime_stats = result.get_stats_by_regime(entry_signal.market_regime)
            
            if not entry_signal.regime_blocked and entry_signal.action == SignalAction.BUY:
                # This trade was allowed
                if pnl_pct > 0:
                    regime_stats.winning_trades += 1
                else:
                    regime_stats.losing_trades += 1
                
                regime_stats.total_return_pct += pnl_pct
    
    def _calculate_regime_stats(self, result: RegimeAwareBacktestResult):
        """Calculate final statistics for each regime."""
        for stats in [result.strong_trend_stats, result.choppy_stats, result.bearish_stats]:
            if stats.trades_allowed > 0:
                stats.avg_trade_return = stats.total_return_pct / stats.trades_allowed


