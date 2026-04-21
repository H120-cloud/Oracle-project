import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from src.models.database import Signal, SignalOutcome, ScanResult, Watchlist, WatchlistAlert, WatchlistTimeline, TradeLog, CustomAlert


class SignalRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, signal: Signal) -> Signal:
        self.db.add(signal)
        self.db.commit()
        self.db.refresh(signal)
        return signal

    def get_by_id(self, signal_id: uuid.UUID) -> Optional[Signal]:
        return self.db.query(Signal).filter(Signal.id == signal_id).first()

    def get_recent(self, limit: int = 50) -> list[Signal]:
        return (
            self.db.query(Signal)
            .order_by(Signal.created_at.desc())
            .limit(limit)
            .all()
        )

    def get_active(self) -> list[Signal]:
        now = datetime.utcnow()
        return (
            self.db.query(Signal)
            .filter(Signal.expired_at.is_(None) | (Signal.signal_expiry > now))
            .order_by(Signal.created_at.desc())
            .all()
        )


class SignalOutcomeRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, outcome: SignalOutcome) -> SignalOutcome:
        self.db.add(outcome)
        self.db.commit()
        self.db.refresh(outcome)
        return outcome

    def get_by_signal(self, signal_id: uuid.UUID) -> Optional[SignalOutcome]:
        return (
            self.db.query(SignalOutcome)
            .filter(SignalOutcome.signal_id == signal_id)
            .first()
        )


class ScanResultRepository:
    def __init__(self, db: Session):
        self.db = db

    def create_batch(self, results: list[ScanResult]) -> list[ScanResult]:
        self.db.add_all(results)
        self.db.commit()
        return results

    def get_latest(self, scan_type: str, limit: int = 20) -> list[ScanResult]:
        return (
            self.db.query(ScanResult)
            .filter(ScanResult.scan_type == scan_type)
            .order_by(ScanResult.created_at.desc())
            .limit(limit)
            .all()
        )


class WatchlistRepository:
    def __init__(self, db: Session):
        self.db = db

    def add(self, ticker: str, **kwargs) -> Watchlist:
        item = Watchlist(ticker=ticker.upper(), **kwargs)
        self.db.add(item)
        self.db.commit()
        self.db.refresh(item)
        # Add timeline entry
        self._add_timeline(item.id, "added", f"{ticker.upper()} added to watchlist", {
            "source": kwargs.get("source", "manual"),
            "watch_reason": kwargs.get("watch_reason"),
        })
        return item

    def get_by_id(self, watchlist_id: str) -> Optional[Watchlist]:
        return self.db.query(Watchlist).filter(Watchlist.id == watchlist_id).first()

    def get_by_ticker(self, ticker: str) -> Optional[Watchlist]:
        return (
            self.db.query(Watchlist)
            .filter(Watchlist.ticker == ticker.upper())
            .first()
        )

    def update(self, ticker: str, **kwargs) -> Optional[Watchlist]:
        item = self.get_by_ticker(ticker)
        if not item:
            return None
        for key, value in kwargs.items():
            if value is not None and hasattr(item, key):
                setattr(item, key, value)
        item.updated_at = datetime.utcnow()
        self.db.commit()
        self.db.refresh(item)
        self._add_timeline(item.id, "updated", f"{ticker.upper()} watchlist entry updated", {
            "fields_updated": list(kwargs.keys()),
        })
        return item

    def remove(self, ticker: str) -> bool:
        item = self.get_by_ticker(ticker)
        if item:
            self.db.delete(item)
            self.db.commit()
            return True
        return False

    def archive(self, ticker: str, reason: str = "manual") -> Optional[Watchlist]:
        item = self.get_by_ticker(ticker)
        if not item:
            return None
        item.status = "archived"
        item.active = False
        item.archived_at = datetime.utcnow()
        item.archive_reason = reason
        self.db.commit()
        self.db.refresh(item)
        self._add_timeline(item.id, "archived", f"{ticker.upper()} archived: {reason}")
        return item

    def restore(self, ticker: str) -> Optional[Watchlist]:
        item = self.get_by_ticker(ticker)
        if not item:
            return None
        item.status = "active"
        item.active = True
        item.archived_at = None
        item.archive_reason = None
        self.db.commit()
        self.db.refresh(item)
        self._add_timeline(item.id, "restored", f"{ticker.upper()} restored to active watchlist")
        return item

    def get_all_active(self) -> list[Watchlist]:
        return (
            self.db.query(Watchlist)
            .filter(Watchlist.active.is_(True), Watchlist.status == "active")
            .order_by(Watchlist.priority_score.desc())
            .all()
        )

    def get_all(self, include_archived: bool = False) -> list[Watchlist]:
        q = self.db.query(Watchlist)
        if not include_archived:
            q = q.filter(Watchlist.status != "archived")
        return q.order_by(Watchlist.priority_score.desc()).all()

    def update_metrics(self, ticker: str, metrics: dict) -> Optional[Watchlist]:
        item = self.get_by_ticker(ticker)
        if not item:
            return None
        for key, value in metrics.items():
            col = f"latest_{key}" if not key.startswith("latest_") else key
            if hasattr(item, col):
                setattr(item, col, value)
        item.metrics_updated_at = datetime.utcnow()
        self.db.commit()
        self.db.refresh(item)
        return item

    # ── Alerts ───────────────────────────────────────────────────────────────

    def add_alert(self, watchlist_id: str, alert_type: str, message: str,
                  severity: str = "info", data: dict = None) -> WatchlistAlert:
        alert = WatchlistAlert(
            watchlist_id=watchlist_id,
            alert_type=alert_type,
            severity=severity,
            message=message,
            data=data or {},
        )
        self.db.add(alert)
        # Update parent
        item = self.get_by_id(watchlist_id)
        if item:
            item.latest_alert = f"{alert_type}: {message[:80]}"
            item.latest_alert_at = datetime.utcnow()
            item.alert_count = (item.alert_count or 0) + 1
        self.db.commit()
        self.db.refresh(alert)
        self._add_timeline(watchlist_id, "alert", message, {"alert_type": alert_type, "severity": severity})
        return alert

    def get_alerts(self, watchlist_id: str, limit: int = 50) -> list[WatchlistAlert]:
        return (
            self.db.query(WatchlistAlert)
            .filter(WatchlistAlert.watchlist_id == watchlist_id)
            .order_by(WatchlistAlert.created_at.desc())
            .limit(limit)
            .all()
        )

    def get_all_unread_alerts(self) -> list[WatchlistAlert]:
        return (
            self.db.query(WatchlistAlert)
            .filter(WatchlistAlert.read.is_(False))
            .order_by(WatchlistAlert.created_at.desc())
            .all()
        )

    def mark_alert_read(self, alert_id: str) -> bool:
        alert = self.db.query(WatchlistAlert).filter(WatchlistAlert.id == alert_id).first()
        if alert:
            alert.read = True
            self.db.commit()
            return True
        return False

    # ── Timeline ─────────────────────────────────────────────────────────────

    def _add_timeline(self, watchlist_id: str, event_type: str, description: str, data: dict = None):
        entry = WatchlistTimeline(
            watchlist_id=watchlist_id,
            event_type=event_type,
            description=description,
            data=data or {},
        )
        self.db.add(entry)
        self.db.commit()

    def get_timeline(self, watchlist_id: str, limit: int = 100) -> list[WatchlistTimeline]:
        return (
            self.db.query(WatchlistTimeline)
            .filter(WatchlistTimeline.watchlist_id == watchlist_id)
            .order_by(WatchlistTimeline.created_at.desc())
            .limit(limit)
            .all()
        )


class TradeLogRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, log: TradeLog) -> TradeLog:
        self.db.add(log)
        self.db.commit()
        self.db.refresh(log)
        return log


class CustomAlertRepository:
    """User-defined price alerts repository."""

    def __init__(self, db: Session):
        self.db = db

    def create(self, ticker: str, alert_type: str, target_value: float,
               reference_price: float = None, message: str = None,
               expires_at: datetime = None) -> CustomAlert:
        alert = CustomAlert(
            ticker=ticker.upper(),
            alert_type=alert_type,
            target_value=target_value,
            reference_price=reference_price,
            message=message,
            expires_at=expires_at,
            is_active=True,
        )
        self.db.add(alert)
        self.db.commit()
        self.db.refresh(alert)
        return alert

    def get_active_for_ticker(self, ticker: str) -> list[CustomAlert]:
        """Get all active alerts for a ticker."""
        return (
            self.db.query(CustomAlert)
            .filter(
                CustomAlert.ticker == ticker.upper(),
                CustomAlert.is_active.is_(True),
            )
            .all()
        )

    def get_all_active(self) -> list[CustomAlert]:
        """Get all active alerts across all tickers."""
        return (
            self.db.query(CustomAlert)
            .filter(CustomAlert.is_active.is_(True))
            .order_by(CustomAlert.created_at.desc())
            .all()
        )

    def mark_triggered(self, alert_id: str, triggered_price: float):
        """Mark an alert as triggered."""
        alert = self.db.query(CustomAlert).filter(CustomAlert.id == alert_id).first()
        if alert:
            alert.is_active = False
            alert.triggered_at = datetime.utcnow()
            alert.triggered_price = triggered_price
            self.db.commit()
            return True
        return False

    def delete(self, alert_id: str) -> bool:
        alert = self.db.query(CustomAlert).filter(CustomAlert.id == alert_id).first()
        if alert:
            self.db.delete(alert)
            self.db.commit()
            return True
        return False

    def get_by_id(self, alert_id: str) -> Optional[CustomAlert]:
        return self.db.query(CustomAlert).filter(CustomAlert.id == alert_id).first()

    def get_by_ticker(self, ticker: str, limit: int = 100) -> list[CustomAlert]:
        """Get all alerts (active and triggered) for a ticker."""
        return (
            self.db.query(CustomAlert)
            .filter(CustomAlert.ticker == ticker.upper())
            .order_by(CustomAlert.created_at.desc())
            .limit(limit)
            .all()
        )
