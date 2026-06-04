"""
News Momentum Outcome Resolver
==============================

Background task that closes the feedback loop on Telegram alerts.

For every alert that hasn't been resolved yet, this module:
  1. Fetches subsequent price bars (1m / 1h / 1d) via the market data provider.
  2. Computes the price 15m / 1h / 4h after the alert + the next-day high/close
     and the 2-day / 5-day high.
  3. Calls AdaptiveTelegramLearning.resolve_outcome() to compute MFE/MAE and
     auto-label the alert as GREAT / GOOD / LATE / TRAP / NO_FOLLOW_THROUGH.

Once enough alerts have been resolved, the data feeds directly into
NewsMomentumMLEngine.train() for the weekly retrain.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, List, Optional, Tuple, TYPE_CHECKING

from src.core.agentic.news_momentum_models import TelegramAlertRecord

if TYPE_CHECKING:
    from src.core.agentic.news_momentum_telegram_learning import AdaptiveTelegramLearning

logger = logging.getLogger(__name__)

# Don't try to resolve alerts older than this — assume the data isn't worth chasing
MAX_RESOLVE_AGE_DAYS = 7

# Don't bother pulling next_day data until at least this many hours after alert
HOURS_BEFORE_NEXT_DAY = 18  # next-day open is ~16h+ after a typical premarket alert
HOURS_BEFORE_TWO_DAY = 36
HOURS_BEFORE_FIVE_DAY = 24 * 5 + 4  # 5 trading days + buffer


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _bar_close_at(bars: List[Any], target_time: datetime) -> Optional[float]:
    """Return the close price of the bar that contains target_time.

    Bars are expected to be OHLCVBar-like objects with .timestamp / .close attributes
    (or dicts with those keys). Returns None if the target is outside the bars range.
    """
    if not bars:
        return None
    target = _aware(target_time)
    candidate = None
    for bar in bars:
        ts = getattr(bar, "timestamp", None) or (bar.get("timestamp") if isinstance(bar, dict) else None)
        close = getattr(bar, "close", None) or (bar.get("close") if isinstance(bar, dict) else None)
        if ts is None or close is None:
            continue
        if isinstance(ts, str):
            try:
                ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except Exception:
                continue
        ts = _aware(ts)
        if ts <= target:
            candidate = float(close)
        else:
            break
    return candidate


def _max_high_in_range(bars: List[Any], start: datetime, end: datetime) -> Optional[float]:
    """Max high price across bars in [start, end]."""
    if not bars:
        return None
    start = _aware(start)
    end = _aware(end)
    highs: List[float] = []
    for bar in bars:
        ts = getattr(bar, "timestamp", None) or (bar.get("timestamp") if isinstance(bar, dict) else None)
        high = getattr(bar, "high", None) or (bar.get("high") if isinstance(bar, dict) else None)
        if ts is None or high is None:
            continue
        if isinstance(ts, str):
            try:
                ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except Exception:
                continue
        ts = _aware(ts)
        if start <= ts <= end:
            highs.append(float(high))
    return max(highs) if highs else None


def _next_day_open_close_high(bars: List[Any], alert_time: datetime) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    """Get next trading day's open, close, and high from daily bars.

    `bars` should be daily OHLCV bars sorted by timestamp ascending.
    """
    if not bars:
        return None, None, None
    alert_time = _aware(alert_time)
    alert_date = alert_time.date()
    next_day_bar = None
    for bar in bars:
        ts = getattr(bar, "timestamp", None) or (bar.get("timestamp") if isinstance(bar, dict) else None)
        if ts is None:
            continue
        if isinstance(ts, str):
            try:
                ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except Exception:
                continue
        ts = _aware(ts)
        if ts.date() > alert_date:
            next_day_bar = bar
            break
    if next_day_bar is None:
        return None, None, None
    open_p = getattr(next_day_bar, "open", None) or (next_day_bar.get("open") if isinstance(next_day_bar, dict) else None)
    close_p = getattr(next_day_bar, "close", None) or (next_day_bar.get("close") if isinstance(next_day_bar, dict) else None)
    high_p = getattr(next_day_bar, "high", None) or (next_day_bar.get("high") if isinstance(next_day_bar, dict) else None)
    return (
        float(open_p) if open_p is not None else None,
        float(close_p) if close_p is not None else None,
        float(high_p) if high_p is not None else None,
    )


def _max_high_n_days(bars: List[Any], alert_time: datetime, n_days: int) -> Optional[float]:
    """Max high across the next n trading days after alert."""
    if not bars:
        return None
    alert_time = _aware(alert_time)
    alert_date = alert_time.date()
    days_seen = 0
    highs: List[float] = []
    for bar in bars:
        ts = getattr(bar, "timestamp", None) or (bar.get("timestamp") if isinstance(bar, dict) else None)
        high = getattr(bar, "high", None) or (bar.get("high") if isinstance(bar, dict) else None)
        if ts is None or high is None:
            continue
        if isinstance(ts, str):
            try:
                ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except Exception:
                continue
        ts = _aware(ts)
        if ts.date() > alert_date:
            days_seen += 1
            highs.append(float(high))
            if days_seen >= n_days:
                break
    return max(highs) if highs else None


class NewsMomentumOutcomeResolver:
    """Resolves outcomes for sent Telegram alerts to feed back into learning."""

    def __init__(self, telegram_learning: "AdaptiveTelegramLearning") -> None:
        self.telegram_learning = telegram_learning

    def get_unresolved(self) -> List[TelegramAlertRecord]:
        """Return alerts that have not yet had their outcome resolved AND are
        recent enough to bother chasing."""
        now = _utcnow()
        cutoff = now - timedelta(days=MAX_RESOLVE_AGE_DAYS)
        unresolved: List[TelegramAlertRecord] = []
        for a in self.telegram_learning._alerts:
            if a.outcome is not None:
                continue
            sent = _aware(a.sent_at)
            if sent < cutoff:
                continue
            unresolved.append(a)
        return unresolved

    async def resolve_one(self, alert: TelegramAlertRecord) -> bool:
        """Try to resolve outcomes for a single alert. Returns True if any new
        data was filled in."""
        try:
            from src.services.market_data import get_market_data_provider
            provider = get_market_data_provider()
        except Exception as exc:
            logger.warning("OutcomeResolver: market data provider unavailable: %s", exc)
            return False

        ticker = alert.ticker
        sent_at = _aware(alert.sent_at)
        now = _utcnow()
        age_hours = (now - sent_at).total_seconds() / 3600.0

        # Fetch intraday minute bars for the alert day + next day
        intraday_bars: List[Any] = []
        daily_bars: List[Any] = []
        try:
            # 5d of minute data — plenty for 4h post-alert MFE/MAE
            intraday_bars = await asyncio.to_thread(
                provider.get_ohlcv, ticker, period="5d", interval="5m", prepost=True
            ) or []
        except Exception as exc:
            logger.debug("OutcomeResolver: intraday fetch failed for %s: %s", ticker, exc)

        try:
            # Daily bars for next_day / 2d / 5d follow-up
            daily_bars = await asyncio.to_thread(
                provider.get_ohlcv, ticker, period="10d", interval="1d", prepost=False
            ) or []
        except Exception as exc:
            logger.debug("OutcomeResolver: daily fetch failed for %s: %s", ticker, exc)

        if not intraday_bars and not daily_bars:
            return False

        # Compute price levels
        price_15m = price_1h = price_4h = None
        if intraday_bars:
            if age_hours >= 0.25:
                price_15m = _bar_close_at(intraday_bars, sent_at + timedelta(minutes=15))
            if age_hours >= 1.0:
                price_1h = _bar_close_at(intraday_bars, sent_at + timedelta(hours=1))
            if age_hours >= 4.0:
                price_4h = _bar_close_at(intraday_bars, sent_at + timedelta(hours=4))

        next_day_open = next_day_close = next_day_high = None
        if daily_bars and age_hours >= HOURS_BEFORE_NEXT_DAY:
            next_day_open, next_day_close, next_day_high = _next_day_open_close_high(daily_bars, sent_at)

        two_day_high = None
        if daily_bars and age_hours >= HOURS_BEFORE_TWO_DAY:
            two_day_high = _max_high_n_days(daily_bars, sent_at, n_days=2)

        five_day_high = None
        if daily_bars and age_hours >= HOURS_BEFORE_FIVE_DAY:
            five_day_high = _max_high_n_days(daily_bars, sent_at, n_days=5)

        # Skip if absolutely nothing new
        if all(v is None for v in [
            price_15m, price_1h, price_4h, next_day_open, next_day_close,
            next_day_high, two_day_high, five_day_high,
        ]):
            return False

        # If alert is older than 5 days, force a final resolve even with partial data
        # (so the AdaptiveTelegramLearning module classifies the outcome and we don't
        # keep retrying forever).
        force_final = age_hours >= HOURS_BEFORE_FIVE_DAY

        # Only call resolve_outcome when we have enough data, otherwise wait
        ready = (
            five_day_high is not None
            or (force_final and any(v is not None for v in [price_4h, next_day_close, two_day_high]))
        )
        if not ready:
            # Update partial fields on the record without classifying yet
            for field, value in [
                ("price_15m_later", price_15m),
                ("price_1h_later", price_1h),
                ("price_4h_later", price_4h),
                ("next_day_open", next_day_open),
                ("next_day_high", next_day_high),
                ("next_day_close", next_day_close),
                ("two_day_high", two_day_high),
            ]:
                if value is not None and getattr(alert, field, None) is None:
                    setattr(alert, field, value)
            # Compute forward-return percentages from whatever prices we
            # now have. The ML retrain reads these as magnitude labels —
            # without explicit return columns it would have to re-derive
            # them on every retrain and any change to the alert price field
            # would silently shift the labels.
            self._populate_forward_returns(alert)
            self.telegram_learning._save()
            return True

        try:
            self.telegram_learning.resolve_outcome(
                alert.alert_id,
                price_15m=price_15m or alert.price_15m_later,
                price_1h=price_1h or alert.price_1h_later,
                price_4h=price_4h or alert.price_4h_later,
                next_day_open=next_day_open or alert.next_day_open,
                next_day_high=next_day_high or alert.next_day_high,
                next_day_close=next_day_close or alert.next_day_close,
                two_day_high=two_day_high or alert.two_day_high,
                five_day_high=five_day_high or alert.five_day_high,
            )
            # Populate the forward-return labels now that prices are final.
            # See _populate_forward_returns for rationale.
            self._populate_forward_returns(alert)
            self.telegram_learning._save()
            return True
        except Exception as exc:
            logger.warning("OutcomeResolver: resolve_outcome failed for %s: %s", alert.alert_id, exc)
            return False

    @staticmethod
    def _populate_forward_returns(alert) -> None:
        """Compute forward-return percentages from stored prices.

        These are the multi-horizon LABELS the next ML retrain reads.
        Recording them explicitly (rather than re-deriving on every retrain)
        guarantees the labels are stable across pipeline changes and lets
        the model train on return MAGNITUDE — the difference between
        catching a 5% grinder and a 500% rocket. Skipped silently when the
        anchor price is missing or non-positive.
        """
        base = getattr(alert, "price_at_alert", None)
        if base is None or base <= 0:
            return

        def _pct(p):
            if p is None or p <= 0:
                return None
            return round((p / base - 1.0) * 100.0, 2)

        # Only OVERWRITE if the price column has a value — preserves
        # whatever the resolver has already settled into upstream.
        if alert.price_15m_later is not None:
            alert.return_15m_pct = _pct(alert.price_15m_later)
        if alert.price_1h_later is not None:
            alert.return_1h_pct = _pct(alert.price_1h_later)
        if alert.price_4h_later is not None:
            alert.return_4h_pct = _pct(alert.price_4h_later)
        if alert.next_day_close is not None:
            alert.return_next_day_close_pct = _pct(alert.next_day_close)
        if alert.next_day_high is not None:
            alert.return_next_day_high_pct = _pct(alert.next_day_high)
        if alert.two_day_high is not None:
            alert.return_two_day_high_pct = _pct(alert.two_day_high)
        if alert.five_day_high is not None:
            alert.return_five_day_high_pct = _pct(alert.five_day_high)

    async def run_once(self) -> dict:
        """Resolve all outstanding alerts. Returns a summary dict."""
        unresolved = self.get_unresolved()
        if not unresolved:
            return {"checked": 0, "resolved": 0, "updated": 0}
        resolved_count = 0
        updated_count = 0
        for alert in unresolved:
            had_outcome = alert.outcome is not None
            try:
                changed = await self.resolve_one(alert)
            except Exception as exc:
                logger.warning("OutcomeResolver: %s failed: %s", alert.ticker, exc)
                continue
            if changed:
                if alert.outcome is not None and not had_outcome:
                    resolved_count += 1
                else:
                    updated_count += 1
            # Be polite to data providers
            await asyncio.sleep(0.2)
        logger.info(
            "OutcomeResolver: checked=%d resolved=%d partial_update=%d",
            len(unresolved), resolved_count, updated_count,
        )
        return {
            "checked": len(unresolved),
            "resolved": resolved_count,
            "updated": updated_count,
        }
