"""
Live Trading Simulator (V6)

Real-time paper trading with WebSocket streaming:
- Connects to live market data feed
- Runs full decision pipeline on every tick/bar
- Simulates paper trades (no real money)
- Real-time regime classification
- Live performance tracking
- Detailed logging of all decisions

Usage:
    python live_trading_simulator.py --ticker AAPL --interval 5m --duration 60
"""

import asyncio
import json
import logging
import argparse
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from collections import deque
import sys
import time

# Add src to path
sys.path.insert(0, "src")

from src.models.schemas import (
    OHLCVBar,
    ScannedStock,
    StockClassification,
    DipResult,
    BounceResult,
    ICTFeatures,
    TradingSignal,
    SignalAction,
    MarketTrendRegime,
)
from src.core.decision_engine import DecisionEngine
from src.core.market_trend_regime_detector import MarketTrendRegimeDetector
from src.core.ict_detector import ICTDetector
from src.services.market_data import YFinanceProvider

logger = logging.getLogger(__name__)


@dataclass
class PaperTrade:
    """Paper trade record for simulation."""
    trade_id: str
    ticker: str
    entry_time: datetime
    entry_price: float
    exit_time: Optional[datetime] = None
    exit_price: Optional[float] = None
    shares: int = 0
    stop_price: float = 0.0
    target_price: float = 0.0
    pnl_pct: float = 0.0
    pnl_dollars: float = 0.0
    status: str = "OPEN"  # OPEN, CLOSED, STOPPED, TARGET
    
    # Signal context
    market_regime: str = ""
    ict_score: int = 0
    liquidity_sweep: bool = False
    msb_confirmed: bool = False
    confidence: int = 0
    
    def close(self, exit_price: float, exit_time: datetime, status: str):
        """Close the trade."""
        self.exit_price = exit_price
        self.exit_time = exit_time
        self.status = status
        self.pnl_pct = ((exit_price - self.entry_price) / self.entry_price) * 100
        self.pnl_dollars = self.shares * (exit_price - self.entry_price)


@dataclass
class LivePerformance:
    """Real-time performance metrics."""
    starting_capital: float = 100000.0
    current_equity: float = 100000.0
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    open_positions: int = 0
    
    # Track equity curve
    equity_history: List[tuple] = field(default_factory=list)
    
    @property
    def win_rate(self) -> float:
        closed = self.total_trades - self.open_positions
        return (self.winning_trades / closed * 100) if closed > 0 else 0.0
    
    @property
    def total_return_pct(self) -> float:
        return ((self.current_equity - self.starting_capital) / self.starting_capital) * 100
    
    @property
    def max_drawdown_pct(self) -> float:
        if not self.equity_history:
            return 0.0
        peak = self.starting_capital
        max_dd = 0.0
        for timestamp, equity in self.equity_history:
            if equity > peak:
                peak = equity
            dd = (peak - equity) / peak * 100
            if dd > max_dd:
                max_dd = dd
        return max_dd


class LiveTradingSimulator:
    """
    V6: Real-time paper trading simulator.
    
    Streams live data, runs full decision pipeline, simulates trades.
    """
    
    def __init__(
        self,
        ticker: str,
        interval: str = "5m",
        starting_capital: float = 100000.0,
        max_positions: int = 3,
        risk_per_trade_pct: float = 1.0
    ):
        self.ticker = ticker
        self.interval = interval
        self.starting_capital = starting_capital
        self.max_positions = max_positions
        self.risk_per_trade_pct = risk_per_trade_pct
        
        # Core components
        self.market_data = YFinanceProvider()
        self.ict_detector = ICTDetector()
        self.regime_detector = MarketTrendRegimeDetector()
        self.decision_engine = DecisionEngine(
            account_equity=starting_capital,
            use_liquidity_aware_sizing=True
        )
        
        # State
        self.price_history: deque = deque(maxlen=100)  # Keep last 100 bars
        self.open_trades: Dict[str, PaperTrade] = {}
        self.closed_trades: List[PaperTrade] = []
        self.performance = LivePerformance(starting_capital=starting_capital)
        self.running = False
        self.bar_count = 0
        
        # Stats
        self.signals_generated = 0
        self.signals_blocked = 0
        self.signals_passed = 0
    
    async def run(self, duration_minutes: int = 60):
        """
        Run live simulation for specified duration.
        
        In a real implementation, this would connect to a WebSocket
        for real-time tick data. For simulation, we poll yfinance.
        """
        print(f"\n{'='*80}")
        print(f"  LIVE PAPER TRADING SIMULATOR")
        print(f"  Ticker: {self.ticker}")
        print(f"  Interval: {self.interval}")
        print(f"  Duration: {duration_minutes} minutes")
        print(f"  Starting Capital: ${self.starting_capital:,.2f}")
        print(f"{'='*80}\n")
        
        self.running = True
        start_time = datetime.now()
        
        try:
            while self.running:
                elapsed = (datetime.now() - start_time).total_seconds() / 60
                if elapsed >= duration_minutes:
                    print(f"\n⏱️  Duration reached ({duration_minutes} min). Stopping...")
                    break
                
                # Fetch latest data (simulating WebSocket tick)
                await self._process_tick()
                
                # Update and display status
                if self.bar_count % 12 == 0:  # Every minute for 5m bars
                    self._print_status()
                
                # Wait for next interval
                await asyncio.sleep(5)  # Check every 5 seconds
                
        except KeyboardInterrupt:
            print("\n\n🛑 Stopped by user")
        finally:
            await self._shutdown()
    
    async def _process_tick(self):
        """Process a single market tick/bar."""
        try:
            # Fetch recent data (simulating live feed)
            # In real implementation, this would come from WebSocket
            bars = self.market_data.get_ohlcv(
                self.ticker,
                period="1d",
                interval=self.interval
            )
            
            if not bars or len(bars) < 2:
                return
            
            # Get latest bar
            latest_bar = bars[-1]
            
            # Check if this is a new bar
            if self.price_history and latest_bar.timestamp == self.price_history[-1].timestamp:
                return  # Same bar, skip
            
            self.price_history.append(latest_bar)
            self.bar_count += 1
            
            # Need enough history for regime detection
            if len(self.price_history) < 50:
                if self.bar_count % 10 == 0:
                    print(f"  ⏳ Building history... ({len(self.price_history)}/50 bars)")
                return
            
            # Update open positions
            self._check_open_positions(latest_bar)
            
            # Generate signal if we have capacity
            if len(self.open_trades) < self.max_positions:
                signal = self._generate_signal(list(self.price_history))
                
                if signal:
                    self.signals_generated += 1
                    
                    if signal.action == SignalAction.BUY:
                        self._enter_trade(signal, latest_bar)
                        self.signals_passed += 1
                    else:
                        self.signals_blocked += 1
                        if self.bar_count % 5 == 0:  # Log some rejections
                            self._log_rejection(signal, latest_bar)
            
        except Exception as e:
            logger.error(f"Error processing tick: {e}")
    
    def _generate_signal(self, bars: List[OHLCVBar]) -> Optional[TradingSignal]:
        """Generate trading signal from current bars."""
        current_bar = bars[-1]
        
        # Create stock object
        stock = ScannedStock(
            ticker=self.ticker,
            price=current_bar.close,
            volume=int(current_bar.volume),
            rvol=1.0,
            change_percent=0.0,
            market_cap=1e12,
            float_shares=1e9,
            scan_type="live",
        )
        
        # Detect patterns
        recent_bars = bars[-20:]
        dip = self._detect_dip(recent_bars)
        bounce = self._detect_bounce(recent_bars)
        
        # Determine classification
        if dip and dip.probability > 50:
            classification = StockClassification.DIP_FORMING
        elif bounce and bounce.probability > 50:
            classification = StockClassification.BOUNCE_FORMING
        else:
            classification = StockClassification.DIP_BOUNCE_FORMING
        
        # Full ICT detection
        ict = None
        try:
            ict = self.ict_detector.detect(self.ticker, bars)
        except Exception as e:
            logger.warning(f"ICT detection failed: {e}")
        
        # V8: Fetch daily bars for HTF analysis
        daily_bars: List[OHLCVBar] = []
        try:
            daily_bars = self.market_data.get_ohlcv(self.ticker, period="3mo", interval="1d")
        except Exception as e:
            logger.warning(f"Failed to fetch daily bars for HTF: {e}")
        
        # Run DecisionEngine
        signal = self.decision_engine.decide(
            stock=stock,
            classification=classification,
            dip=dip,
            bounce=bounce,
            ict=ict,
            vol_profile=None,
            liquidity=None,
            bars=bars,
            daily_bars=daily_bars,
        )
        
        return signal
    
    def _detect_dip(self, bars: List[OHLCVBar]) -> Optional[DipResult]:
        """Simple dip detection for live trading."""
        if len(bars) < 5:
            return None
        
        price_decline = (bars[-1].close - bars[0].close) / bars[0].close * 100
        lower_highs = sum(1 for i in range(1, len(bars)) if bars[i].high < bars[i-1].high)
        
        if price_decline < -2.0 or lower_highs >= 3:
            return DipResult(
                ticker=self.ticker,
                probability=min(75, int(abs(price_decline) * 25) + lower_highs * 5),
                phase=DipPhase.EARLY,
                features=DipFeatures(
                    vwap_distance_pct=-1.5,
                    ema9_distance_pct=-2.0,
                    ema20_distance_pct=-1.8,
                    drop_from_high_pct=abs(price_decline),
                    consecutive_red_candles=sum(1 for i in range(1, len(bars)) if bars[i].close < bars[i-1].close),
                    red_candle_volume_ratio=1.2,
                    lower_highs_count=lower_highs,
                    momentum_decay=-0.15,
                ),
                is_valid_dip=True,
            )
        return None
    
    def _detect_bounce(self, bars: List[OHLCVBar]) -> Optional[BounceResult]:
        """Simple bounce detection for live trading."""
        if len(bars) < 3:
            return None
        
        if bars[-1].close > bars[-2].close and bars[-2].close < bars[-3].close:
            return BounceResult(
                ticker=self.ticker,
                probability=60,
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
    
    def _enter_trade(self, signal: TradingSignal, bar: OHLCVBar):
        """Enter a new paper trade."""
        trade_id = f"{self.ticker}-{datetime.now().strftime('%H%M%S')}"
        
        # Calculate position size based on risk
        risk_amount = self.performance.current_equity * (self.risk_per_trade_pct / 100)
        stop_distance = abs(bar.close - signal.stop_price) if signal.stop_price else bar.close * 0.02
        
        if stop_distance > 0:
            shares = int(risk_amount / stop_distance)
        else:
            shares = int(self.performance.current_equity * 0.01 / bar.close)
        
        # Limit to max 10% of equity
        max_shares = int(self.performance.current_equity * 0.10 / bar.close)
        shares = min(shares, max_shares)
        
        if shares < 1:
            return
        
        trade = PaperTrade(
            trade_id=trade_id,
            ticker=self.ticker,
            entry_time=datetime.now(),
            entry_price=bar.close,
            shares=shares,
            stop_price=signal.stop_price or bar.close * 0.98,
            target_price=signal.target_prices[0] if signal.target_prices else bar.close * 1.04,
            market_regime=signal.market_regime or "unknown",
            ict_score=signal.ict_score if hasattr(signal, 'ict_score') else 0,
            confidence=signal.confidence,
        )
        
        self.open_trades[trade_id] = trade
        self.performance.open_positions = len(self.open_trades)
        
        # Deduct from equity
        cost = shares * bar.close
        self.performance.current_equity -= cost
        
        print(f"\n  🟢 ENTER: {self.ticker} @ ${bar.close:.2f}")
        print(f"     Shares: {shares} | Stop: ${trade.stop_price:.2f} | Target: ${trade.target_price:.2f}")
        print(f"     Regime: {trade.market_regime} | Confidence: {signal.confidence}%")
        if signal.reason:
            print(f"     Reason: {signal.reason[0] if signal.reason else 'N/A'}")
    
    def _check_open_positions(self, bar: OHLCVBar):
        """Check if any open positions should be closed."""
        closed = []
        
        for trade_id, trade in self.open_trades.items():
            # Check stop loss
            if bar.low <= trade.stop_price:
                trade.close(trade.stop_price, datetime.now(), "STOPPED")
                closed.append(trade_id)
                self._log_trade_close(trade, "STOP LOSS")
            
            # Check target
            elif bar.high >= trade.target_price:
                trade.close(trade.target_price, datetime.now(), "TARGET")
                closed.append(trade_id)
                self._log_trade_close(trade, "TARGET HIT")
        
        # Remove closed trades
        for trade_id in closed:
            trade = self.open_trades.pop(trade_id)
            self.closed_trades.append(trade)
            self.performance.total_trades += 1
            
            if trade.pnl_pct > 0:
                self.performance.winning_trades += 1
            else:
                self.performance.losing_trades += 1
            
            # Update equity
            self.performance.current_equity += trade.shares * trade.exit_price
        
        self.performance.open_positions = len(self.open_trades)
    
    def _log_trade_close(self, trade: PaperTrade, reason: str):
        """Log trade closure."""
        emoji = "🟢" if trade.pnl_pct > 0 else "🔴"
        print(f"\n  {emoji} EXIT: {trade.ticker} @ ${trade.exit_price:.2f} | {reason}")
        print(f"     P&L: {trade.pnl_pct:+.2f}% (${trade.pnl_dollars:+.2f})")
        print(f"     Duration: {str(datetime.now() - trade.entry_time).split('.')[0]}")
    
    def _log_rejection(self, signal: TradingSignal, bar: OHLCVBar):
        """Log signal rejection."""
        if signal.regime_blocked:
            print(f"\n  🚫 BLOCKED: {self.ticker} @ ${bar.close:.2f} | Regime: {signal.market_regime}")
        elif signal.reason:
            reason = signal.reason[0] if signal.reason else "Unknown"
            if "ICT" in reason or "MSB" in reason or "sweep" in reason.lower():
                print(f"\n  ⚠️  REJECTED: {self.ticker} @ ${bar.close:.2f} | {reason[:60]}")
    
    def _print_status(self):
        """Print current status."""
        if not self.price_history:
            return
        
        latest = self.price_history[-1]
        
        # Calculate current equity (including open positions)
        current_value = self.performance.current_equity
        for trade in self.open_trades.values():
            current_value += trade.shares * latest.close
        
        # Update equity history
        self.performance.equity_history.append((datetime.now(), current_value))
        
        # Print status line
        pnl = current_value - self.starting_capital
        pnl_pct = (pnl / self.starting_capital) * 100
        
        print(f"\n  📊 Status | Price: ${latest.close:.2f} | "
              f"Equity: ${current_value:,.2f} ({pnl_pct:+.2f}%) | "
              f"Open: {len(self.open_trades)} | "
              f"Closed: {len(self.closed_trades)} | "
              f"Win Rate: {self.performance.win_rate:.1f}%")
        
        if self.open_trades:
            for trade in self.open_trades.values():
                unrealized = ((latest.close - trade.entry_price) / trade.entry_price) * 100
                print(f"     📈 {trade.trade_id}: ${trade.entry_price:.2f} → ${latest.close:.2f} "
                      f"({unrealized:+.2f}% | Target: ${trade.target_price:.2f})")
    
    async def _shutdown(self):
        """Clean shutdown."""
        print(f"\n{'='*80}")
        print(f"  SIMULATION COMPLETE")
        print(f"{'='*80}\n")
        
        # Close all open positions at current price
        if self.open_trades and self.price_history:
            current_price = self.price_history[-1].close
            print(f"  Closing {len(self.open_trades)} open positions at ${current_price:.2f}\n")
            
            for trade in list(self.open_trades.values()):
                trade.close(current_price, datetime.now(), "SIMULATION_END")
                self._log_trade_close(trade, "SIMULATION END")
                self.closed_trades.append(trade)
                self.performance.total_trades += 1
                if trade.pnl_pct > 0:
                    self.performance.winning_trades += 1
                else:
                    self.performance.losing_trades += 1
        
        # Final summary
        self._print_final_summary()
    
    def _print_final_summary(self):
        """Print final performance summary."""
        print(f"\n{'='*80}")
        print(f"  FINAL PERFORMANCE SUMMARY")
        print(f"{'='*80}\n")
        
        # Calculate final equity
        final_equity = self.performance.current_equity
        if self.open_trades and self.price_history:
            for trade in self.open_trades.values():
                final_equity += trade.shares * self.price_history[-1].close
        
        total_return = final_equity - self.starting_capital
        total_return_pct = (total_return / self.starting_capital) * 100
        
        print(f"  Starting Capital: ${self.starting_capital:,.2f}")
        print(f"  Final Equity:     ${final_equity:,.2f}")
        print(f"  Total Return:     ${total_return:+.2f} ({total_return_pct:+.2f}%)")
        print(f"  Max Drawdown:     {self.performance.max_drawdown_pct:.2f}%")
        print(f"\n  Total Trades:     {self.performance.total_trades}")
        print(f"  Winning Trades:   {self.performance.winning_trades}")
        print(f"  Losing Trades:    {self.performance.losing_trades}")
        print(f"  Win Rate:         {self.performance.win_rate:.1f}%")
        
        print(f"\n  Signals Generated: {self.signals_generated}")
        print(f"  Signals Passed:    {self.signals_passed}")
        print(f"  Signals Blocked:   {self.signals_blocked}")
        
        if self.closed_trades:
            avg_win = sum(t.pnl_pct for t in self.closed_trades if t.pnl_pct > 0) / \
                     max(1, sum(1 for t in self.closed_trades if t.pnl_pct > 0))
            avg_loss = sum(t.pnl_pct for t in self.closed_trades if t.pnl_pct <= 0) / \
                      max(1, sum(1 for t in self.closed_trades if t.pnl_pct <= 0))
            
            print(f"\n  Average Win:      {avg_win:+.2f}%")
            print(f"  Average Loss:     {avg_loss:+.2f}%")
        
        print(f"\n{'='*80}\n")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Live Paper Trading Simulator")
    parser.add_argument("--ticker", default="AAPL", help="Stock ticker to trade")
    parser.add_argument("--interval", default="5m", help="Bar interval (1m, 5m, 15m, 1h)")
    parser.add_argument("--duration", type=int, default=60, help="Duration in minutes")
    parser.add_argument("--capital", type=float, default=100000.0, help="Starting capital")
    parser.add_argument("--max-positions", type=int, default=3, help="Max concurrent positions")
    
    args = parser.parse_args()
    
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Create and run simulator
    simulator = LiveTradingSimulator(
        ticker=args.ticker,
        interval=args.interval,
        starting_capital=args.capital,
        max_positions=args.max_positions
    )
    
    try:
        asyncio.run(simulator.run(duration_minutes=args.duration))
    except KeyboardInterrupt:
        print("\n\nShutdown complete.")


if __name__ == "__main__":
    main()
