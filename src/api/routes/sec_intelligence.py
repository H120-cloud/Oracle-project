"""
SEC Filing Intelligence API Routes (V23)

Endpoints (mounted under /api/v1/sec-intelligence):
- GET  /candidates                — list all analyzed tickers + summary scores
- GET  /candidates/{ticker}       — full SEC profile for one ticker
- GET  /filings                   — recent filings across all tracked tickers
- GET  /filings/{ticker}          — filings for one ticker
- GET  /dilution-risk             — tickers ranked by dilution probability
- GET  /structural-traps          — tickers flagged AVOID_CHASE / STRUCTURAL_TRAP
- GET  /clean-watchlist           — clean balance-sheet tickers
- GET  /serial-diluters           — historical serial diluters
- GET  /history/{ticker}          — share-count + dilution history summary
- POST /scan-now                  — trigger an ad-hoc scan for one or more tickers
- GET  /stats                     — learning/shadow-mode stats
"""

from __future__ import annotations

import logging
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from src.core.agentic.sec_filing_models import (
    DilutionBehavior,
    OracleStructuralAction,
    SECIntelligenceCandidate,
)
from src.core.agentic.sec_intelligence_orchestrator import (
    SECIntelligenceOrchestrator,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sec-intelligence", tags=["sec-intelligence"])


# Global singleton — initialized lazily so tests can patch it
_orchestrator: Optional[SECIntelligenceOrchestrator] = None


def get_orchestrator() -> SECIntelligenceOrchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = SECIntelligenceOrchestrator()
    return _orchestrator


def set_orchestrator(orch: SECIntelligenceOrchestrator) -> None:
    """Allow main.py / tests to inject a shared orchestrator instance."""
    global _orchestrator
    _orchestrator = orch


# ── Request/Response models ─────────────────────────────────────────────────


class ScanRequest(BaseModel):
    tickers: List[str] = Field(default_factory=list, description="Tickers to scan")
    concurrency: int = 4


class CandidateSummary(BaseModel):
    ticker: str
    company_name: str = ""
    dilution_behavior: str
    oracle_action: str
    overall_filing_sentiment: str
    dilution_probability_score: float
    toxic_financing_score: float
    warrant_overhang_score: float
    cash_runway_score: float
    survival_risk_score: float
    balance_sheet_quality_score: float
    offering_risk_score: float
    reverse_split_risk_score: float
    structural_trap_risk_score: float
    historical_dilution_behavior_score: float
    atm_active: bool
    going_concern_active: bool
    offerings_last_12mo: int
    reverse_splits_last_36mo: int
    share_growth_pct_12mo: float
    sec_summary: str
    why_it_matters: str
    last_updated: str


def _summarize(c: SECIntelligenceCandidate) -> CandidateSummary:
    return CandidateSummary(
        ticker=c.ticker,
        company_name=c.company_name or "",
        dilution_behavior=c.dilution_behavior.value if c.dilution_behavior else None,
        oracle_action=c.oracle_action.value if c.oracle_action else None,
        overall_filing_sentiment=c.overall_filing_sentiment.value if c.overall_filing_sentiment else None,
        dilution_probability_score=c.scores.dilution_probability_score,
        toxic_financing_score=c.scores.toxic_financing_score,
        warrant_overhang_score=c.scores.warrant_overhang_score,
        cash_runway_score=c.scores.cash_runway_score,
        survival_risk_score=c.scores.survival_risk_score,
        balance_sheet_quality_score=c.scores.balance_sheet_quality_score,
        offering_risk_score=c.scores.offering_risk_score,
        reverse_split_risk_score=c.scores.reverse_split_risk_score,
        structural_trap_risk_score=c.scores.structural_trap_risk_score,
        historical_dilution_behavior_score=c.scores.historical_dilution_behavior_score,
        atm_active=c.atm_active,
        going_concern_active=c.going_concern_active,
        offerings_last_12mo=c.offerings_last_12mo,
        reverse_splits_last_36mo=c.reverse_splits_last_36mo,
        share_growth_pct_12mo=c.share_growth_pct_12mo,
        sec_summary=c.sec_summary,
        why_it_matters=c.why_it_matters,
        last_updated=c.last_updated.isoformat(),
    )


# ── Endpoints ───────────────────────────────────────────────────────────────


@router.get("/candidates", response_model=List[CandidateSummary])
async def list_candidates(
    behavior: Optional[str] = Query(None, description="Filter by DilutionBehavior"),
    action: Optional[str] = Query(None, description="Filter by Oracle action"),
    limit: int = Query(200, ge=1, le=1000),
):
    """Return all analyzed tickers with summary scores."""
    orch = get_orchestrator()
    candidates = orch.all_candidates()
    if behavior:
        candidates = [
            c for c in candidates
            if c.dilution_behavior and c.dilution_behavior.value == behavior
        ]
    if action:
        candidates = [
            c for c in candidates
            if c.oracle_action and c.oracle_action.value == action
        ]
    # Sort by structural_trap_risk desc so worst offenders surface first
    candidates.sort(key=lambda c: c.scores.structural_trap_risk_score, reverse=True)
    return [_summarize(c) for c in candidates[:limit]]


@router.get("/candidates/{ticker}")
async def get_candidate(ticker: str):
    orch = get_orchestrator()
    c = orch.get_candidate(ticker)
    if c is None:
        raise HTTPException(404, f"No SEC profile for {ticker.upper()}")
    return c.model_dump(mode="json")


@router.get("/filings")
async def list_filings(limit: int = Query(50, ge=1, le=500)):
    """Return the most recent filings across all tracked tickers."""
    orch = get_orchestrator()
    all_filings = []
    for c in orch.all_candidates():
        all_filings.extend(c.recent_filings)
    all_filings.sort(key=lambda f: f.filing_date, reverse=True)
    return [f.model_dump(mode="json") for f in all_filings[:limit]]


@router.get("/filings/{ticker}")
async def filings_for_ticker(ticker: str, limit: int = 25):
    orch = get_orchestrator()
    c = orch.get_candidate(ticker)
    if c is None:
        raise HTTPException(404, f"No SEC profile for {ticker.upper()}")
    return [f.model_dump(mode="json") for f in c.recent_filings[:limit]]


@router.get("/dilution-risk", response_model=List[CandidateSummary])
async def dilution_risk_ranking(limit: int = 50):
    """Tickers ranked by dilution probability (highest first)."""
    orch = get_orchestrator()
    cands = sorted(
        orch.all_candidates(),
        key=lambda c: c.scores.dilution_probability_score,
        reverse=True,
    )
    return [_summarize(c) for c in cands[:limit]]


@router.get("/structural-traps", response_model=List[CandidateSummary])
async def structural_traps(limit: int = 100):
    """Tickers flagged AVOID_CHASE or STRUCTURAL_TRAP."""
    orch = get_orchestrator()
    cands = orch.structural_traps()
    cands.sort(key=lambda c: c.scores.structural_trap_risk_score, reverse=True)
    return [_summarize(c) for c in cands[:limit]]


@router.get("/clean-watchlist", response_model=List[CandidateSummary])
async def clean_watchlist(limit: int = 100):
    """Tickers with clean balance sheets and high balance sheet quality."""
    orch = get_orchestrator()
    cands = orch.clean_watchlist()
    cands.sort(key=lambda c: c.scores.balance_sheet_quality_score, reverse=True)
    return [_summarize(c) for c in cands[:limit]]


@router.get("/serial-diluters", response_model=List[CandidateSummary])
async def serial_diluters(limit: int = 100):
    orch = get_orchestrator()
    cands = orch.serial_diluters()
    cands.sort(key=lambda c: c.scores.historical_dilution_behavior_score, reverse=True)
    return [_summarize(c) for c in cands[:limit]]


@router.get("/history/{ticker}")
async def history_for_ticker(ticker: str):
    orch = get_orchestrator()
    c = orch.get_candidate(ticker)
    if c is None:
        raise HTTPException(404, f"No SEC profile for {ticker.upper()}")
    return {
        "ticker": c.ticker,
        "share_history": c.share_history,
        "offerings_last_12mo": c.offerings_last_12mo,
        "reverse_splits_last_36mo": c.reverse_splits_last_36mo,
        "share_growth_pct_12mo": c.share_growth_pct_12mo,
        "dilution_behavior": c.dilution_behavior.value,
        "historical_dilution_behavior_score": c.scores.historical_dilution_behavior_score,
    }


@router.post("/scan-now")
async def scan_now(req: ScanRequest):
    """Trigger an ad-hoc SEC scan for one or more tickers."""
    orch = get_orchestrator()
    if not req.tickers:
        raise HTTPException(400, "tickers required")
    results = await orch.scan_tickers(req.tickers, concurrency=req.concurrency)
    return {
        "scanned": len(results),
        "candidates": [_summarize(c) for c in results],
    }


@router.get("/stats")
async def stats():
    orch = get_orchestrator()
    return orch.get_stats()
