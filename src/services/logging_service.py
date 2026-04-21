"""
Logging Service — V2

Persists signals, outcomes, and trade events to the database.
Stores full feature snapshots for ML training.
"""

import logging
import uuid
import dataclasses
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from src.models.database import Signal as SignalModel, SignalOutcome as SignalOutcomeModel, TradeLog as TradeLogModel
from src.models.schemas import TradingSignal, DipFeatures, BounceFeatures, ICTFeatures, OutcomeRecord
from src.db.repositories import (
    SignalRepository,
    SignalOutcomeRepository,
    TradeLogRepository,
)


def _to_dict(obj):
    """Convert object to dict, handling both Pydantic models and dataclasses."""
    if obj is None:
        return None
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if hasattr(obj, "__dataclass_fields__"):
        return dataclasses.asdict(obj)
    return obj

logger = logging.getLogger(__name__)


class LoggingService:
    """Handles persistence of signals, outcomes, and events."""

    def __init__(self, db: Session):
        self.signal_repo = SignalRepository(db)
        self.outcome_repo = SignalOutcomeRepository(db)
        self.trade_log_repo = TradeLogRepository(db)

    def log_signal(
        self,
        signal: TradingSignal,
        dip_features: Optional[DipFeatures] = None,
        bounce_features: Optional[BounceFeatures] = None,
        ict_features: Optional[ICTFeatures] = None,
    ) -> SignalModel:
        """Persist a generated trading signal with full feature snapshot for ML."""
        snapshot = {
            "reason": signal.reason,
        }
        if dip_features is not None:
            snapshot["dip_features"] = _to_dict(dip_features)
        if bounce_features is not None:
            snapshot["bounce_features"] = _to_dict(bounce_features)
        if ict_features is not None:
            snapshot["ict_features"] = _to_dict(ict_features)

        db_signal = SignalModel(
            ticker=signal.ticker,
            action=signal.action.value,
            classification=signal.classification.value,
            dip_probability=signal.dip_probability,
            bounce_probability=signal.bounce_probability,
            entry_price=signal.entry_price,
            stop_price=signal.stop_price,
            target_prices=signal.target_prices,
            risk_score=signal.risk_score,
            setup_grade=signal.setup_grade,
            confidence=signal.confidence,
            signal_expiry=signal.signal_expiry,
            features_snapshot=snapshot,
            created_at=signal.created_at or datetime.utcnow(),
        )
        saved = self.signal_repo.create(db_signal)
        logger.info(
            "Signal logged: %s %s %s (id=%s)",
            saved.ticker, saved.action, saved.classification, saved.id,
        )
        return saved

    def log_outcome(self, outcome: OutcomeRecord) -> SignalOutcomeModel:
        """Persist an outcome observation for a signal."""
        db_outcome = SignalOutcomeModel(
            signal_id=outcome.signal_id,
            price_after_5m=outcome.price_after_5m,
            price_after_15m=outcome.price_after_15m,
            price_after_30m=outcome.price_after_30m,
            price_after_60m=outcome.price_after_60m,
            outcome=outcome.outcome.value,
            pnl_percent=outcome.pnl_percent,
        )
        saved = self.outcome_repo.create(db_outcome)
        logger.info("Outcome logged for signal %s: %s", outcome.signal_id, outcome.outcome.value)
        return saved

    def log_event(
        self,
        ticker: str,
        event_type: str,
        details: dict | None = None,
        signal_id: uuid.UUID | None = None,
    ) -> TradeLogModel:
        """Log a generic trade/system event."""
        db_log = TradeLogModel(
            signal_id=signal_id,
            ticker=ticker,
            event_type=event_type,
            details=details or {},
        )
        saved = self.trade_log_repo.create(db_log)
        logger.debug("Event logged: %s %s", ticker, event_type)
        return saved
