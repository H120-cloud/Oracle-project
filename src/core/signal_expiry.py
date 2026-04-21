"""
Signal Expiry Logic — V3

Determines if a signal should be expired based on:
  - time window exceeded
  - no bounce materialized
  - key level reclaim failed
  - momentum faded
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

from src.models.schemas import (
    TradingSignal,
    SignalAction,
    ExpiryReason,
    OHLCVBar,
)

logger = logging.getLogger(__name__)


class SignalExpiryChecker:
    """Evaluate whether active signals should be expired."""

    def __init__(self, default_expiry_minutes: int = 30):
        self.default_expiry_minutes = default_expiry_minutes

    def check(
        self,
        signal: TradingSignal,
        current_price: float,
        recent_bars: Optional[list[OHLCVBar]] = None,
        now: Optional[datetime] = None,
    ) -> Optional[ExpiryReason]:
        """
        Return an ExpiryReason if the signal should be expired, else None.
        """
        now = now or datetime.utcnow()

        # 1. Time expiry
        if signal.signal_expiry and now >= signal.signal_expiry:
            logger.info("Signal %s expired: time window", signal.ticker)
            return ExpiryReason.TIME_EXPIRED

        # Only check BUY/WATCH signals further
        if signal.action not in (SignalAction.BUY, SignalAction.WATCH):
            return None

        # 2. Reclaim failed: price dropped below stop
        if signal.stop_price and current_price < signal.stop_price:
            logger.info(
                "Signal %s expired: reclaim failed (price %.2f < stop %.2f)",
                signal.ticker, current_price, signal.stop_price,
            )
            return ExpiryReason.RECLAIM_FAILED

        # 3. No bounce: if WATCH signal and bounce probability was set,
        #    check if enough time passed without bounce forming
        if signal.action == SignalAction.WATCH and signal.created_at:
            watch_window = timedelta(minutes=self.default_expiry_minutes // 2)
            if now > signal.created_at + watch_window:
                # Price hasn't moved up meaningfully from entry area
                if signal.entry_price and current_price <= signal.entry_price:
                    logger.info("Signal %s expired: no bounce within watch window", signal.ticker)
                    return ExpiryReason.NO_BOUNCE

        # 4. Momentum faded: check if recent bars show declining momentum
        if recent_bars and len(recent_bars) >= 5:
            recent_closes = [b.close for b in recent_bars[-5:]]
            # All 5 bars making lower closes → momentum gone
            all_declining = all(
                recent_closes[i] <= recent_closes[i - 1]
                for i in range(1, len(recent_closes))
            )
            if all_declining and signal.action == SignalAction.BUY:
                logger.info("Signal %s expired: momentum faded (5 lower closes)", signal.ticker)
                return ExpiryReason.MOMENTUM_FADED

        return None
