"""
Broker Execution Service — V10

Executes trades via Alpaca paper trading API.
Converts TradingSignal BUY actions into real paper orders with:
  - Market or limit orders
  - Bracket orders (entry + stop + take-profit)
  - Position tracking
  - Order status monitoring

Also works as a standalone paper-trade simulator when no API keys are set.
"""

import os
import logging
import json
from datetime import datetime
from dataclasses import dataclass, field, asdict
from typing import Optional, List, Dict
from pathlib import Path
from enum import Enum

from src.core.trailing_stop import TrailingStopEngine, TrailingStopState

logger = logging.getLogger(__name__)

# Lazy import
_alpaca_available = False
try:
    from alpaca.trading.client import TradingClient
    from alpaca.trading.requests import (
        MarketOrderRequest,
        LimitOrderRequest,
        StopLossRequest,
        TakeProfitRequest,
    )
    from alpaca.trading.enums import OrderSide, TimeInForce, OrderType
    _alpaca_available = True
except ImportError:
    pass


class OrderStatus(str, Enum):
    PENDING = "pending"
    FILLED = "filled"
    PARTIALLY_FILLED = "partially_filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


@dataclass
class PaperOrder:
    """Record of a paper trade order."""
    order_id: str
    ticker: str
    side: str  # "buy" or "sell"
    qty: int
    order_type: str  # "market", "limit", "bracket"
    limit_price: Optional[float] = None
    stop_price: Optional[float] = None
    take_profit_price: Optional[float] = None
    status: str = "pending"
    filled_price: Optional[float] = None
    filled_at: Optional[str] = None
    created_at: str = ""
    signal_confidence: Optional[float] = None
    signal_grade: Optional[str] = None
    htf_bias: Optional[str] = None
    reason: Optional[str] = None


@dataclass
class PaperPosition:
    """Tracks an open paper position."""
    ticker: str
    qty: int
    entry_price: float
    entry_date: str
    stop_price: float
    target_prices: List[float]
    current_price: float = 0.0
    unrealized_pnl: float = 0.0
    unrealized_pnl_pct: float = 0.0
    signal_confidence: float = 0.0
    signal_grade: str = ""
    htf_bias: Optional[str] = None
    # Trailing stop state
    initial_stop: float = 0.0
    atr_at_entry: float = 0.0
    highest_price_reached: float = 0.0
    moved_to_breakeven: bool = False
    trailing_active: bool = False


@dataclass
class ClosedTrade:
    """Record of a completed trade with P/L."""
    ticker: str
    side: str
    qty: int
    entry_price: float
    exit_price: float
    entry_date: str
    exit_date: str
    pnl_dollars: float
    pnl_pct: float
    hold_duration_minutes: int
    exit_reason: str  # "stop_loss", "breakeven", "trailing_stop", "target", "time_exit", "manual"
    signal_confidence: float = 0.0
    signal_grade: str = ""
    htf_bias: Optional[str] = None
    # Trailing stop tracking
    moved_to_breakeven: bool = False
    trailing_activated: bool = False
    highest_price_reached: float = 0.0
    max_r_reached: float = 0.0
    realized_r: float = 0.0


class BrokerService:
    """
    Paper trading broker that can optionally connect to Alpaca.
    
    Without Alpaca keys: simulates trades locally with JSON persistence.
    With Alpaca keys: executes real paper trades on Alpaca.
    """

    def __init__(self, use_alpaca: bool = False, data_dir: str = None):
        self.use_alpaca = use_alpaca and _alpaca_available
        self.trading_client = None
        # Support env var override for Railway volume mount (/app/data)
        data_dir = data_dir or os.getenv("PAPER_TRADING_DATA_DIR", "data/paper_trading")
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # Local state
        self.orders: List[PaperOrder] = []
        self.positions: Dict[str, PaperPosition] = {}
        self.closed_trades: List[ClosedTrade] = []
        self._order_counter = 0
        self._trailing_states: Dict[str, TrailingStopState] = {}
        self._ts_engine = TrailingStopEngine()

        # Load existing state
        self._load_state()

        if self.use_alpaca:
            try:
                api_key = os.getenv("ALPACA_API_KEY", "")
                secret_key = os.getenv("ALPACA_SECRET_KEY", "")
                if api_key and secret_key:
                    self.trading_client = TradingClient(
                        api_key=api_key,
                        secret_key=secret_key,
                        paper=True,
                    )
                    logger.info("BrokerService: Connected to Alpaca paper trading")
                else:
                    logger.warning("BrokerService: No Alpaca keys, using local simulation")
                    self.use_alpaca = False
            except Exception as e:
                logger.warning("BrokerService: Alpaca init failed (%s), using local", e)
                self.use_alpaca = False

        mode = "Alpaca paper" if self.use_alpaca else "Local simulation"
        logger.info("BrokerService initialized: %s, %d open positions, %d closed trades",
                     mode, len(self.positions), len(self.closed_trades))

    # ------------------------------------------------------------------
    # Order execution
    # ------------------------------------------------------------------

    def execute_signal(self, signal) -> Optional[PaperOrder]:
        """
        Convert a TradingSignal into a paper order.
        Only executes BUY signals with sufficient confidence.
        """
        from src.models.schemas import SignalAction

        if signal.action != SignalAction.BUY:
            logger.debug("Skipping non-BUY signal for %s", signal.ticker)
            return None

        if signal.confidence < 50:
            logger.info("Skipping low-confidence signal for %s (%.0f%%)", 
                       signal.ticker, signal.confidence)
            return None

        # Don't double up on positions
        if signal.ticker in self.positions:
            logger.info("Already have position in %s, skipping", signal.ticker)
            return None

        qty = signal.position_size_shares or 10  # Default 10 shares
        entry = signal.entry_price
        stop = signal.stop_price
        targets = signal.target_prices or []

        if self.use_alpaca and self.trading_client:
            return self._execute_alpaca(signal, qty, entry, stop, targets)
        else:
            return self._execute_local(signal, qty, entry, stop, targets)

    def _execute_alpaca(self, signal, qty, entry, stop, targets) -> Optional[PaperOrder]:
        """Execute via Alpaca paper trading API."""
        try:
            order_request = MarketOrderRequest(
                symbol=signal.ticker,
                qty=qty,
                side=OrderSide.BUY,
                time_in_force=TimeInForce.DAY,
            )
            order = self.trading_client.submit_order(order_request)

            paper_order = PaperOrder(
                order_id=str(order.id),
                ticker=signal.ticker,
                side="buy",
                qty=qty,
                order_type="market",
                stop_price=stop,
                take_profit_price=targets[0] if targets else None,
                status="filled",
                filled_price=entry,
                filled_at=datetime.utcnow().isoformat(),
                created_at=datetime.utcnow().isoformat(),
                signal_confidence=signal.confidence,
                signal_grade=signal.setup_grade,
                htf_bias=getattr(signal, 'htf_bias', None),
                reason=f"Alpaca paper order submitted",
            )

            self.orders.append(paper_order)
            self._open_position(paper_order, stop, targets, signal)
            self._save_state()

            logger.info("ALPACA ORDER: %s %d shares of %s @ ~$%.2f",
                       "BUY", qty, signal.ticker, entry)
            return paper_order

        except Exception as e:
            logger.error("Alpaca order failed for %s: %s", signal.ticker, e)
            return None

    def _execute_local(self, signal, qty, entry, stop, targets) -> Optional[PaperOrder]:
        """Simulate order execution locally."""
        self._order_counter += 1
        order_id = f"LOCAL-{self._order_counter:06d}"

        paper_order = PaperOrder(
            order_id=order_id,
            ticker=signal.ticker,
            side="buy",
            qty=qty,
            order_type="market",
            limit_price=None,
            stop_price=stop,
            take_profit_price=targets[0] if targets else None,
            status="filled",
            filled_price=entry,
            filled_at=datetime.utcnow().isoformat(),
            created_at=datetime.utcnow().isoformat(),
            signal_confidence=signal.confidence,
            signal_grade=signal.setup_grade,
            htf_bias=getattr(signal, 'htf_bias', None),
            reason=f"Local paper trade",
        )

        self.orders.append(paper_order)
        self._open_position(paper_order, stop, targets, signal)
        self._save_state()

        logger.info("PAPER ORDER: %s %d shares of %s @ $%.2f (stop=$%.2f)",
                    "BUY", qty, signal.ticker, entry, stop)
        return paper_order

    def _open_position(self, order: PaperOrder, stop, targets, signal):
        """Track a new open position with trailing stop state."""
        entry = order.filled_price
        # Compute ATR from signal if available, else estimate 2% of price
        atr = getattr(signal, 'atr_value', 0) or (entry * 0.02)

        self.positions[order.ticker] = PaperPosition(
            ticker=order.ticker,
            qty=order.qty,
            entry_price=entry,
            entry_date=order.filled_at,
            stop_price=stop,
            target_prices=targets,
            current_price=entry,
            signal_confidence=order.signal_confidence or 0,
            signal_grade=order.signal_grade or "",
            htf_bias=order.htf_bias,
            initial_stop=stop,
            atr_at_entry=atr,
            highest_price_reached=entry,
        )

        # Initialize trailing stop state
        self._trailing_states[order.ticker] = self._ts_engine.create_state(
            entry_price=entry,
            initial_stop=stop,
            atr_at_entry=atr,
        )

    # ------------------------------------------------------------------
    # Position management
    # ------------------------------------------------------------------

    def update_prices(self, price_map: Dict[str, float]):
        """
        Update current prices for open positions.
        Uses trailing stop engine for dynamic stop management.
        """
        exits = []
        for ticker, pos in self.positions.items():
            if ticker not in price_map:
                continue

            price = price_map[ticker]
            pos.current_price = price
            pos.unrealized_pnl = (price - pos.entry_price) * pos.qty
            pos.unrealized_pnl_pct = ((price - pos.entry_price) / pos.entry_price) * 100

            # Get or create trailing stop state
            ts = self._trailing_states.get(ticker)
            if ts is None:
                # Fallback: create state from position data
                ts = self._ts_engine.create_state(
                    entry_price=pos.entry_price,
                    initial_stop=pos.initial_stop or pos.stop_price,
                    atr_at_entry=pos.atr_at_entry or (pos.entry_price * 0.02),
                )
                self._trailing_states[ticker] = ts

            # Use price as both high and low (single price update)
            # In production with bar data, pass actual high/low
            action = self._ts_engine.update(
                ts, high=price, low=price, close=price,
            )

            # Sync trailing state back to position
            pos.stop_price = ts.current_stop
            pos.highest_price_reached = ts.highest_price
            pos.moved_to_breakeven = ts.moved_to_breakeven
            pos.trailing_active = ts.trailing_active

            if action == "stop_hit":
                exits.append((ticker, ts.current_stop, ts.exit_type))
            elif action == "partial_close":
                # Partial profit taking — close a portion of the position
                partial_qty = max(1, int(pos.qty * ts.partial_close_pct))
                remaining_qty = pos.qty - partial_qty
                if remaining_qty > 0:
                    partial_pnl = (price - pos.entry_price) * partial_qty
                    r = abs(pos.entry_price - (pos.initial_stop or pos.stop_price)) or 1
                    partial_trade = ClosedTrade(
                        ticker=ticker, side="buy", qty=partial_qty,
                        entry_price=pos.entry_price, exit_price=price,
                        entry_date=pos.entry_date,
                        exit_date=datetime.utcnow().isoformat(),
                        pnl_dollars=round(partial_pnl, 2),
                        pnl_pct=round((price - pos.entry_price) / pos.entry_price * 100, 2),
                        hold_duration_minutes=int((datetime.utcnow() - datetime.fromisoformat(pos.entry_date)).total_seconds() / 60) if pos.entry_date else 0,
                        exit_reason="partial_+2R",
                        signal_confidence=pos.signal_confidence,
                        signal_grade=pos.signal_grade,
                        htf_bias=pos.htf_bias,
                        moved_to_breakeven=ts.moved_to_breakeven,
                        trailing_activated=ts.trailing_active,
                        highest_price_reached=ts.highest_price,
                        max_r_reached=round(ts.max_r_reached, 2),
                        realized_r=round((price - pos.entry_price) / r, 2),
                    )
                    self.closed_trades.append(partial_trade)
                    pos.qty = remaining_qty
                    logger.info(
                        "PARTIAL CLOSE: %s %d/%d shares @ $%.2f (+%.1f%%)",
                        ticker, partial_qty, partial_qty + remaining_qty,
                        price, partial_trade.pnl_pct,
                    )

            # Target check (independent of partial close)
            if action != "stop_hit" and pos.target_prices and price >= pos.target_prices[0]:
                exits.append((ticker, price, "target"))

        for ticker, exit_price, reason in exits:
            self.close_position(ticker, exit_price, reason)

        if exits:
            self._save_state()

    def close_position(self, ticker: str, exit_price: float, reason: str = "manual"):
        """Close an open position and record the trade."""
        if ticker not in self.positions:
            return None

        pos = self.positions.pop(ticker)
        pnl_dollars = (exit_price - pos.entry_price) * pos.qty
        pnl_pct = ((exit_price - pos.entry_price) / pos.entry_price) * 100

        entry_dt = datetime.fromisoformat(pos.entry_date) if pos.entry_date else datetime.utcnow()
        hold_minutes = int((datetime.utcnow() - entry_dt).total_seconds() / 60)

        # Get trailing stop state for tracking fields
        ts = self._trailing_states.pop(ticker, None)
        r = abs(pos.entry_price - (pos.initial_stop or pos.stop_price)) or 1

        trade = ClosedTrade(
            ticker=ticker,
            side="buy",
            qty=pos.qty,
            entry_price=pos.entry_price,
            exit_price=exit_price,
            entry_date=pos.entry_date,
            exit_date=datetime.utcnow().isoformat(),
            pnl_dollars=round(pnl_dollars, 2),
            pnl_pct=round(pnl_pct, 2),
            hold_duration_minutes=hold_minutes,
            exit_reason=reason,
            signal_confidence=pos.signal_confidence,
            signal_grade=pos.signal_grade,
            htf_bias=pos.htf_bias,
            moved_to_breakeven=ts.moved_to_breakeven if ts else pos.moved_to_breakeven,
            trailing_activated=ts.trailing_active if ts else pos.trailing_active,
            highest_price_reached=ts.highest_price if ts else pos.highest_price_reached,
            max_r_reached=round(ts.max_r_reached, 2) if ts else 0,
            realized_r=round((exit_price - pos.entry_price) / r, 2),
        )

        self.closed_trades.append(trade)
        self._save_state()

        logger.info(
            "CLOSED: %s %d shares @ $%.2f -> $%.2f | P/L: $%.2f (%.1f%%) | %s",
            ticker, pos.qty, pos.entry_price, exit_price,
            pnl_dollars, pnl_pct, reason
        )
        return trade

    # ------------------------------------------------------------------
    # Performance analytics
    # ------------------------------------------------------------------

    def get_performance(self) -> dict:
        """Calculate comprehensive performance metrics."""
        trades = self.closed_trades
        if not trades:
            return {
                "total_trades": 0, "win_rate": 0, "profit_factor": 0,
                "total_pnl": 0, "avg_win": 0, "avg_loss": 0,
                "max_drawdown": 0, "sharpe_estimate": 0,
                "by_confidence": {}, "by_grade": {}, "by_htf_bias": {},
            }

        wins = [t for t in trades if t.pnl_pct > 0]
        losses = [t for t in trades if t.pnl_pct <= 0]

        total_pnl = sum(t.pnl_dollars for t in trades)
        gross_wins = sum(t.pnl_dollars for t in wins) if wins else 0
        gross_losses = abs(sum(t.pnl_dollars for t in losses)) if losses else 1

        # Drawdown calculation
        equity_curve = []
        running = 0
        peak = 0
        max_dd = 0
        for t in trades:
            running += t.pnl_dollars
            equity_curve.append(running)
            peak = max(peak, running)
            dd = peak - running
            max_dd = max(max_dd, dd)

        # Sharpe estimate (annualized, rough)
        returns = [t.pnl_pct for t in trades]
        import numpy as np
        avg_return = np.mean(returns)
        std_return = np.std(returns) if len(returns) > 1 else 1
        sharpe = (avg_return / std_return) * (252 ** 0.5) if std_return > 0 else 0

        # Breakdown by confidence bucket
        by_confidence = {}
        for bucket_name, lo, hi in [("0-40", 0, 40), ("40-60", 40, 60), ("60-80", 60, 80), ("80-100", 80, 100)]:
            bucket_trades = [t for t in trades if lo <= (t.signal_confidence or 0) < hi]
            if bucket_trades:
                bucket_wins = [t for t in bucket_trades if t.pnl_pct > 0]
                by_confidence[bucket_name] = {
                    "count": len(bucket_trades),
                    "win_rate": round(len(bucket_wins) / len(bucket_trades) * 100, 1),
                    "avg_pnl": round(np.mean([t.pnl_pct for t in bucket_trades]), 2),
                }

        # Breakdown by grade
        by_grade = {}
        for grade in ["A", "B", "C", "D", "F"]:
            g_trades = [t for t in trades if t.signal_grade == grade]
            if g_trades:
                g_wins = [t for t in g_trades if t.pnl_pct > 0]
                by_grade[grade] = {
                    "count": len(g_trades),
                    "win_rate": round(len(g_wins) / len(g_trades) * 100, 1),
                    "avg_pnl": round(np.mean([t.pnl_pct for t in g_trades]), 2),
                }

        # Breakdown by HTF bias
        by_htf = {}
        for bias in ["BULLISH", "NEUTRAL", "BEARISH", None]:
            label = bias or "UNKNOWN"
            b_trades = [t for t in trades if (t.htf_bias or None) == bias]
            if b_trades:
                b_wins = [t for t in b_trades if t.pnl_pct > 0]
                by_htf[label] = {
                    "count": len(b_trades),
                    "win_rate": round(len(b_wins) / len(b_trades) * 100, 1),
                    "avg_pnl": round(np.mean([t.pnl_pct for t in b_trades]), 2),
                }

        return {
            "total_trades": len(trades),
            "winning_trades": len(wins),
            "losing_trades": len(losses),
            "win_rate": round(len(wins) / len(trades) * 100, 1),
            "profit_factor": round(gross_wins / gross_losses, 2) if gross_losses > 0 else 0,
            "total_pnl": round(total_pnl, 2),
            "avg_win_pct": round(np.mean([t.pnl_pct for t in wins]), 2) if wins else 0,
            "avg_loss_pct": round(np.mean([t.pnl_pct for t in losses]), 2) if losses else 0,
            "max_drawdown": round(max_dd, 2),
            "sharpe_estimate": round(sharpe, 2),
            "avg_hold_minutes": round(np.mean([t.hold_duration_minutes for t in trades]), 0),
            "by_confidence": by_confidence,
            "by_grade": by_grade,
            "by_htf_bias": by_htf,
        }

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _save_state(self):
        """Save state to JSON files."""
        try:
            orders_path = self.data_dir / "orders.json"
            with open(orders_path, "w") as f:
                json.dump([asdict(o) for o in self.orders[-500:]], f, indent=2, default=str)

            positions_path = self.data_dir / "positions.json"
            with open(positions_path, "w") as f:
                json.dump({k: asdict(v) for k, v in self.positions.items()}, f, indent=2, default=str)

            trades_path = self.data_dir / "closed_trades.json"
            with open(trades_path, "w") as f:
                json.dump([asdict(t) for t in self.closed_trades], f, indent=2, default=str)

            # Persist trailing stop states so they survive restarts
            ts_path = self.data_dir / "trailing_states.json"
            with open(ts_path, "w") as f:
                json.dump({k: v.to_dict() for k, v in self._trailing_states.items()}, f, indent=2)
        except Exception as e:
            logger.error("Failed to save broker state: %s", e)

    def _load_state(self):
        """Load state from JSON files."""
        try:
            orders_path = self.data_dir / "orders.json"
            if orders_path.exists():
                with open(orders_path) as f:
                    data = json.load(f)
                    self.orders = [PaperOrder(**d) for d in data]
                    self._order_counter = len(self.orders)

            positions_path = self.data_dir / "positions.json"
            if positions_path.exists():
                with open(positions_path) as f:
                    data = json.load(f)
                    self.positions = {k: PaperPosition(**v) for k, v in data.items()}

            trades_path = self.data_dir / "closed_trades.json"
            if trades_path.exists():
                with open(trades_path) as f:
                    data = json.load(f)
                    self.closed_trades = [ClosedTrade(**d) for d in data]

            # Restore trailing stop states
            ts_path = self.data_dir / "trailing_states.json"
            if ts_path.exists():
                with open(ts_path) as f:
                    data = json.load(f)
                    self._trailing_states = {
                        k: TrailingStopState.from_dict(v) for k, v in data.items()
                    }
                logger.info("Restored %d trailing stop states", len(self._trailing_states))
        except Exception as e:
            logger.warning("Failed to load broker state: %s", e)
