"""
Outcome Simulator — Auto-learns from signal performance

Automatically checks open signals against real market data to determine
if targets or stops were hit, then records outcomes for ML training.

Improvements over naive simulation:
1. Slippage modeling — accounts for realistic entry price deviation
2. Gap detection — detects gap-through-stop scenarios for accurate loss calc
3. Time decay — expires stale signals that haven't resolved
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

import yfinance as yf
from sqlalchemy.orm import Session

from src.models.database import Signal, SignalOutcome
from src.models.schemas import OutcomeRecord, OutcomeType
from src.db.repositories import SignalRepository, SignalOutcomeRepository

logger = logging.getLogger(__name__)

# Simulation parameters
MAX_SIGNAL_AGE_HOURS = 48  # Expire signals older than this
SLIPPAGE_BASE_PCT = 0.15   # Base slippage as % of price
SLIPPAGE_VOL_MULT = 0.5    # Multiplier for volatility-based slippage


class OutcomeSimulator:
    """
    Background simulator that checks open signals and auto-records outcomes.

    Features:
    - Slippage modeling: adjusts entry price based on volatility
    - Gap detection: catches gap-down through stop for accurate loss
    - Time decay: expires stale signals that haven't hit target or stop
    """

    def __init__(self, db: Session):
        self.db = db
        self.signal_repo = SignalRepository(db)
        self.outcome_repo = SignalOutcomeRepository(db)

    def run(self) -> dict:
        """
        Check all open signals and simulate outcomes.
        Returns summary of results.
        """
        stats = {"checked": 0, "wins": 0, "losses": 0, "expired": 0, "open": 0}

        # Get signals that don't have outcomes yet
        open_signals = self._get_open_signals()
        logger.info("OutcomeSimulator: checking %d open signals", len(open_signals))

        for signal in open_signals:
            stats["checked"] += 1
            result = self._evaluate_signal(signal)

            if result is None:
                stats["open"] += 1
                continue

            outcome_type, pnl_pct, prices = result

            try:
                outcome = OutcomeRecord(
                    signal_id=signal.id,
                    outcome=outcome_type,
                    pnl_percent=round(pnl_pct, 2),
                    price_after_5m=prices.get("5m"),
                    price_after_15m=prices.get("15m"),
                    price_after_30m=prices.get("30m"),
                    price_after_60m=prices.get("60m"),
                )
                db_outcome = SignalOutcome(
                    signal_id=str(signal.id),
                    price_after_5m=outcome.price_after_5m,
                    price_after_15m=outcome.price_after_15m,
                    price_after_30m=outcome.price_after_30m,
                    price_after_60m=outcome.price_after_60m,
                    outcome=outcome_type.value,
                    pnl_percent=round(pnl_pct, 2),
                )
                self.outcome_repo.create(db_outcome)

                if outcome_type == OutcomeType.WIN:
                    stats["wins"] += 1
                elif outcome_type == OutcomeType.LOSS:
                    stats["losses"] += 1
                elif outcome_type == OutcomeType.EXPIRED:
                    stats["expired"] += 1

                logger.info(
                    "SimOutcome [%s]: %s pnl=%.2f%%",
                    signal.ticker, outcome_type.value, pnl_pct,
                )
            except Exception as exc:
                logger.error("Failed to record outcome for %s: %s", signal.ticker, exc)

        logger.info(
            "OutcomeSimulator complete: %d checked, %d wins, %d losses, %d expired, %d still open",
            stats["checked"], stats["wins"], stats["losses"], stats["expired"], stats["open"],
        )
        return stats

    def _get_open_signals(self) -> list[Signal]:
        """Get signals that have actionable setups but no outcome recorded yet."""
        all_signals = self.signal_repo.get_recent(limit=200)
        open_signals = []

        for sig in all_signals:
            # Only check BUY and WATCH signals (not AVOID/NO_VALID_SETUP)
            if sig.action not in ("BUY", "WATCH"):
                continue

            # Skip if outcome already exists
            existing = self.outcome_repo.get_by_signal(sig.id)
            if existing is not None:
                continue

            # Skip if missing entry/stop/target
            if not sig.entry_price or not sig.stop_price or not sig.target_prices:
                continue

            open_signals.append(sig)

        return open_signals

    def _evaluate_signal(
        self, signal: Signal
    ) -> Optional[tuple[OutcomeType, float, dict]]:
        """
        Evaluate a signal against current market data.

        Returns (outcome_type, pnl_percent, price_snapshots) or None if still open.
        """
        try:
            ticker = yf.Ticker(signal.ticker)

            # Get intraday data since signal was created
            signal_age = datetime.utcnow() - signal.created_at
            period = "5d" if signal_age.total_seconds() > 86400 else "1d"

            hist = ticker.history(period=period, interval="5m")
            if hist.empty:
                logger.warning("No data for %s, skipping", signal.ticker)
                return None

            # ── 1. Slippage Modeling ─────────────────────────────────
            slippage = self._calculate_slippage(hist, signal.entry_price)
            adjusted_entry = signal.entry_price + slippage

            entry_price = adjusted_entry
            stop_price = signal.stop_price
            target_price = signal.target_prices[0] if signal.target_prices else None

            if target_price is None:
                return None

            # ── Collect price snapshots ──────────────────────────────
            prices = self._get_price_snapshots(hist, signal.created_at)

            # ── 2. Gap Detection ─────────────────────────────────────
            gap_result = self._check_gap_through_stop(hist, signal.created_at, stop_price)
            if gap_result is not None:
                gap_pnl = ((gap_result - entry_price) / entry_price) * 100
                logger.info(
                    "Gap detected for %s: opened at %.2f below stop %.2f",
                    signal.ticker, gap_result, stop_price,
                )
                return (OutcomeType.LOSS, gap_pnl, prices)

            # ── Check bars after signal creation ─────────────────────
            bars_after = hist[hist.index >= signal.created_at.strftime("%Y-%m-%d")]

            for _, bar in bars_after.iterrows():
                # Check stop hit first (conservative — stop before target)
                if bar["Low"] <= stop_price:
                    pnl = ((stop_price - entry_price) / entry_price) * 100
                    return (OutcomeType.LOSS, pnl, prices)

                # Check target hit
                if bar["High"] >= target_price:
                    pnl = ((target_price - entry_price) / entry_price) * 100
                    return (OutcomeType.WIN, pnl, prices)

            # ── 3. Time Decay — expire stale signals ─────────────────
            hours_old = signal_age.total_seconds() / 3600
            if hours_old > MAX_SIGNAL_AGE_HOURS:
                # Close at current price
                current_price = float(hist["Close"].iloc[-1])
                pnl = ((current_price - entry_price) / entry_price) * 100
                logger.info(
                    "Time decay for %s: %.1f hours old, closing at %.2f (pnl=%.2f%%)",
                    signal.ticker, hours_old, current_price, pnl,
                )
                return (OutcomeType.EXPIRED, pnl, prices)

            # Still open — neither target nor stop hit yet
            return None

        except Exception as exc:
            logger.error("Error evaluating %s: %s", signal.ticker, exc)
            return None

    def _calculate_slippage(self, hist, entry_price: float) -> float:
        """
        Model realistic slippage based on volatility.

        Higher volatility = more slippage (harder to get exact fill).
        """
        try:
            # Calculate recent volatility (ATR-like)
            recent = hist.tail(20)
            if len(recent) < 5:
                return entry_price * (SLIPPAGE_BASE_PCT / 100)

            high_low_range = (recent["High"] - recent["Low"]).mean()
            volatility_pct = high_low_range / entry_price

            # Slippage = base + (volatility * multiplier)
            slippage_pct = (SLIPPAGE_BASE_PCT / 100) + (volatility_pct * SLIPPAGE_VOL_MULT)

            # Cap at 2% max slippage
            slippage_pct = min(slippage_pct, 0.02)

            slippage = entry_price * slippage_pct
            logger.debug(
                "Slippage for entry %.2f: vol=%.4f slip=%.4f (%.2f%%)",
                entry_price, volatility_pct, slippage, slippage_pct * 100,
            )
            return slippage

        except Exception:
            return entry_price * (SLIPPAGE_BASE_PCT / 100)

    def _check_gap_through_stop(
        self, hist, signal_time: datetime, stop_price: float
    ) -> Optional[float]:
        """
        Detect if a stock gapped down through the stop price.

        Returns the gap open price if detected, None otherwise.
        """
        try:
            # Get daily bars to check for gaps
            daily_bars = hist.resample("1D").agg({
                "Open": "first", "High": "max", "Low": "min",
                "Close": "last", "Volume": "sum",
            }).dropna()

            if len(daily_bars) < 2:
                return None

            # Check each day's open after signal creation
            for i in range(1, len(daily_bars)):
                day = daily_bars.iloc[i]
                prev_day = daily_bars.iloc[i - 1]

                # Gap down: today's open is below stop AND below yesterday's low
                if day["Open"] < stop_price and day["Open"] < prev_day["Low"]:
                    return float(day["Open"])

            return None

        except Exception:
            return None

    def _get_price_snapshots(self, hist, signal_time: datetime) -> dict:
        """Get price at 5m, 15m, 30m, 60m after signal creation."""
        prices = {}
        offsets = {"5m": 5, "15m": 15, "30m": 30, "60m": 60}

        for label, minutes in offsets.items():
            target_time = signal_time + timedelta(minutes=minutes)
            try:
                # Find the closest bar
                after_bars = hist[hist.index >= target_time.strftime("%Y-%m-%d %H:%M")]
                if not after_bars.empty:
                    prices[label] = float(after_bars["Close"].iloc[0])
            except Exception:
                pass

        return prices
