import uuid
from datetime import datetime

from sqlalchemy import (
    Column, String, Float, Integer, Boolean, DateTime, ForeignKey, Text, JSON,
    TypeDecorator,
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


def _new_uuid():
    return str(uuid.uuid4())


class Signal(Base):
    __tablename__ = "signals"

    id = Column(String(36), primary_key=True, default=_new_uuid)
    ticker = Column(String(10), nullable=False, index=True)
    action = Column(String(20), nullable=False)
    classification = Column(String(30), nullable=False)
    dip_probability = Column(Float, nullable=True)
    bounce_probability = Column(Float, nullable=True)
    entry_price = Column(Float, nullable=True)
    stop_price = Column(Float, nullable=True)
    target_prices = Column(JSON, nullable=True)
    risk_score = Column(Integer, nullable=True)
    setup_grade = Column(String(1), nullable=True)
    confidence = Column(Float, nullable=True)
    signal_expiry = Column(DateTime, nullable=True)
    features_snapshot = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    expired_at = Column(DateTime, nullable=True)

    outcomes = relationship("SignalOutcome", back_populates="signal")
    trade_logs = relationship("TradeLog", back_populates="signal")


class SignalOutcome(Base):
    __tablename__ = "signal_outcomes"

    id = Column(String(36), primary_key=True, default=_new_uuid)
    signal_id = Column(String(36), ForeignKey("signals.id"), nullable=False)
    price_after_5m = Column(Float, nullable=True)
    price_after_15m = Column(Float, nullable=True)
    price_after_30m = Column(Float, nullable=True)
    price_after_60m = Column(Float, nullable=True)
    outcome = Column(String(10), default="unknown")
    pnl_percent = Column(Float, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    signal = relationship("Signal", back_populates="outcomes")


class ScanResult(Base):
    __tablename__ = "scan_results"

    id = Column(String(36), primary_key=True, default=_new_uuid)
    ticker = Column(String(10), nullable=False, index=True)
    price = Column(Float, nullable=False)
    volume = Column(Float, nullable=False)
    rvol = Column(Float, nullable=True)
    change_percent = Column(Float, nullable=True)
    market_cap = Column(Float, nullable=True)
    float_shares = Column(Float, nullable=True)
    scan_type = Column(String(20), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class Watchlist(Base):
    __tablename__ = "watchlist"

    id = Column(String(36), primary_key=True, default=_new_uuid)
    ticker = Column(String(10), nullable=False, unique=True, index=True)
    company_name = Column(String(120), nullable=True)
    added_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    active = Column(Boolean, default=True, nullable=False)

    # Source & context
    source = Column(String(30), default="manual")  # scanner, analysis, bearish, manual
    tags = Column(JSON, default=list)  # ["dip_candidate", "breakout_watch", ...]
    notes = Column(Text, nullable=True)
    watch_reason = Column(String(200), nullable=True)  # why user is watching

    # Priority
    priority = Column(String(10), default="medium")  # high, medium, low
    priority_score = Column(Float, default=50.0)  # numeric 0-100

    # Key levels
    support_level = Column(Float, nullable=True)
    resistance_level = Column(Float, nullable=True)
    invalidation_level = Column(Float, nullable=True)

    # Latest metrics snapshot (refreshed periodically)
    latest_price = Column(Float, nullable=True)
    latest_change_pct = Column(Float, nullable=True)
    latest_volume = Column(Float, nullable=True)
    latest_rvol = Column(Float, nullable=True)
    latest_dip_prob = Column(Float, nullable=True)
    latest_bounce_prob = Column(Float, nullable=True)
    latest_bearish_prob = Column(Float, nullable=True)
    latest_regime = Column(String(30), nullable=True)
    latest_stage = Column(Integer, nullable=True)
    latest_in_play = Column(String(20), nullable=True)  # active, fading, dead
    latest_extension = Column(String(20), nullable=True)
    latest_liquidity_score = Column(Float, nullable=True)
    latest_rejection_risk = Column(Float, nullable=True)
    latest_final_score = Column(Float, nullable=True)
    metrics_updated_at = Column(DateTime, nullable=True)
    
    # V8: Higher Timeframe (HTF) Analysis snapshot
    latest_htf_bias = Column(String(20), nullable=True)  # BULLISH/NEUTRAL/BEARISH
    latest_htf_strength_score = Column(Float, nullable=True)  # 0-100
    latest_alignment_status = Column(String(30), nullable=True)  # ALIGNED/NEUTRAL/COUNTER_TREND
    latest_trade_type = Column(String(30), nullable=True)  # TREND_FOLLOWING/COUNTER_TREND_REVERSAL
    latest_htf_blocked = Column(Boolean, default=False)  # True if HTF filter blocked
    latest_htf_alignment_reason = Column(String(255), nullable=True)  # Block/allow reason
    latest_htf_rsi = Column(Float, nullable=True)  # HTF RSI value
    latest_htf_adx = Column(Float, nullable=True)  # HTF ADX value
    latest_htf_updated_at = Column(DateTime, nullable=True)  # When HTF was last calculated

    # Alert state
    latest_alert = Column(String(100), nullable=True)
    latest_alert_at = Column(DateTime, nullable=True)
    alert_count = Column(Integer, default=0)

    # Status
    status = Column(String(20), default="active")  # active, archived, inactive
    archived_at = Column(DateTime, nullable=True)
    archive_reason = Column(String(100), nullable=True)

    # Analysis snapshot when added
    analysis_snapshot = Column(JSON, nullable=True)

    # Earnings calendar
    next_earnings_date = Column(DateTime, nullable=True)
    earnings_warning_shown = Column(Boolean, default=False)

    # Relationships
    alerts = relationship("WatchlistAlert", back_populates="watchlist_item", cascade="all, delete-orphan")
    timeline = relationship("WatchlistTimeline", back_populates="watchlist_item", cascade="all, delete-orphan")


class WatchlistAlert(Base):
    __tablename__ = "watchlist_alerts"

    id = Column(String(36), primary_key=True, default=_new_uuid)
    watchlist_id = Column(String(36), ForeignKey("watchlist.id"), nullable=False)
    alert_type = Column(String(50), nullable=False)  # dip_detected, bounce_confirmed, bearish_warning, etc.
    severity = Column(String(20), default="info")  # info, warning, critical
    message = Column(String(500), nullable=False)
    data = Column(JSON, nullable=True)  # extra alert data
    read = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    watchlist_item = relationship("Watchlist", back_populates="alerts")


class WatchlistTimeline(Base):
    __tablename__ = "watchlist_timeline"

    id = Column(String(36), primary_key=True, default=_new_uuid)
    watchlist_id = Column(String(36), ForeignKey("watchlist.id"), nullable=False)
    event_type = Column(String(50), nullable=False)  # added, alert, metrics_update, note_edit, archived, etc.
    description = Column(String(500), nullable=False)
    data = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    watchlist_item = relationship("Watchlist", back_populates="timeline")


class TradeLog(Base):
    __tablename__ = "trade_logs"

    id = Column(String(36), primary_key=True, default=_new_uuid)
    signal_id = Column(String(36), ForeignKey("signals.id"), nullable=True)
    ticker = Column(String(10), nullable=False, index=True)
    event_type = Column(String(50), nullable=False)
    details = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    signal = relationship("Signal", back_populates="trade_logs")


class CustomAlert(Base):
    """User-defined price alerts (target price, stop loss, etc.)."""
    __tablename__ = "custom_alerts"

    id = Column(String(36), primary_key=True, default=_new_uuid)
    ticker = Column(String(10), nullable=False, index=True)

    # Alert condition
    alert_type = Column(String(20), nullable=False)  # price_above, price_below, percent_change, rvol_above
    target_value = Column(Float, nullable=False)  # price level or percentage

    # Optional reference price (for percent_change alerts)
    reference_price = Column(Float, nullable=True)

    # Status
    is_active = Column(Boolean, default=True)
    triggered_at = Column(DateTime, nullable=True)
    triggered_price = Column(Float, nullable=True)

    # Notification
    message = Column(String(200), nullable=True)
    notification_sent = Column(Boolean, default=False)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    expires_at = Column(DateTime, nullable=True)
