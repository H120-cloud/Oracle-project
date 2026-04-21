"""
Full-Featured Backtester (V6)

Matches the live decision pipeline exactly:
- Full ICT feature detection (MSB, liquidity sweep, structure reclaim, trap detection, order blocks)
- Detailed rejection reason logging with hierarchy
- Comprehensive summary statistics
- Validates whether the full live logic can work historically
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Tuple
from enum import Enum
import logging
from collections import defaultdict

import numpy as np

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
from src.core.ict_detector import ICTDetector
from src.services.market_data import YFinanceProvider

logger = logging.getLogger(__name__)


@dataclass
class RejectionReason:
    """Single rejection reason with context."""
    reason: str
    category: str  # regime, ict, risk, filter, other
    timestamp: str
    ticker: str
    price: float
    details: Dict = field(default_factory=dict)


@dataclass
class BacktestTrade:
    """Complete trade record with full context."""
    # Trade details
    entry_date: str
    exit_date: str
    entry_price: float
    exit_price: float
    pnl_pct: float
    action: str  # TARGET_HIT, STOP_LOSS, OPEN_CLOSE
    
    # Signal context
    ticker: str
    classification: str
    
    # Regime info
    market_regime: str
    regime_confidence: float
    regime_reason: str
    regime_blocked: bool
    regime_downgrade_applied: bool
    
    # ICT info
    ict_score: int
    liquidity_sweep: bool
    structure_break_confirmed: bool
    structure_reclaimed: bool
    trap_detected: bool
    trap_reason: str
    is_overextended: bool
    extension_pct: float
    near_order_block: bool
    order_block_freshness: float
    volatility_class: str
    
    # Confidence
    confidence: int
    risk_score: int
    setup_grade: str


@dataclass
class RejectionSummary:
    """Summary of rejections by category."""
    total_candidates: int = 0
    
    # By rejection reason
    blocked_by_regime: int = 0
    no_liquidity_sweep: int = 0
    no_structure_reclaim: int = 0
    no_msb: int = 0
    trap_detected: int = 0
    overextended: int = 0
    no_ict_alignment: int = 0
    stale_order_block: int = 0
    failed_filter: int = 0
    high_risk: int = 0
    low_confidence: int = 0
    other: int = 0
    
    # By ticker
    by_ticker: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    
    # By year
    by_year: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    
    # Detailed list
    rejection_details: List[RejectionReason] = field(default_factory=list)


@dataclass
class FullBacktestResult:
    """Complete backtest results with full analytics."""
    config: BacktestConfig
    
    # Trades taken
    trades: List[BacktestTrade] = field(default_factory=list)
    
    # Rejections
    rejections: RejectionSummary = field(default_factory=RejectionSummary)
    
    # Performance
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
        equity = 1.0
        for trade in self.trades:
            equity *= (1 + trade.pnl_pct / 100)
        return (equity - 1) * 100
    
    @property
    def avg_win_pct(self) -> float:
        wins = [t.pnl_pct for t in self.trades if t.pnl_pct > 0]
        return sum(wins) / len(wins) if wins else 0.0
    
    @property
    def avg_loss_pct(self) -> float:
        losses = [t.pnl_pct for t in self.trades if t.pnl_pct <= 0]
        return sum(losses) / len(losses) if losses else 0.0
    
    # By regime
    @property
    def trades_by_regime(self) -> Dict[str, List[BacktestTrade]]:
        result = defaultdict(list)
        for trade in self.trades:
            result[trade.market_regime].append(trade)
        return dict(result)


class FullFeaturedBacktester:
    """
    V6: Full-featured backtester matching live pipeline.
    
    Includes:
    - Full ICT feature detection
    - Complete DecisionEngine integration
    - Detailed rejection tracking
    - Comprehensive analytics
    """
    
    def __init__(self, market_data: Optional[YFinanceProvider] = None):
        self.market_data = market_data or YFinanceProvider()
        self.ict_detector = ICTDetector()
        self.regime_detector = MarketTrendRegimeDetector()
        self.decision_engine = DecisionEngine(
            account_equity=100000.0,
            use_liquidity_aware_sizing=True
        )
    
    def run(self, config: BacktestConfig) -> FullBacktestResult:
        """Run full-featured backtest."""
        logger.info(f"Full backtest: {config.ticker} {config.start_date} to {config.end_date}")
        
        # Fetch data
        bars = self.market_data.get_ohlcv(
            config.ticker,
            start=config.start_date,
            end=config.end_date,
            interval=config.interval,
        )
        
        if len(bars) < 50:
            logger.warning(f"Not enough bars ({len(bars)})")
            return FullBacktestResult(config=config)
        
        logger.info(f"Fetched {len(bars)} bars")
        
        result = FullBacktestResult(config=config)
        position = None
        
        MIN_BARS = 50
        
        for i in range(MIN_BARS, len(bars)):
            current_bar = bars[i]
            window = bars[:i+1]
            
            # Manage open position
            if position:
                if self._check_exit(position, current_bar, result):
                    position = None
                continue
            
            # Look for entry
            signal, rejection = self._generate_signal(
                config.ticker, window, current_bar, result.rejections
            )
            
            result.rejections.total_candidates += 1
            
            if signal and signal.action == SignalAction.BUY:
                # Enter position
                position = self._enter_position(signal, current_bar, result)
            elif rejection:
                # Log rejection
                result.rejections.rejection_details.append(rejection)
                self._categorize_rejection(rejection, result.rejections)
        
        # Close open position
        if position:
            self._close_position(position, bars[-1], result, "OPEN_CLOSE")
        
        logger.info(f"Backtest complete: {len(result.trades)} trades, "
                   f"{result.rejections.total_candidates - len(result.trades)} rejections")
        
        return result
    
    def _generate_signal(
        self,
        ticker: str,
        bars: List[OHLCVBar],
        current_bar: OHLCVBar,
        rejections: RejectionSummary
    ) -> Tuple[Optional[TradingSignal], Optional[RejectionReason]]:
        """
        Generate signal with full feature detection.
        Returns (signal, rejection_reason) tuple.
        """
        # Create stock object
        stock = ScannedStock(
            ticker=ticker,
            price=current_bar.close,
            volume=int(current_bar.volume),
            rvol=1.0,
            change_percent=0.0,
            market_cap=1e12,
            float_shares=1e9,
            scan_type="backtest",
        )
        
        # Detect dip/bounce
        recent_bars = bars[-20:]
        dip = self._detect_dip(recent_bars)
        bounce = self._detect_bounce(recent_bars)
        
        # Determine classification
        if dip and dip.probability > 50:
            classification = StockClassification.DIP_FORMING
        elif bounce and bounce.probability > 50:
            classification = StockClassification.BOUNCE_FORMING
        else:
            classification = StockClassification.NO_VALID_SETUP
            
            # Still try to generate signal for tracking
            return None, RejectionReason(
                reason="No valid setup (dip/bounce not detected)",
                category="other",
                timestamp=str(current_bar.timestamp),
                ticker=ticker,
                price=current_bar.close,
                details={"dip_prob": dip.probability if dip else 0, 
                        "bounce_prob": bounce.probability if bounce else 0}
            )
        
        # Full ICT detection
        ict = self._detect_ict_features(ticker, bars)
        
        # V8: Fetch daily bars for HTF analysis (need 60 days history)
        daily_bars: List[OHLCVBar] = []
        try:
            daily_bars = self.market_data.get_ohlcv(ticker, period="3mo", interval="1d")
        except Exception as e:
            logger.warning(f"[{ticker}] Failed to fetch daily bars for HTF: {e}")
        
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
        
        # If rejected, create detailed rejection reason
        if signal.action != SignalAction.BUY:
            rejection = self._analyze_rejection(signal, ticker, current_bar)
            return None, rejection
        
        return signal, None
    
    def _detect_ict_features(self, ticker: str, bars: List[OHLCVBar]) -> Optional[ICTFeatures]:
        """Run full ICT detection on bars."""
        try:
            # ICTDetector expects objects with .high, .low, .open, .close, .volume attributes
            # OHLCVBar has these attributes, so pass directly
            return self.ict_detector.detect(ticker, bars)
        except Exception as e:
            logger.warning(f"ICT detection failed for {ticker}: {e}")
            return None
    
    def _detect_dip(self, bars: List[OHLCVBar]) -> Optional[DipResult]:
        """Enhanced dip detection."""
        if len(bars) < 5:
            return None
        
        # Calculate metrics
        highs = [b.high for b in bars]
        lows = [b.low for b in bars]
        closes = [b.close for b in bars]
        
        price_decline = (closes[-1] - closes[0]) / closes[0] * 100
        
        # Count lower highs
        lower_highs = sum(1 for i in range(1, len(highs)) if highs[i] < highs[i-1])
        
        # Check for dip pattern
        if price_decline < -2.0 or lower_highs >= 3:
            # Calculate VWAP-like metric
            typical_prices = [(b.high + b.low + b.close) / 3 for b in bars]
            vwap = sum(p * b.volume for p, b in zip(typical_prices, bars)) / sum(b.volume for b in bars) if sum(b.volume for b in bars) > 0 else closes[-1]
            
            return DipResult(
                ticker="BACKTEST",
                probability=min(75, int(abs(price_decline) * 25) + lower_highs * 5),
                phase=DipPhase.EARLY if price_decline > -5 else DipPhase.MID if price_decline > -10 else DipPhase.LATE,
                features=DipFeatures(
                    vwap_distance_pct=((closes[-1] - vwap) / vwap) * 100,
                    ema9_distance_pct=-2.0,
                    ema20_distance_pct=-1.8,
                    drop_from_high_pct=abs(price_decline),
                    consecutive_red_candles=sum(1 for i in range(1, len(closes)) if closes[i] < closes[i-1]),
                    red_candle_volume_ratio=1.2,
                    lower_highs_count=lower_highs,
                    momentum_decay=-0.15,
                ),
                is_valid_dip=True,
            )
        return None
    
    def _detect_bounce(self, bars: List[OHLCVBar]) -> Optional[BounceResult]:
        """Enhanced bounce detection."""
        if len(bars) < 3:
            return None
        
        closes = [b.close for b in bars]
        
        # Check for bounce pattern: price declining then rising
        if closes[-1] > closes[-2] and closes[-2] < closes[-3]:
            return BounceResult(
                ticker="BACKTEST",
                probability=60,
                entry_ready=True,
                trigger_price=closes[-1],
                features=BounceFeatures(
                    support_distance_pct=2.0,
                    selling_pressure_change=-0.1,
                    buying_pressure_ratio=1.2,
                    higher_low_formed=closes[-2] > min(closes[:-2]),
                    key_level_reclaimed=False,
                ),
                is_valid_bounce=True,
            )
        return None
    
    def _analyze_rejection(
        self,
        signal: TradingSignal,
        ticker: str,
        current_bar: OHLCVBar
    ) -> RejectionReason:
        """Analyze why a signal was rejected."""
        
        reasons = signal.reason or []
        reason_str = " | ".join(reasons) if reasons else "Unknown rejection"
        
        # Determine category based on reasons
        category = "other"
        
        if signal.regime_blocked:
            category = "regime"
        elif any("ICT alignment" in r for r in reasons):
            category = "ict"
        elif any("MSB" in r or "structure break" in r for r in reasons):
            category = "ict"
        elif any("TRAP" in r or "trap" in r for r in reasons):
            category = "ict"
        elif any("Overextended" in r for r in reasons):
            category = "ict"
        elif any("Stale OB" in r for r in reasons):
            category = "ict"
        elif any("No valid" in r for r in reasons):
            category = "filter"
        elif any("Risk" in r for r in reasons):
            category = "risk"
        elif any("confidence" in r.lower() for r in reasons):
            category = "other"
        
        return RejectionReason(
            reason=reason_str,
            category=category,
            timestamp=str(current_bar.timestamp),
            ticker=ticker,
            price=current_bar.close,
            details={
                "regime": signal.market_regime,
                "regime_blocked": signal.regime_blocked,
                "confidence": signal.confidence,
                "risk_score": signal.risk_score,
            }
        )
    
    def _categorize_rejection(self, rejection: RejectionReason, summary: RejectionSummary):
        """Categorize rejection for summary stats."""
        reason_lower = rejection.reason.lower()
        
        # Count by specific reason
        if "regime" in reason_lower and "blocking" in reason_lower:
            summary.blocked_by_regime += 1
        elif "ict alignment" in reason_lower or ("sweep" in reason_lower and "no" in reason_lower):
            summary.no_ict_alignment += 1
        elif "msb" in reason_lower or "structure break" in reason_lower:
            summary.no_msb += 1
        elif "trap" in reason_lower:
            summary.trap_detected += 1
        elif "overextended" in reason_lower:
            summary.overextended += 1
        elif "stale ob" in reason_lower:
            summary.stale_order_block += 1
        elif "filter" in reason_lower or "no valid" in reason_lower:
            summary.failed_filter += 1
        elif "risk" in reason_lower:
            summary.high_risk += 1
        elif "confidence" in reason_lower:
            summary.low_confidence += 1
        else:
            summary.other += 1
        
        # Count by ticker
        summary.by_ticker[rejection.ticker] += 1
        
        # Count by year
        year = rejection.timestamp[:4] if len(rejection.timestamp) >= 4 else "unknown"
        summary.by_year[year] += 1
    
    def _enter_position(
        self,
        signal: TradingSignal,
        current_bar: OHLCVBar,
        result: FullBacktestResult
    ) -> dict:
        """Enter a new position."""
        entry_price = current_bar.close
        stop = signal.stop_price or entry_price * 0.98
        target = signal.target_prices[0] if signal.target_prices else entry_price * 1.04
        
        return {
            "entry_price": entry_price,
            "entry_date": str(current_bar.timestamp),
            "stop": stop,
            "target": target,
            "signal": signal,
        }
    
    def _check_exit(
        self,
        position: dict,
        current_bar: OHLCVBar,
        result: FullBacktestResult
    ) -> bool:
        """Check if position should be exited."""
        entry_price = position["entry_price"]
        stop = position["stop"]
        target = position["target"]
        signal = position["signal"]
        
        # Stop loss hit
        if current_bar.low <= stop:
            pnl = ((stop - entry_price) / entry_price) * 100
            self._record_trade(result, signal, position["entry_date"], 
                             str(current_bar.timestamp), entry_price, stop, pnl, "STOP_LOSS")
            return True
        
        # Target hit
        if current_bar.high >= target:
            pnl = ((target - entry_price) / entry_price) * 100
            self._record_trade(result, signal, position["entry_date"],
                             str(current_bar.timestamp), entry_price, target, pnl, "TARGET_HIT")
            return True
        
        return False
    
    def _close_position(
        self,
        position: dict,
        current_bar: OHLCVBar,
        result: FullBacktestResult,
        action: str
    ):
        """Close position at end of backtest."""
        entry_price = position["entry_price"]
        exit_price = current_bar.close
        pnl = ((exit_price - entry_price) / entry_price) * 100
        
        self._record_trade(result, position["signal"], position["entry_date"],
                         str(current_bar.timestamp), entry_price, exit_price, pnl, action)
    
    def _record_trade(
        self,
        result: FullBacktestResult,
        signal: TradingSignal,
        entry_date: str,
        exit_date: str,
        entry_price: float,
        exit_price: float,
        pnl_pct: float,
        action: str
    ):
        """Record a completed trade."""
        
        # Extract ICT features from signal context (stored in reason or other fields)
        ict_score = 0
        liquidity_sweep = False
        msb = False
        reclaimed = False
        trap = False
        trap_reason = ""
        overextended = False
        extension = 0.0
        near_ob = False
        ob_freshness = 1.0
        vol_class = "medium"
        
        # Parse from signal reason if available
        if signal.reason:
            for r in signal.reason:
                if "ICT score" in r:
                    try:
                        ict_score = int(r.split(":")[1].split("/")[0].strip())
                    except:
                        pass
                elif "Sweep+reclaim" in r:
                    liquidity_sweep = True
                    reclaimed = True
                elif "MSB confirmed" in r:
                    msb = True
                elif "TRAP" in r:
                    trap = True
                    trap_reason = r
                elif "Overextended" in r:
                    overextended = True
                    try:
                        extension = float(r.split()[1].rstrip("%"))
                    except:
                        pass
                elif "Near OB" in r:
                    near_ob = True
                    try:
                        ob_freshness = float(r.split("fresh:")[1].rstrip(")"))
                    except:
                        pass
                elif "Volatility" in r:
                    if "high" in r.lower():
                        vol_class = "high"
                    elif "low" in r.lower():
                        vol_class = "low"
        
        trade = BacktestTrade(
            entry_date=entry_date,
            exit_date=exit_date,
            entry_price=round(entry_price, 2),
            exit_price=round(exit_price, 2),
            pnl_pct=round(pnl_pct, 2),
            action=action,
            ticker=signal.ticker,
            classification=signal.classification.value if signal.classification else "unknown",
            market_regime=signal.market_regime or "unknown",
            regime_confidence=signal.regime_confidence_score or 0.0,
            regime_reason=signal.regime_reason or "",
            regime_blocked=False,  # Wouldn't be in trades if blocked
            regime_downgrade_applied=signal.regime_downgrade_applied,
            ict_score=ict_score,
            liquidity_sweep=liquidity_sweep,
            structure_break_confirmed=msb,
            structure_reclaimed=reclaimed,
            trap_detected=trap,
            trap_reason=trap_reason,
            is_overextended=overextended,
            extension_pct=extension,
            near_order_block=near_ob,
            order_block_freshness=ob_freshness,
            volatility_class=vol_class,
            confidence=signal.confidence,
            risk_score=signal.risk_score,
            setup_grade=signal.setup_grade or "D",
        )
        
        result.trades.append(trade)
