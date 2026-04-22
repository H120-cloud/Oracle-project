"""
Intelligence API routes — Market Intelligence Engine endpoints.

Endpoints:
- POST  /intelligence/analyze/{ticker}  — full intelligence analysis for a ticker
- POST  /intelligence/analyze-batch     — batch analysis for multiple tickers
- GET   /intelligence/market-context    — current market context (SPY/QQQ)
- GET   /intelligence/active-trades     — all active trade trackers
- POST  /intelligence/track             — start tracking a trade
- POST  /intelligence/track/{ticker}/update  — update tracked trade price
- POST  /intelligence/track/{ticker}/close   — close and grade a trade
- GET   /intelligence/learning/weights  — current adaptive weights
- POST  /intelligence/learning/adjust   — compute weight adjustments
"""

import logging
from typing import Optional, List

from fastapi import APIRouter, Query
from pydantic import BaseModel

from src.services.market_data import get_market_data_provider
from src.core.intelligence_engine import IntelligenceEngine

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/intelligence", tags=["intelligence"])

# Shared engine instance
_provider = get_market_data_provider()
_engine = IntelligenceEngine(provider=_provider)


class BatchRequest(BaseModel):
    tickers: List[str]


class TrackRequest(BaseModel):
    ticker: str
    entry_price: float
    target_1: float
    target_2: float
    stop_loss: float
    direction: str = "bullish"


class UpdateRequest(BaseModel):
    current_price: float


class CloseRequest(BaseModel):
    exit_price: float


# ── Single Ticker Analysis ────────────────────────────────────────────────────

@router.post("/analyze/{ticker}")
def analyze_ticker(ticker: str):
    """Full intelligence analysis for a single ticker."""
    intel = _engine.analyze_ticker(ticker.upper())
    return intel.to_dict()


# ── Batch Analysis ────────────────────────────────────────────────────────────

@router.post("/analyze-batch")
def analyze_batch(req: BatchRequest):
    """Batch intelligence analysis for multiple tickers."""
    results = _engine.analyze_batch([t.upper() for t in req.tickers])
    return {
        "results": {k: v.to_dict() for k, v in results.items()},
        "count": len(results),
    }


# ── Market Context ────────────────────────────────────────────────────────────

@router.get("/market-context")
def get_market_context(refresh: bool = Query(False)):
    """Get current market context (SPY/QQQ tracking)."""
    ctx = _engine.get_market_context(force_refresh=refresh)
    return ctx.to_dict() if ctx else {"error": "No market context available"}


# ── Trade Tracking (Part 9) ──────────────────────────────────────────────────

@router.post("/track")
def start_tracking(req: TrackRequest):
    """Start tracking a trade for real-time adaptation."""
    tracker = _engine.adaptation.start_tracking(
        ticker=req.ticker.upper(),
        entry_price=req.entry_price,
        target_1=req.target_1,
        target_2=req.target_2,
        stop_loss=req.stop_loss,
        direction=req.direction,
    )
    return tracker.to_dict()


@router.post("/track/{ticker}/update")
def update_tracked_trade(ticker: str, req: UpdateRequest):
    """Update a tracked trade with new price."""
    tracker = _engine.adaptation.update(ticker.upper(), req.current_price)
    if not tracker:
        return {"error": f"No active trade for {ticker}"}
    return tracker.to_dict()


@router.post("/track/{ticker}/close")
def close_tracked_trade(ticker: str, req: CloseRequest):
    """Close a tracked trade and get EOD grade."""
    result = _engine.adaptation.close_trade(ticker.upper(), req.exit_price)
    if not result:
        return {"error": f"No active trade for {ticker}"}
    return {
        "ticker": result.ticker,
        "outcome_grade": result.outcome_grade.value,
        "pnl_pct": result.pnl_pct,
        "mfe": result.mfe,
        "mae": result.mae,
        "t1_hit": result.t1_hit,
        "t2_hit": result.t2_hit,
        "prediction_error_pct": result.prediction_error_pct,
    }


@router.get("/active-trades")
def get_active_trades():
    """Get all active trade trackers."""
    return {
        "trades": _engine.adaptation.get_all_active(),
        "count": len(_engine.adaptation.active_trades),
    }


# ── Learning (Part 10) ───────────────────────────────────────────────────────

@router.get("/learning/weights")
def get_learning_weights():
    """Get current adaptive weights."""
    return {"weights": _engine.adaptation.get_weights()}


@router.post("/learning/adjust")
def compute_adjustments():
    """Compute weight adjustments from completed trades."""
    adjustments = _engine.adaptation.compute_learning_adjustments()
    return {
        "adjustments": [
            {"component": a.component, "old": a.old_weight, "new": a.new_weight, "reason": a.reason}
            for a in adjustments
        ],
        "count": len(adjustments),
        "current_weights": _engine.adaptation.get_weights(),
    }
