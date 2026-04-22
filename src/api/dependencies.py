"""
FastAPI dependency injection providers.
"""

from typing import Generator

from sqlalchemy.orm import Session

from src.db.session import get_db
from src.services.signal_service import SignalService
from src.services.logging_service import LoggingService
from src.services.market_data import get_market_data_provider


def get_signal_service(db: Session) -> SignalService:
    return SignalService(db=db, market_data=get_market_data_provider())


def get_logging_service(db: Session) -> LoggingService:
    return LoggingService(db=db)
