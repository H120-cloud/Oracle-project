"""
Backtest Validator — V10
Runs full pipeline on historical data, produces rigorous performance metrics.
"""
import logging
import time
from datetime import datetime
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Tuple
import numpy as np

from src.models.schemas import (
    OHLCVBar, ScannedStock, TradingSignal, SignalAction,
    StockClassification, DipFeatures, DipResult, DipPhase,
    BounceFeatures, BounceResult,
)
from src.core.decision_engine import DecisionEngine
from src.core.dip_detector import DipDetector
from src.core.bounce_detector import BounceDetector
from src.core.ict_detector import ICTDetector
from src.core.classifier import StockClassifier
from src.core.trailing_stop import TrailingStopEngine, TrailingStopState

logger = logging.getLogger(__name__)


@dataclass
class ValidatedTrade:
    ticker: str
    entry_price: float
    exit_price: float = 0.0
    pnl_pct: float = 0.0
    exit_reason: str = ""  # stop_loss, breakeven, trailing_stop, target, time_exit
    hold_bars: int = 0
    confidence: float = 0.0
    setup_grade: str = ""
    htf_bias: Optional[str] = None
    ict_score: int = 0
    # Trailing stop tracking
    moved_to_breakeven: bool = False
    trailing_activated: bool = False
    highest_price_reached: float = 0.0
    max_r_reached: float = 0.0
    realized_r: float = 0.0


@dataclass
class RejectedSignal:
    ticker: str
    price: float
    reason: str
    would_have_won: Optional[bool] = None
    max_favorable: float = 0.0
    htf_bias: Optional[str] = None


@dataclass
class ValidationResult:
    tickers_tested: List[str]
    start_date: str
    end_date: str
    interval: str
    total_bars: int
    run_time_seconds: float
    trades: List[ValidatedTrade] = field(default_factory=list)
    rejections: List[RejectedSignal] = field(default_factory=list)

    @property
    def wins(self): return [t for t in self.trades if t.pnl_pct > 0]
    @property
    def losses(self): return [t for t in self.trades if t.pnl_pct <= 0]
    @property
    def win_rate(self):
        return (len(self.wins) / len(self.trades) * 100) if self.trades else 0
    @property
    def profit_factor(self):
        gw = sum(t.pnl_pct for t in self.wins) or 0
        gl = abs(sum(t.pnl_pct for t in self.losses)) or 1
        return gw / gl if gl > 0 else 0
    @property
    def total_return(self):
        eq = 1.0
        for t in self.trades: eq *= (1 + t.pnl_pct / 100)
        return (eq - 1) * 100
    @property
    def sharpe(self):
        if len(self.trades) < 2: return 0
        r = [t.pnl_pct for t in self.trades]
        s = np.std(r)
        return (np.mean(r) / s) * (252**0.5) if s > 0 else 0
    @property
    def max_drawdown(self):
        eq, pk, dd = 1.0, 1.0, 0
        for t in self.trades:
            eq *= (1 + t.pnl_pct / 100)
            pk = max(pk, eq)
            dd = max(dd, (pk - eq) / pk * 100)
        return dd

    def confidence_calibration(self) -> Dict:
        buckets = {"0-40": (0,40), "40-60": (40,60), "60-80": (60,80), "80-100": (80,100)}
        out = {}
        for name, (lo, hi) in buckets.items():
            b = [t for t in self.trades if lo <= t.confidence < hi]
            if b:
                w = [t for t in b if t.pnl_pct > 0]
                wr = len(w)/len(b)*100
                out[name] = {"count": len(b), "win_rate": round(wr,1),
                    "avg_pnl": round(np.mean([t.pnl_pct for t in b]),2),
                    "calibration_gap": round(wr - (lo+hi)/2, 1)}
        return out

    def grade_performance(self) -> Dict:
        out = {}
        for g in ["A","B","C","D","F"]:
            b = [t for t in self.trades if t.setup_grade == g]
            if b:
                w = [t for t in b if t.pnl_pct > 0]
                out[g] = {"count": len(b), "win_rate": round(len(w)/len(b)*100,1)}
        return out

    def htf_impact(self) -> Dict:
        out = {}
        for bias in ["BULLISH","NEUTRAL","BEARISH",None]:
            label = bias or "NO_HTF"
            b = [t for t in self.trades if t.htf_bias == bias]
            if b:
                w = [t for t in b if t.pnl_pct > 0]
                out[label] = {"count": len(b), "win_rate": round(len(w)/len(b)*100,1),
                    "avg_pnl": round(np.mean([t.pnl_pct for t in b]),2)}
        return out

    def trailing_stop_analysis(self) -> Dict:
        """Trailing stop performance breakdown."""
        if not self.trades:
            return {}
        total = len(self.trades)
        reached_1r = sum(1 for t in self.trades if t.max_r_reached >= 1.0)
        reached_2r = sum(1 for t in self.trades if t.max_r_reached >= 2.0)
        reached_3r = sum(1 for t in self.trades if t.max_r_reached >= 3.0)
        be_trades = [t for t in self.trades if t.moved_to_breakeven]
        trail_trades = [t for t in self.trades if t.trailing_activated]

        # Exit type breakdown
        exit_types = {}
        for t in self.trades:
            exit_types[t.exit_reason] = exit_types.get(t.exit_reason, 0) + 1

        # Avg R before trailing exit
        trail_exits = [t for t in self.trades if t.exit_reason == "trailing_stop"]
        avg_r_trail = round(np.mean([t.realized_r for t in trail_exits]), 2) if trail_exits else 0

        return {
            "pct_reached_1r": round(reached_1r / total * 100, 1),
            "pct_reached_2r": round(reached_2r / total * 100, 1),
            "pct_reached_3r": round(reached_3r / total * 100, 1),
            "breakeven_activated": len(be_trades),
            "trailing_activated": len(trail_trades),
            "avg_max_r": round(np.mean([t.max_r_reached for t in self.trades]), 2),
            "avg_realized_r": round(np.mean([t.realized_r for t in self.trades]), 2),
            "avg_r_trailing_exits": avg_r_trail,
            "exit_type_breakdown": exit_types,
        }

    def equity_curve_data(self) -> list:
        """Generate equity curve data points for charting."""
        curve = []
        eq = 1.0
        peak = 1.0
        for idx, t in enumerate(self.trades):
            eq *= (1 + t.pnl_pct / 100)
            peak = max(peak, eq)
            dd = (peak - eq) / peak * 100 if peak > 0 else 0
            curve.append({
                "trade_num": idx + 1,
                "ticker": t.ticker,
                "pnl_pct": t.pnl_pct,
                "equity": round(eq * 100, 2),  # As percentage of starting capital
                "drawdown": round(dd, 2),
                "exit_reason": t.exit_reason,
            })
        return curve

    def summary(self) -> dict:
        has_edge = self.win_rate > 50 and self.profit_factor > 1.2 and len(self.trades) >= 30
        return {
            "performance": {
                "total_trades": len(self.trades), "win_rate": round(self.win_rate,1),
                "profit_factor": round(self.profit_factor,2),
                "total_return_pct": round(self.total_return,2),
                "sharpe": round(self.sharpe,2), "max_drawdown": round(self.max_drawdown,2),
                "avg_win": round(np.mean([t.pnl_pct for t in self.wins]),2) if self.wins else 0,
                "avg_loss": round(np.mean([t.pnl_pct for t in self.losses]),2) if self.losses else 0,
            },
            "trailing_stop": self.trailing_stop_analysis(),
            "equity_curve": self.equity_curve_data(),
            "calibration": self.confidence_calibration(),
            "grades": self.grade_performance(),
            "htf": self.htf_impact(),
            "rejections": {"total": len(self.rejections),
                "correct": sum(1 for r in self.rejections if not r.would_have_won),
                "missed_wins": sum(1 for r in self.rejections if r.would_have_won)},
            "verdict": {
                "has_edge": has_edge,
                "recommendation": "Proceed to paper trading" if has_edge else "Do NOT trade live yet",
            },
        }


class BacktestValidator:
    def __init__(self, max_hold_bars: int = 60, use_htf: bool = True):
        self.engine = DecisionEngine()
        self.dip_det = DipDetector()
        self.bounce_det = BounceDetector()
        self.ict_det = ICTDetector()
        self.classifier = StockClassifier()
        self.max_hold = max_hold_bars
        self.use_htf = use_htf
        self._skip_ict = False

    def _adapt_for_interval(self, interval: str):
        """Adapt detector thresholds based on data interval.

        Daily bars have less granularity than intraday, so bounce/dip
        probabilities are naturally lower.  Relax thresholds so the
        backtest can generate a meaningful number of trades.
        """
        if interval in ("1d", "1wk"):
            # Bounce detector: lower readiness from 60→25, validity 40→20
            self.bounce_det.t.entry_readiness_threshold = 25.0
            self.bounce_det.t.validity_threshold = 20.0
            # Dip detector thresholds (if exposed)
            try:
                self.dip_det.t.min_probability = 25.0
            except AttributeError:
                pass
            # NoTradeFilter inside engine: lower minimums
            try:
                self.engine.no_trade_filter.t.min_bounce_probability = 5.0
                self.engine.no_trade_filter.t.min_dip_probability = 15.0
                # Unblock SIDEWAYS — daily bars often classify as sideways
                # but can still have valid dip/bounce setups
                from src.models.schemas import StockClassification
                self.engine.no_trade_filter.t.blocked_classifications = (
                    StockClassification.BREAKDOWN_RISK,
                    StockClassification.OVEREXTENDED,
                    StockClassification.NO_VALID_SETUP,
                )
            except AttributeError:
                pass
            # Decision engine bounce threshold override
            self.engine.bounce_threshold_override = 5
            # ICT patterns (sweeps, MSBs) don't work on daily bars — disable
            self._skip_ict = True
            # Daily IS the higher timeframe — skip HTF alignment
            self.use_htf = False
            # Test across ALL regimes (bear, bull, choppy) — don't block
            self.engine.disable_regime_filter = True
            # Max hold in days (not intraday bars)
            self.max_hold = min(self.max_hold, 20)
            logger.info("Adapted thresholds for daily interval")
        elif interval in ("1h",):
            self.bounce_det.t.entry_readiness_threshold = 40.0
            self.bounce_det.t.validity_threshold = 30.0
            self.engine.bounce_threshold_override = 35
            try:
                self.engine.no_trade_filter.t.min_bounce_probability = 25.0
                self.engine.no_trade_filter.t.min_dip_probability = 25.0
            except AttributeError:
                pass
            logger.info("Adapted thresholds for hourly interval")

    def walk_forward_validate(
        self, tickers: List[str], start: str = "2023-01-01",
        end: str = "2024-12-31", interval: str = "1d",
        train_months: int = 6, test_months: int = 2,
    ) -> dict:
        """
        Walk-forward validation: train on N months, test on M months, roll forward.
        Returns per-fold results and aggregate metrics.
        """
        from datetime import datetime as dt
        from dateutil.relativedelta import relativedelta

        start_dt = dt.strptime(start, "%Y-%m-%d")
        end_dt = dt.strptime(end, "%Y-%m-%d")

        folds = []
        fold_start = start_dt

        while True:
            train_end = fold_start + relativedelta(months=train_months)
            test_start = train_end
            test_end = test_start + relativedelta(months=test_months)

            if test_end > end_dt:
                break

            fold_result = self.validate(
                tickers,
                start=test_start.strftime("%Y-%m-%d"),
                end=test_end.strftime("%Y-%m-%d"),
                interval=interval,
            )

            fold_summary = fold_result.summary()
            fold_summary["fold"] = len(folds) + 1
            fold_summary["test_period"] = f"{test_start.strftime('%Y-%m-%d')} to {test_end.strftime('%Y-%m-%d')}"
            folds.append(fold_summary)

            # Roll forward by test_months
            fold_start += relativedelta(months=test_months)

        # Aggregate across folds
        if folds:
            all_wr = [f["performance"]["win_rate"] for f in folds if f["performance"]["total_trades"] > 0]
            all_pf = [f["performance"]["profit_factor"] for f in folds if f["performance"]["total_trades"] > 0]
            all_ret = [f["performance"]["total_return_pct"] for f in folds]
            all_trades = sum(f["performance"]["total_trades"] for f in folds)

            aggregate = {
                "total_folds": len(folds),
                "total_trades": all_trades,
                "avg_win_rate": round(np.mean(all_wr), 1) if all_wr else 0,
                "avg_profit_factor": round(np.mean(all_pf), 2) if all_pf else 0,
                "avg_return_per_fold": round(np.mean(all_ret), 2) if all_ret else 0,
                "profitable_folds": sum(1 for r in all_ret if r > 0),
                "consistency_score": round(sum(1 for r in all_ret if r > 0) / len(folds) * 100, 1) if folds else 0,
            }
        else:
            aggregate = {"total_folds": 0, "error": "No complete folds in date range"}

        return {"walk_forward": aggregate, "folds": folds}

    def validate(self, tickers: List[str], start: str = "2024-01-01",
                 end: str = "2024-12-31", interval: str = "5m") -> ValidationResult:
        from src.services.market_data import YFinanceProvider
        prov = YFinanceProvider()
        self._adapt_for_interval(interval)
        t0 = time.time()
        all_trades, all_rej, total = [], [], 0

        for tk in tickers:
            logger.info("Validating %s...", tk)
            try:
                bars = prov.get_ohlcv(tk, start=start, end=end, interval=interval)
                if len(bars) < 50:
                    logger.warning("%s: only %d bars (need 50+), skip", tk, len(bars))
                    continue
                daily = prov.get_ohlcv(tk, start=start, end=end, interval="1d") if self.use_htf else []
                trades, rej = self._run(tk, bars, daily)
                all_trades.extend(trades)
                all_rej.extend(rej)
                total += len(bars)
                wr = (sum(1 for t in trades if t.pnl_pct > 0)/len(trades)*100) if trades else 0
                logger.info("  %s: %d trades (%.0f%% win), %d rejections", tk, len(trades), wr, len(rej))
            except Exception as e:
                logger.error("Failed %s: %s", tk, e)

        return ValidationResult(tickers, start, end, interval, total, time.time()-t0, all_trades, all_rej)

    def _run(self, ticker, bars, daily_bars):
        trades, rejections = [], []
        win_size = 50
        in_trade = False
        trade = None
        ts_state: Optional[TrailingStopState] = None
        trade_targets = []
        trade_entry_idx = 0

        ts_engine = TrailingStopEngine()

        for i in range(win_size, len(bars)):
            bar = bars[i]

            if in_trade:
                # ── Determine momentum/volume for trailing logic ──
                momentum = "neutral"
                vol_up = False
                if i >= 3:
                    price_chg = (bar.close - bars[i - 3].close) / bars[i - 3].close * 100
                    if price_chg > 1.5:
                        momentum = "strong_up"
                    elif price_chg > 0.5:
                        momentum = "accelerating_up"
                    vol_up = bar.volume > bars[i - 1].volume

                # ── Evaluate trailing stop engine ──
                action = ts_engine.update(
                    ts_state, high=bar.high, low=bar.low, close=bar.close,
                    momentum_state=momentum, volume_increasing=vol_up,
                )

                if action == "stop_hit":
                    exit_price = ts_state.current_stop
                    trade.exit_price = exit_price
                    trade.pnl_pct = round((exit_price - trade.entry_price) / trade.entry_price * 100, 2)
                    trade.exit_reason = ts_state.exit_type
                    trade.hold_bars = i - trade_entry_idx
                    trade.moved_to_breakeven = ts_state.moved_to_breakeven
                    trade.trailing_activated = ts_state.trailing_active
                    trade.highest_price_reached = ts_state.highest_price
                    trade.max_r_reached = round(ts_state.max_r_reached, 2)
                    r = ts_state.risk_per_share
                    trade.realized_r = round((exit_price - trade.entry_price) / r, 2) if r > 0 else 0
                    trades.append(trade)
                    in_trade = False
                    continue

                # ── Target hit (first target only) ──
                if trade_targets and bar.high >= trade_targets[0]:
                    exit_price = trade_targets[0]
                    trade.exit_price = exit_price
                    trade.pnl_pct = round((exit_price - trade.entry_price) / trade.entry_price * 100, 2)
                    trade.exit_reason = "target"
                    trade.hold_bars = i - trade_entry_idx
                    trade.moved_to_breakeven = ts_state.moved_to_breakeven
                    trade.trailing_activated = ts_state.trailing_active
                    trade.highest_price_reached = ts_state.highest_price
                    trade.max_r_reached = round(ts_state.max_r_reached, 2)
                    r = ts_state.risk_per_share
                    trade.realized_r = round((exit_price - trade.entry_price) / r, 2) if r > 0 else 0
                    trades.append(trade)
                    in_trade = False
                    continue

                # ── Time expiry (fallback) ──
                if i - trade_entry_idx >= self.max_hold:
                    exit_price = bar.close
                    trade.exit_price = exit_price
                    trade.pnl_pct = round((exit_price - trade.entry_price) / trade.entry_price * 100, 2)
                    trade.exit_reason = "time_exit"
                    trade.hold_bars = self.max_hold
                    trade.moved_to_breakeven = ts_state.moved_to_breakeven
                    trade.trailing_activated = ts_state.trailing_active
                    trade.highest_price_reached = ts_state.highest_price
                    trade.max_r_reached = round(ts_state.max_r_reached, 2)
                    r = ts_state.risk_per_share
                    trade.realized_r = round((exit_price - trade.entry_price) / r, 2) if r > 0 else 0
                    trades.append(trade)
                    in_trade = False
                    continue

                continue

            # ── Generate signal ──
            if i + self.max_hold >= len(bars):
                break  # Not enough bars left for a full trade

            window = bars[i - win_size:i + 1]
            current = bars[i]
            signal = self._gen_signal(ticker, window, current, daily_bars)
            if not signal:
                continue

            if signal.action == SignalAction.BUY:
                entry_price = current.close
                stop_price = signal.stop_price

                # Compute ATR at entry from the window
                w_highs = [b.high for b in window]
                w_lows = [b.low for b in window]
                w_closes = [b.close for b in window]
                atr = ts_engine.compute_atr(w_highs, w_lows, w_closes)

                trade = ValidatedTrade(
                    ticker=ticker, entry_price=entry_price,
                    confidence=signal.confidence or 0,
                    setup_grade=signal.setup_grade or "",
                    htf_bias=getattr(signal, 'htf_bias', None),
                    ict_score=0,
                )
                trade_targets = signal.target_prices or []
                trade_entry_idx = i

                # Initialize trailing stop state
                ts_state = ts_engine.create_state(
                    entry_price=entry_price,
                    initial_stop=stop_price,
                    atr_at_entry=atr,
                )
                in_trade = True

            elif signal.action in (SignalAction.NO_VALID_SETUP, SignalAction.WATCH, SignalAction.AVOID):
                # Track rejection outcome
                future = bars[i:min(i + self.max_hold, len(bars))]
                if len(future) > 5:
                    max_price = max(b.high for b in future[1:])
                    fav = (max_price - current.close) / current.close * 100
                    would_win = fav > 2.0
                    rej = RejectedSignal(
                        ticker=ticker, price=current.close,
                        reason="; ".join(signal.reason[:2]) if signal.reason else "filtered",
                        would_have_won=would_win, max_favorable=round(fav, 2),
                        htf_bias=getattr(signal, 'htf_bias', None),
                    )
                    rejections.append(rej)

        return trades, rejections

    def _gen_signal(self, ticker, window, current, daily_bars):
        try:
            stock = ScannedStock(ticker=ticker, price=current.close,
                volume=float(current.volume), scan_type="backtest")
            ict = None if self._skip_ict else self.ict_det.detect(ticker, window)

            # Compute features from window
            closes = [b.close for b in window]
            highs = [b.high for b in window]
            lows = [b.low for b in window]
            opens = [b.open for b in window]
            vols = [b.volume for b in window]

            dip_feat = self._compute_dip(closes, highs, lows, opens, vols)
            dip_result = self.dip_det.detect(ticker, dip_feat) if dip_feat else None

            bounce_feat = self._compute_bounce(closes, highs, lows, opens, vols)
            bounce_result = self.bounce_det.detect(ticker, bounce_feat, current.close) if bounce_feat else None

            classification = self.classifier.classify(
                dip=dip_result, bounce=bounce_result,
                change_percent=0)

            return self.engine.decide(
                stock=stock, classification=classification,
                dip=dip_result, bounce=bounce_result, ict=ict,
                bars=window, daily_bars=daily_bars if self.use_htf else None)
        except Exception as e:
            logger.debug("Signal gen failed at bar: %s", e)
            return None

    def _compute_dip(self, closes, highs, lows, opens, vols):
        import pandas as pd
        try:
            c, h, l, o, v = pd.Series(closes), pd.Series(highs), pd.Series(lows), pd.Series(opens), pd.Series(vols)
            if len(c) < 20: return None
            tp = (h + l + c) / 3
            vwap = (tp * v).cumsum() / v.cumsum()
            ema9 = c.ewm(span=9, adjust=False).mean()
            ema20 = c.ewm(span=20, adjust=False).mean()
            vel = c.pct_change(1) * 100
            pv = float(vel.iloc[-1]) if len(vel) > 0 else 0
            ppv = float(vel.iloc[-2]) if len(vel) > 1 else pv
            pa = pv - ppv
            if pv < -1 and pa < 0: ms = "accelerating_down"
            elif pv < 0 and pa > 0: ms = "slowing_down"
            elif pv > 0.5: ms = "bullish"
            else: ms = "neutral"
            fk = pv < -2 and pa < -0.5
            rl = l.tail(10).values
            mins = [rl[i] for i in range(1,len(rl)-1) if rl[i]<rl[i-1] and rl[i]<rl[i+1]]
            hl = len(mins) >= 2 and mins[-1] > mins[-2]
            rs = float(l.rolling(10).min().iloc[-1])
            si = hl or float(c.iloc[-1]) > rs * 1.002
            red = (c < o).astype(int)
            rc = 0
            for x in reversed(red.values):
                if x: rc += 1
                else: break
            return DipFeatures(
                vwap_distance_pct=round(float((c.iloc[-1]-vwap.iloc[-1])/vwap.iloc[-1]*100),2),
                ema9_distance_pct=round(float((c.iloc[-1]-ema9.iloc[-1])/ema9.iloc[-1]*100),2),
                ema20_distance_pct=round(float((c.iloc[-1]-ema20.iloc[-1])/ema20.iloc[-1]*100),2),
                drop_from_high_pct=round(float((h.max()-c.iloc[-1])/h.max()*100),2),
                consecutive_red_candles=rc, red_candle_volume_ratio=1.0,
                lower_highs_count=sum(1 for i in range(1,min(10,len(highs))) if highs[-i]<highs[-i-1]),
                momentum_decay=0, price_velocity=round(pv,4),
                price_acceleration=round(pa,4), momentum_state=ms,
                structure_intact=si, is_falling_knife=fk)
        except: return None

    def _compute_bounce(self, closes, highs, lows, opens, vols):
        import pandas as pd
        try:
            c, l, o, v = pd.Series(closes), pd.Series(lows), pd.Series(opens), pd.Series(vols)
            if len(c) < 20: return None
            sup = float(l.rolling(20).min().iloc[-1])
            sd = (c.iloc[-1]-sup)/sup*100
            ema9 = c.ewm(span=9, adjust=False).mean()
            vel = c.pct_change(1) * 100
            pv = float(vel.iloc[-1]) if len(vel) > 0 else 0
            ppv = float(vel.iloc[-2]) if len(vel) > 1 else pv
            pa = pv - ppv
            if pv > 0 and pa > 0: ms = "accelerating_up"
            elif pv < 0 and pa > 0: ms = "slowing_down"
            elif pv > 0.3: ms = "bullish"
            else: ms = "neutral"
            rl = l.tail(20).values
            mins = [rl[i] for i in range(1,len(rl)-1) if rl[i]<rl[i-1] and rl[i]<rl[i+1]]
            hl = len(mins) >= 2 and mins[-1] > mins[-2]
            wb = any(c.iloc[-10:-3] < ema9.iloc[-10:-3])
            na = c.iloc[-1] > ema9.iloc[-1]
            return BounceFeatures(
                support_distance_pct=round(float(sd),2), selling_pressure_change=0,
                buying_pressure_ratio=1.0, higher_low_formed=hl,
                key_level_reclaimed=wb and na, rsi=None, macd_histogram_slope=None,
                price_velocity=round(pv,4), price_acceleration=round(pa,4), momentum_state=ms)
        except: return None
