"""
Watchlist Service — monitors watchlist stocks, detects events, triggers alerts.

Responsibilities:
1. Refresh metrics for all active watchlist items
2. Detect events (dip forming, bounce, breakout, bearish shift, etc.)
3. Create alerts when conditions change
4. Auto-archive stale/dead stocks
5. V9: HTF context change detection and alerting
"""

import logging
from datetime import datetime
from typing import Optional, List

from sqlalchemy.orm import Session

from src.db.repositories import WatchlistRepository
from src.services.market_data import get_market_data_provider
from src.services.htf_alert_service import get_htf_alert_service, HTFAlert
from src.core.higher_timeframe_bias import HigherTimeframeBiasDetector
from src.models.database import Watchlist

logger = logging.getLogger(__name__)


class WatchlistService:
    """Manages watchlist monitoring, event detection, and alerts."""

    def __init__(self, db: Session):
        self.db = db
        self.repo = WatchlistRepository(db)
        self.provider = get_market_data_provider()
        self.htf_alert_service = get_htf_alert_service()
        self.htf_detector = HigherTimeframeBiasDetector()

    # ── Refresh Metrics ──────────────────────────────────────────────────────

    def refresh_all(self) -> dict:
        """Refresh metrics for all active watchlist items."""
        items = self.repo.get_all_active()
        if not items:
            return {"refreshed": 0, "alerts_generated": 0}

        refreshed = 0
        alerts_generated = 0

        for item in items:
            try:
                metrics = self._fetch_metrics(item.ticker)
                if metrics:
                    # Detect events BEFORE updating (compare old vs new)
                    new_alerts = self._detect_events(item, metrics)
                    alerts_generated += len(new_alerts)

                    # Update metrics
                    self.repo.update_metrics(item.ticker, metrics)
                    refreshed += 1

                    # Auto-archive check
                    self._check_auto_archive(item, metrics)

            except Exception as exc:
                logger.warning("Failed to refresh %s: %s", item.ticker, exc)

        logger.info(
            "Watchlist refresh: %d/%d refreshed, %d alerts",
            refreshed, len(items), alerts_generated,
        )
        return {"refreshed": refreshed, "total": len(items), "alerts_generated": alerts_generated}

    def refresh_one(self, ticker: str) -> Optional[dict]:
        """Refresh metrics for a single watchlist item."""
        item = self.repo.get_by_ticker(ticker)
        if not item:
            return None

        metrics = self._fetch_metrics(ticker)
        if not metrics:
            return None

        alerts = self._detect_events(item, metrics)
        self.repo.update_metrics(ticker, metrics)
        self._check_auto_archive(item, metrics)

        # Check custom price alerts
        custom_alerts = self._check_custom_alerts(ticker, metrics)

        return {"ticker": ticker, "metrics": metrics, "alerts": len(alerts), "custom_alerts": custom_alerts}

    # ── Fetch Metrics ────────────────────────────────────────────────────────

    def _fetch_metrics(self, ticker: str) -> Optional[dict]:
        """Fetch current metrics for a ticker."""
        try:
            # Try 1d/1m first (market hours), fall back to 5d/1d (after hours)
            bars = self.provider.get_ohlcv(ticker, period="1d", interval="1m")
            if bars is None or len(bars) < 10:
                bars = self.provider.get_ohlcv(ticker, period="5d", interval="1d")
                if bars is None or len(bars) < 2:
                    return None

            # bars is list[OHLCVBar] - access attributes directly
            price = float(bars[-1].close)
            open_price = float(bars[0].open) if len(bars) > 1 else price
            volume = sum(b.volume for b in bars)
            change_pct = ((price - open_price) / open_price * 100) if open_price and open_price > 0 else 0

            # RVOL
            import yfinance as yf
            tkr = yf.Ticker(ticker)
            try:
                avg_vol = getattr(tkr.fast_info, "three_month_average_volume", None)
                rvol = volume / avg_vol if avg_vol and avg_vol > 0 else None
            except Exception:
                rvol = None

            metrics = {
                "price": round(price, 4),
                "change_pct": round(change_pct, 2),
                "volume": volume,
                "rvol": round(rvol, 2) if rvol else None,
            }

            # Advanced metrics via market_data provider (optional)
            try:
                dip_features = self.provider.compute_dip_features(ticker)
                if dip_features:
                    from src.core.dip_detector import DipDetector
                    dip_result = DipDetector().detect(ticker, dip_features)
                    if dip_result:
                        metrics["dip_prob"] = round(dip_result.probability, 1)
            except Exception:
                pass

            try:
                bounce_features, _ = self.provider.compute_bounce_features(ticker)
                if bounce_features:
                    from src.core.bounce_detector import BounceDetector
                    bounce_result = BounceDetector().detect(ticker, bounce_features, price)
                    if bounce_result:
                        metrics["bounce_prob"] = round(bounce_result.probability, 1)
            except Exception:
                pass

            # Bearish detection (optional, volume_profile not required)
            try:
                from src.core.bearish_detector import BearishDetector
                bearish_result = BearishDetector().detect(ticker, bars)
                if bearish_result:
                    metrics["bearish_prob"] = round(bearish_result.bearish_probability, 1)
            except Exception:
                pass
            
            # V8: HTF (Higher Timeframe) Analysis
            try:
                daily_bars = self.provider.get_ohlcv(ticker, period="3mo", interval="1d")
                if daily_bars and len(daily_bars) >= 50:
                    htf_result = self.htf_detector.detect_bias(ticker, daily_bars)
                    if htf_result:
                        metrics["htf_bias"] = htf_result.bias.value
                        metrics["htf_strength_score"] = round(htf_result.strength_score, 1)
                        metrics["htf_structure_score"] = round(htf_result.structure_score, 1)
                        metrics["htf_ema_score"] = round(htf_result.ema_alignment_score, 1)
                        metrics["htf_momentum_score"] = round(htf_result.momentum_score, 1)
                        metrics["htf_adx_score"] = round(htf_result.adx_score, 1)
                        metrics["htf_rsi"] = round(htf_result.rsi, 1) if htf_result.rsi else None
                        metrics["htf_adx"] = round(htf_result.adx, 1) if htf_result.adx else None
                        metrics["htf_updated_at"] = datetime.utcnow().isoformat()
            except Exception as exc:
                logger.debug("HTF detection skipped for %s: %s", ticker, exc)

            return metrics

        except Exception as exc:
            logger.warning("Failed to fetch metrics for %s: %s", ticker, exc)
            return None

    # ── Event Detection ──────────────────────────────────────────────────────

    def _detect_events(self, item: Watchlist, new_metrics: dict) -> list:
        """Compare old metrics with new to detect significant events."""
        alerts = []

        price = new_metrics.get("price")
        old_price = item.latest_price
        dip_prob = new_metrics.get("dip_prob")
        bounce_prob = new_metrics.get("bounce_prob")
        bearish_prob = new_metrics.get("bearish_prob")
        rvol = new_metrics.get("rvol")
        change_pct = new_metrics.get("change_pct", 0)

        # 1. Dip detected (probability crossed above 60%)
        if dip_prob and dip_prob >= 60:
            old_dip = item.latest_dip_prob or 0
            if old_dip < 60:
                alerts.append(self._create_alert(
                    item, "dip_detected", "warning",
                    f"{item.ticker} dip forming — probability {dip_prob}%",
                    {"dip_prob": dip_prob},
                ))

        # 2. Bounce confirmation (probability crossed above 65%)
        if bounce_prob and bounce_prob >= 65:
            old_bounce = item.latest_bounce_prob or 0
            if old_bounce < 65:
                alerts.append(self._create_alert(
                    item, "bounce_confirmed", "critical",
                    f"{item.ticker} bounce confirmed — probability {bounce_prob}%",
                    {"bounce_prob": bounce_prob},
                ))

        # 3. Bearish warning (probability crossed above 50%)
        if bearish_prob and bearish_prob >= 50:
            old_bearish = item.latest_bearish_prob or 0
            if old_bearish < 50:
                alerts.append(self._create_alert(
                    item, "bearish_warning", "critical",
                    f"{item.ticker} bearish transition — probability {bearish_prob}%",
                    {"bearish_prob": bearish_prob},
                ))

        # 4. Volume surge (RVOL > 3x)
        if rvol and rvol >= 3.0:
            old_rvol = item.latest_rvol or 0
            if old_rvol < 3.0:
                alerts.append(self._create_alert(
                    item, "volume_surge", "warning",
                    f"{item.ticker} unusual volume — RVOL {rvol}x",
                    {"rvol": rvol},
                ))

        # 5. Big move (change > 5% or < -5%)
        if abs(change_pct) >= 5:
            direction = "up" if change_pct > 0 else "down"
            alerts.append(self._create_alert(
                item, "big_move", "warning",
                f"{item.ticker} moved {change_pct:+.1f}% ({direction})",
                {"change_pct": change_pct},
            ))

        # 6. Support/resistance approach
        if price and item.support_level:
            dist_to_support = ((price - item.support_level) / price) * 100
            if 0 < dist_to_support < 2:
                alerts.append(self._create_alert(
                    item, "near_support", "info",
                    f"{item.ticker} approaching support ${item.support_level:.2f} ({dist_to_support:.1f}% away)",
                    {"support_level": item.support_level, "distance_pct": dist_to_support},
                ))

        if price and item.resistance_level:
            dist_to_resistance = ((item.resistance_level - price) / price) * 100
            if 0 < dist_to_resistance < 2:
                alerts.append(self._create_alert(
                    item, "near_resistance", "info",
                    f"{item.ticker} approaching resistance ${item.resistance_level:.2f} ({dist_to_resistance:.1f}% away)",
                    {"resistance_level": item.resistance_level, "distance_pct": dist_to_resistance},
                ))

        # 7. Invalidation level breached
        if price and item.invalidation_level:
            if old_price and old_price > item.invalidation_level and price <= item.invalidation_level:
                alerts.append(self._create_alert(
                    item, "invalidation_breached", "critical",
                    f"{item.ticker} broke below invalidation level ${item.invalidation_level:.2f}",
                    {"invalidation_level": item.invalidation_level, "price": price},
                ))

        return alerts

    def _create_alert(self, item: Watchlist, alert_type: str, severity: str,
                      message: str, data: dict = None):
        """Create and persist an alert."""
        return self.repo.add_alert(item.id, alert_type, message, severity, data)

    # ── Auto Archive ─────────────────────────────────────────────────────────

    def _check_auto_archive(self, item: Watchlist, metrics: dict):
        """Auto-archive stocks that are no longer worth watching."""
        reasons = []

        rvol = metrics.get("rvol")
        if rvol is not None and rvol < 0.3:
            reasons.append("very_low_volume")

        change_pct = metrics.get("change_pct", 0)
        if abs(change_pct) < 0.2 and (rvol is not None and rvol < 0.5):
            reasons.append("dead_stock")

        # Don't auto-archive if user set high priority
        if item.priority == "high":
            return

        if len(reasons) >= 2:
            self.repo.archive(item.ticker, reason=f"auto: {', '.join(reasons)}")
            logger.info("Auto-archived %s: %s", item.ticker, reasons)

    # ── Custom Price Alerts ────────────────────────────────────────────────────

    def _check_custom_alerts(self, ticker: str, metrics: dict) -> list:
        """Check if any custom price alerts are triggered."""
        from src.db.repositories import CustomAlertRepository

        triggered = []
        alert_repo = CustomAlertRepository(self.db)
        alerts = alert_repo.get_active_for_ticker(ticker)

        if not alerts:
            return triggered

        price = metrics.get("price")
        rvol = metrics.get("rvol")

        for alert in alerts:
            is_triggered = False
            trigger_price = None

            if alert.alert_type == "price_above" and price and price >= alert.target_value:
                is_triggered = True
                trigger_price = price

            elif alert.alert_type == "price_below" and price and price <= alert.target_value:
                is_triggered = True
                trigger_price = price

            elif alert.alert_type == "percent_change_up" and alert.reference_price and price:
                change_pct = ((price - alert.reference_price) / alert.reference_price) * 100
                if change_pct >= alert.target_value:
                    is_triggered = True
                    trigger_price = price

            elif alert.alert_type == "percent_change_down" and alert.reference_price and price:
                change_pct = ((price - alert.reference_price) / alert.reference_price) * 100
                if change_pct <= -alert.target_value:
                    is_triggered = True
                    trigger_price = price

            elif alert.alert_type == "rvol_above" and rvol and rvol >= alert.target_value:
                is_triggered = True
                trigger_price = price

            if is_triggered:
                alert_repo.mark_triggered(alert.id, trigger_price)
                # Create watchlist alert
                self.repo.add_alert(
                    self.repo.get_by_ticker(ticker).id,
                    "custom_alert_triggered",
                    alert.message or f"Custom alert: {alert.alert_type} triggered at ${trigger_price:.2f}",
                    "critical",
                    {"alert_type": alert.alert_type, "target": alert.target_value, "triggered_at": trigger_price},
                )
                triggered.append({
                    "id": alert.id,
                    "type": alert.alert_type,
                    "message": alert.message,
                    "triggered_price": trigger_price,
                })

        return triggered

    def refresh_earnings_dates(self):
        """Fetch upcoming earnings dates for all watchlist items."""
        from datetime import timedelta
        import yfinance as yf

        items = self.repo.get_all_active()
        updated = 0

        for item in items:
            try:
                ticker = yf.Ticker(item.ticker)
                # Try to get earnings date from calendar
                calendar = ticker.calendar
                if calendar is not None and not calendar.empty:
                    # Get the next earnings date
                    earnings_date = calendar.iloc[0, 0] if hasattr(calendar, 'iloc') else None
                    if earnings_date:
                        # Convert to datetime if needed
                        if isinstance(earnings_date, str):
                            from dateutil import parser
                            earnings_date = parser.parse(earnings_date)

                        # Update if different or not set
                        if item.next_earnings_date != earnings_date:
                            self.db.query(Watchlist).filter(Watchlist.id == item.id).update({
                                "next_earnings_date": earnings_date,
                                "earnings_warning_shown": False,
                            })
                            self.db.commit()
                            updated += 1
                            logger.info("Updated earnings date for %s: %s", item.ticker, earnings_date)

            except Exception as exc:
                logger.warning("Failed to fetch earnings for %s: %s", item.ticker, exc)
                continue

        return {"checked": len(items), "updated": updated}

    def check_earnings_warnings(self) -> list:
        """Check for earnings warnings (within 2 days)."""
        from datetime import timedelta
        warnings = []

        items = self.repo.get_all_active()
        now = datetime.utcnow()

        for item in items:
            if not item.next_earnings_date:
                continue

            days_until = (item.next_earnings_date - now).days

            # Warn if earnings within 2 days and not already warned
            if 0 <= days_until <= 2 and not item.earnings_warning_shown:
                self.repo.add_alert(
                    item.id,
                    "earnings_soon",
                    "warning",
                    f"{item.ticker} earnings in {days_until} day{'s' if days_until != 1 else ''} ({item.next_earnings_date.strftime('%Y-%m-%d')})",
                    {"earnings_date": item.next_earnings_date.isoformat(), "days_until": days_until},
                )
                # Mark as warned
                item.earnings_warning_shown = True
                self.db.commit()
                warnings.append({"ticker": item.ticker, "days_until": days_until})

        return warnings

    # ── HTF Change Detection ────────────────────────────────────────────────

    def check_htf_changes(self) -> dict:
        """Check all active watchlist items for HTF context changes.
        
        Returns:
            Dict with htf_alerts list and statistics.
        """
        items = self.repo.get_all_active()
        alerts = []
        
        for item in items:
            try:
                # Get current HTF state
                htf_alert = self._detect_htf_change_for_item(item)
                if htf_alert:
                    # Create database alert
                    self._create_htf_database_alert(item, htf_alert)
                    alerts.append(htf_alert)
                    
            except Exception as e:
                logger.warning(f"[{item.ticker}] HTF check failed: {e}")
                continue
        
        return {
            "htf_alerts_generated": len(alerts),
            "by_severity": self._summarize_alerts(alerts),
            "alerts": [{"ticker": a.ticker, "type": a.alert_type.value, "msg": a.explanation} for a in alerts[:5]]
        }
    
    def check_htf_for_ticker(self, ticker: str) -> Optional[HTFAlert]:
        """Check HTF changes for a single ticker."""
        item = self.repo.get_by_ticker(ticker)
        if not item:
            return None
        return self._detect_htf_change_for_item(item)
    
    def _detect_htf_change_for_item(self, item) -> Optional[HTFAlert]:
        """Detect HTF changes for a watchlist item."""
        try:
            # Fetch daily bars for HTF analysis
            daily_bars = self.provider.get_ohlcv(item.ticker, period="3mo", interval="1d")
            if len(daily_bars) < 50:
                return None
            
            # Get HTF result
            htf_result = self.htf_detector.detect_bias(item.ticker, daily_bars)
            
            # Build current state
            current_state = {
                'bias': htf_result.bias.value if htf_result else item.latest_htf_bias,
                'alignment': item.latest_alignment_status,
                'strength': htf_result.strength_score if htf_result else item.latest_htf_strength_score,
                'blocked': item.latest_htf_blocked
            }
            
            # Check for changes using alert service
            alert = self.htf_alert_service._detect_change(item.ticker, current_state)
            return alert
            
        except Exception as e:
            logger.warning(f"[{item.ticker}] HTF detection error: {e}")
            return None
    
    def _create_htf_database_alert(self, item, alert: HTFAlert):
        """Persist HTF alert to database."""
        self.repo.add_alert(
            item.id,
            f"htf_{alert.alert_type.value}",
            alert.severity,
            alert.explanation,
            {
                "previous_bias": alert.previous_bias,
                "new_bias": alert.new_bias,
                "previous_strength": alert.previous_strength,
                "new_strength": alert.new_strength,
                "timestamp": alert.timestamp
            }
        )
        self.db.commit()
        logger.info(f"[{item.ticker}] HTF alert created: {alert.explanation}")
    
    def _summarize_alerts(self, alerts: List[HTFAlert]) -> dict:
        """Summarize alerts by severity."""
        counts = {"critical": 0, "warning": 0, "info": 0}
        for alert in alerts:
            counts[alert.severity] = counts.get(alert.severity, 0) + 1
        return counts
