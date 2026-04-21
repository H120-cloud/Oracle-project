"""
Signals API routes — generate and retrieve trading signals.
"""

import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session

from src.db.session import get_db
from src.db.repositories import SignalRepository, SignalOutcomeRepository
from src.api.dependencies import get_signal_service, get_logging_service
from src.models.schemas import (
    SignalResponse,
    TradingSignal,
    OutcomeRecord,
)

router = APIRouter(prefix="/signals", tags=["signals"])


@router.post("/generate", response_model=SignalResponse)
def generate_signals(
    scan_type: str = Query("volume", enum=["volume", "rvol", "gainers", "finviz", "professional", "professional-discovery", "professional-all", "professional-penny", "htf-prefer-bullish", "htf-only-bullish", "htf-include-reversals"]),
    db: Session = Depends(get_db),
):
    """Run the full pipeline: scan → analyze → generate signals."""
    service = get_signal_service(db)
    return service.generate_signals(scan_type=scan_type)


@router.post("/generate/watchlist", response_model=SignalResponse)
def generate_watchlist_signals(
    tickers: list[str],
    db: Session = Depends(get_db),
):
    """Generate signals for a specific list of tickers."""
    service = get_signal_service(db)
    return service.generate_signals(watchlist=tickers)


@router.get("/analyze/{ticker}", response_model=TradingSignal)
def analyze_ticker(
    ticker: str,
    db: Session = Depends(get_db),
):
    """Analyze a single ticker through the full pipeline."""
    service = get_signal_service(db)
    signal = service.analyze_single(ticker.upper())
    if signal is None:
        raise HTTPException(status_code=404, detail=f"Could not analyze {ticker}")
    return signal


@router.get("/recent", response_model=list[TradingSignal])
def get_recent_signals(
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """Retrieve recently generated signals from the database."""
    repo = SignalRepository(db)
    db_signals = repo.get_recent(limit=limit)
    results = []
    for s in db_signals:
        results.append(
            TradingSignal(
                id=s.id,
                ticker=s.ticker,
                action=s.action,
                classification=s.classification,
                dip_probability=s.dip_probability,
                bounce_probability=s.bounce_probability,
                entry_price=s.entry_price,
                stop_price=s.stop_price,
                target_prices=s.target_prices,
                risk_score=s.risk_score,
                setup_grade=s.setup_grade,
                confidence=s.confidence,
                signal_expiry=s.signal_expiry,
                reason=s.features_snapshot.get("reason") if s.features_snapshot else None,
                created_at=s.created_at,
            )
        )
    return results


@router.get("/active", response_model=list[TradingSignal])
def get_active_signals(
    db: Session = Depends(get_db),
):
    """Retrieve signals that have not yet expired."""
    repo = SignalRepository(db)
    db_signals = repo.get_active()
    results = []
    for s in db_signals:
        results.append(
            TradingSignal(
                id=s.id,
                ticker=s.ticker,
                action=s.action,
                classification=s.classification,
                dip_probability=s.dip_probability,
                bounce_probability=s.bounce_probability,
                entry_price=s.entry_price,
                stop_price=s.stop_price,
                target_prices=s.target_prices,
                risk_score=s.risk_score,
                setup_grade=s.setup_grade,
                confidence=s.confidence,
                signal_expiry=s.signal_expiry,
                reason=s.features_snapshot.get("reason") if s.features_snapshot else None,
                created_at=s.created_at,
            )
        )
    return results


@router.post("/outcome")
def record_outcome(
    outcome: OutcomeRecord,
    db: Session = Depends(get_db),
):
    """Record price outcomes for a previously generated signal."""
    logging_svc = get_logging_service(db)
    saved = logging_svc.log_outcome(outcome)
    return {"status": "ok", "outcome_id": str(saved.id)}


@router.post("/simulate")
def run_simulation(
    db: Session = Depends(get_db),
):
    """Manually trigger the outcome simulator to check all open signals."""
    from src.core.outcome_simulator import OutcomeSimulator
    simulator = OutcomeSimulator(db)
    stats = simulator.run()
    return {"status": "ok", "stats": stats}
