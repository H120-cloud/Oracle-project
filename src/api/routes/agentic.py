"""
Agentic Catalyst Momentum Mode — API Routes

All endpoints prefixed with /agentic in the router.
Completely separate from existing Oracle endpoints.
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from src.core.agentic.orchestrator import AgenticOrchestrator
from src.core.agentic.learning import LearningEngine
from src.core.agentic.missed_opportunities import MissedOpportunityEngine
from src.core.agentic.models import MomentumState, ConfidenceLevel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/agentic", tags=["Agentic Mode"])

# ── Singleton instances (shared across requests) ────────────────────────────

_orchestrator: Optional[AgenticOrchestrator] = None
_learning: Optional[LearningEngine] = None
_missed_engine: Optional[MissedOpportunityEngine] = None


def _get_orchestrator() -> AgenticOrchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = AgenticOrchestrator()
        _orchestrator.load_state()
    return _orchestrator


def _get_learning() -> LearningEngine:
    global _learning
    if _learning is None:
        _learning = LearningEngine()
    return _learning


def _get_missed() -> MissedOpportunityEngine:
    global _missed_engine
    if _missed_engine is None:
        _missed_engine = MissedOpportunityEngine()
    return _missed_engine


# ── Request / Response Models ────────────────────────────────────────────────


class ScanResponse(BaseModel):
    candidates: list[dict]
    alerts: list[dict]
    scanned_at: str
    count: int
    alertable_count: int


class CandidateDetailResponse(BaseModel):
    candidate: dict
    alerts: list[dict]


class AlertsResponse(BaseModel):
    alerts: list[dict]
    count: int


class LearningStatsResponse(BaseModel):
    stats: dict
    current_weights: dict
    suggested_weights: Optional[dict] = None
    insights: dict = {}


class MissedResponse(BaseModel):
    missed: list[dict]
    count: int
    date: str


class RecordOutcomeRequest(BaseModel):
    ticker: str
    peak_price: Optional[float] = None
    exit_price: Optional[float] = None


# ── Endpoints ────────────────────────────────────────────────────────────────


@router.post("/scan", response_model=ScanResponse)
async def run_scan():
    """
    Run full agentic catalyst scan.
    Discovers new candidates, runs all engines, generates alerts.
    """
    orch = _get_orchestrator()
    try:
        # Run synchronous scan in thread to avoid blocking event loop
        candidates = await asyncio.to_thread(orch.run_scan)
        alerts = await asyncio.to_thread(lambda: orch.alerts[-20:])
        return ScanResponse(
            candidates=[c.to_summary() for c in candidates],
            alerts=[a.model_dump(mode="json") for a in alerts],
            scanned_at=datetime.now(timezone.utc).isoformat(),
            count=len(candidates),
            alertable_count=sum(1 for c in candidates if c.alertable),
        )
    except Exception as e:
        logger.error("Agentic scan failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/refresh")
async def refresh_all():
    """Refresh all active candidates with latest data."""
    orch = _get_orchestrator()
    try:
        updated = orch.refresh_all()
        return {
            "candidates": [c.to_summary() for c in updated],
            "count": len(updated),
            "refreshed_at": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/candidates")
async def list_candidates(
    active_only: bool = Query(True, description="Only return active candidates"),
    min_probability: float = Query(0, description="Minimum probability filter"),
    state: Optional[str] = Query(None, description="Filter by momentum state"),
):
    """List all agentic candidates with optional filters."""
    orch = _get_orchestrator()
    candidates = list(orch.candidates.values())

    if active_only:
        candidates = [c for c in candidates if c.active]
    if min_probability > 0:
        candidates = [c for c in candidates if c.final_probability >= min_probability]
    if state:
        candidates = [c for c in candidates if c.momentum.state.value == state]

    candidates.sort(key=lambda c: c.final_probability, reverse=True)

    return {
        "candidates": [c.to_summary() for c in candidates],
        "count": len(candidates),
    }


@router.get("/candidates/{ticker}")
async def get_candidate_detail(ticker: str):
    """Get full detail for a specific candidate."""
    orch = _get_orchestrator()
    ticker = ticker.upper()
    cand = orch.candidates.get(ticker)
    if not cand:
        raise HTTPException(status_code=404, detail=f"Candidate {ticker} not found")

    # Get alerts for this ticker
    alerts = [a for a in orch.alerts if a.ticker == ticker]

    return CandidateDetailResponse(
        candidate=cand.model_dump(mode="json"),
        alerts=[a.model_dump(mode="json") for a in alerts[-10:]],
    )


@router.post("/candidates/{ticker}/refresh")
async def refresh_candidate(ticker: str):
    """Refresh a single candidate."""
    orch = _get_orchestrator()
    ticker = ticker.upper()
    cand = orch.refresh(ticker)
    if not cand:
        raise HTTPException(status_code=404, detail=f"Candidate {ticker} not found")
    return {"candidate": cand.to_summary()}


@router.post("/candidates/{ticker}/deactivate")
async def deactivate_candidate(ticker: str):
    """Mark candidate as inactive."""
    orch = _get_orchestrator()
    ticker = ticker.upper()
    success = orch.deactivate(ticker)
    if not success:
        raise HTTPException(status_code=404, detail=f"Candidate {ticker} not found")
    return {"status": "deactivated", "ticker": ticker}


@router.get("/alerts", response_model=AlertsResponse)
async def list_alerts(limit: int = Query(50, le=200)):
    """List recent agentic alerts."""
    orch = _get_orchestrator()
    alerts = orch.alerts[-limit:]
    return AlertsResponse(
        alerts=[a.model_dump(mode="json") for a in alerts],
        count=len(alerts),
    )


# ── Learning Endpoints ───────────────────────────────────────────────────────


@router.get("/learning/stats", response_model=LearningStatsResponse)
async def learning_stats():
    """Get learning engine performance stats, current weights, and insights."""
    engine = _get_learning()
    stats = engine.get_stats()
    suggested = engine.suggest_adjustments()
    insights = engine.generate_insights()
    return LearningStatsResponse(
        stats=stats,
        current_weights=engine.current_weights.model_dump(mode="json"),
        suggested_weights=suggested.model_dump(mode="json") if suggested else None,
        insights=insights,
    )


@router.post("/learning/record-outcome")
async def record_outcome(req: RecordOutcomeRequest):
    """Record outcome for a candidate (for learning)."""
    orch = _get_orchestrator()
    engine = _get_learning()
    ticker = req.ticker.upper()

    cand = orch.candidates.get(ticker)
    if not cand:
        raise HTTPException(status_code=404, detail=f"Candidate {ticker} not found")

    outcome = engine.record_from_candidate(cand, req.peak_price, req.exit_price)
    return {
        "outcome": outcome.model_dump(mode="json"),
        "stats": engine.get_stats(),
    }


@router.post("/learning/apply-suggested-weights", response_model=LearningStatsResponse)
async def apply_suggested_weights():
    """Apply the suggested weight adjustments (manual confirmation endpoint)."""
    engine = _get_learning()
    suggested = engine.suggest_adjustments()
    if not suggested:
        raise HTTPException(status_code=400, detail="Not enough samples or no adjustments suggested")
    engine.apply_weights(suggested)
    insights = engine.generate_insights()
    return LearningStatsResponse(
        stats=engine.get_stats(),
        current_weights=engine.current_weights.model_dump(mode="json"),
        suggested_weights=suggested.model_dump(mode="json") if suggested else None,
        insights=insights,
    )


@router.post("/learning/rollback-weights", response_model=LearningStatsResponse)
async def rollback_weights():
    """Rollback to previous weights."""
    engine = _get_learning()
    success = engine.rollback_weights()
    if not success:
        raise HTTPException(status_code=400, detail="No previous weights to rollback to")
    insights = engine.generate_insights()
    suggested = engine.suggest_adjustments()
    return LearningStatsResponse(
        stats=engine.get_stats(),
        current_weights=engine.current_weights.model_dump(mode="json"),
        suggested_weights=suggested.model_dump(mode="json") if suggested else None,
        insights=insights,
    )


# ── Missed Opportunities ─────────────────────────────────────────────────────


@router.post("/missed-opportunities", response_model=MissedResponse)
async def analyze_missed_opportunities():
    """Analyze today's big movers vs what the system discovered/alerted."""
    orch = _get_orchestrator()
    engine = _get_missed()

    missed = engine.analyze(orch.candidates)
    return MissedResponse(
        missed=[m.model_dump(mode="json") for m in missed],
        count=len(missed),
        date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    )


# ── Quality Separator ────────────────────────────────────────────────────────


@router.get("/quality-separator/status")
async def quality_separator_status():
    """Get quality separator engine status and profile readiness."""
    orch = _get_orchestrator()
    summary = orch.quality_engine.get_profiles_summary()
    return summary


@router.get("/quality-separator/profiles")
async def quality_separator_profiles():
    """Get winner/loser feature divergence profiles."""
    orch = _get_orchestrator()
    return orch.quality_engine.get_feature_report()


class EvaluateRequest(BaseModel):
    ticker: str


@router.post("/quality-separator/evaluate")
async def quality_separator_evaluate(req: EvaluateRequest):
    """Evaluate a candidate through the quality separator."""
    orch = _get_orchestrator()
    ticker = req.ticker.upper()
    cand = orch.candidates.get(ticker)
    if not cand:
        raise HTTPException(status_code=404, detail=f"Candidate {ticker} not found")
    result = orch.quality_engine.evaluate(cand, cand.final_probability)
    return result.__dict__ if hasattr(result, "__dict__") else dict(result)


@router.get("/quality-separator/report")
async def quality_separator_report():
    """Get comprehensive quality separator analysis report."""
    orch = _get_orchestrator()
    profiles = orch.quality_engine.get_profiles_summary()
    features = orch.quality_engine.get_feature_report()
    return {
        "profiles": profiles,
        "feature_divergence": features,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


# ── ML Advisory ──────────────────────────────────────────────────────────────


@router.post("/ml/train")
async def ml_train():
    """Trigger ML model training on recorded outcomes."""
    engine = _get_learning()
    result = engine.train_ml()
    if result is None:
        raise HTTPException(status_code=400, detail="Insufficient samples for ML training")
    return result


@router.get("/ml/status")
async def ml_status():
    """Get ML model status, versions, and approval state."""
    engine = _get_learning()
    return engine.get_ml_status()


class MLApproveRequest(BaseModel):
    version: str
    approved_by: str


@router.post("/ml/approve")
async def ml_approve(req: MLApproveRequest):
    """Manually approve an ML model version for live advisory use."""
    engine = _get_learning()
    success = engine.approve_ml_model(req.version, req.approved_by)
    if not success:
        raise HTTPException(status_code=404, detail=f"Model version {req.version} not found")
    return {"approved": True, "version": req.version, "approved_by": req.approved_by}


@router.get("/ml/drift")
async def ml_drift():
    """Check ML prediction drift against recent outcomes."""
    engine = _get_learning()
    return engine.check_ml_drift()


@router.get("/ml/predict/{ticker}")
async def ml_predict(ticker: str):
    """Get ML prediction for a specific candidate (advisory only)."""
    orch = _get_orchestrator()
    engine = _get_learning()
    ticker = ticker.upper()
    cand = orch.candidates.get(ticker)
    if not cand:
        raise HTTPException(status_code=404, detail=f"Candidate {ticker} not found")
    pred = engine.predict_ml(cand)
    return {
        "ticker": ticker,
        "continuation_prob": pred.continuation_prob,
        "false_alert_prob": pred.false_alert_prob,
        "expected_mfe": pred.expected_mfe,
        "expected_mae": pred.expected_mae,
        "confidence": pred.confidence,
        "top_shap": pred.top_shap_features,
        "model_version": pred.model_version,
        "is_live": pred.is_live,
        "fallback_reason": pred.fallback_reason,
        "predicted_at": pred.predicted_at,
    }


# ── V20 News Catalyst Impact Engine ─────────────────────────────────────────


class NewsImpactEvaluateRequest(BaseModel):
    ticker: str = ""
    headline: str
    source: str = ""
    market_cap: Optional[float] = None
    float_shares: Optional[float] = None
    rvol: float = 0.0
    current_price: Optional[float] = None
    pre_news_runup_pct: float = 0.0
    pre_news_suspicion_score: float = 0.0
    pre_news_has_anomaly: bool = False
    short_interest_pct: Optional[float] = None
    has_offering_filing: bool = False
    has_warrants: bool = False
    is_unconfirmed: bool = False


@router.post("/news-impact/evaluate")
async def news_impact_evaluate(req: NewsImpactEvaluateRequest):
    """One-shot evaluation of a headline through the V20 impact engine.

    Useful for the frontend "what would this news do?" tester. Does NOT
    persist or alert.
    """
    from src.core.agentic.news_impact_engine import NewsImpactEngine
    engine = NewsImpactEngine()
    result = engine.evaluate(
        ticker=req.ticker,
        headline=req.headline,
        source=req.source,
        market_cap=req.market_cap,
        float_shares=req.float_shares,
        rvol=req.rvol,
        current_price=req.current_price,
        pre_news_runup_pct=req.pre_news_runup_pct,
        pre_news_suspicion_score=req.pre_news_suspicion_score,
        pre_news_has_anomaly=req.pre_news_has_anomaly,
        short_interest_pct=req.short_interest_pct,
        has_offering_filing=req.has_offering_filing,
        has_warrants=req.has_warrants,
        is_unconfirmed=req.is_unconfirmed,
    )
    return result.to_dict()


@router.get("/news-impact/candidates")
async def news_impact_candidates(min_score: float = Query(0, description="Minimum impact score"),
                                  decision: Optional[str] = Query(None, description="Filter by news_decision")):
    """List active candidates with their V20 news impact evaluation.

    Sorted by news_impact_score desc, filtered by min_score and decision.
    """
    orch = _get_orchestrator()
    rows = []
    for cand in orch.candidates.values():
        if not cand.active:
            continue
        ni = cand.news_impact
        if not ni.has_evaluation:
            continue
        if ni.news_impact_score < min_score:
            continue
        if decision and ni.news_decision != decision:
            continue
        rows.append({
            "ticker": cand.ticker,
            "headline": cand.catalyst.headline,
            "source": cand.catalyst.source,
            "timestamp": cand.catalyst.discovered_at.isoformat() if cand.catalyst.discovered_at else None,
            "catalyst_type": ni.catalyst_type,
            "catalyst_tier": ni.catalyst_tier,
            "news_impact_score": round(ni.news_impact_score, 1),
            "news_decision": ni.news_decision,
            "oracle_action": ni.oracle_action,
            "estimated_move_range": {
                "conservative_move_pct": ni.estimated_move_range.conservative_move_pct,
                "bullish_move_pct": ni.estimated_move_range.bullish_move_pct,
                "extreme_squeeze_pct": ni.estimated_move_range.extreme_squeeze_pct,
                "bearish_move_pct": ni.estimated_move_range.bearish_move_pct,
                "rationale": ni.estimated_move_range.rationale,
            },
            "is_dilution": ni.is_dilution,
            "is_parabolic": ni.is_parabolic,
            "trap_warning": ni.trap_warning,
            "pre_news_accumulation_detected": ni.pre_news_accumulation_detected,
            "rvol_at_detection": ni.rvol_at_detection,
            "float_shares_at_detection": ni.float_shares_at_detection,
            "market_cap_at_detection": ni.market_cap_at_detection,
            "summary": ni.news_summary,
        })
    rows.sort(key=lambda r: r["news_impact_score"], reverse=True)
    return {"candidates": rows, "count": len(rows)}


@router.get("/news-impact/learning/summary")
async def news_impact_learning_summary_priority():
    """Aggregate learning-loop summary for V20 (placed above {ticker} for routing)."""
    orch = _get_orchestrator()
    if orch.news_impact_learning is None:
        return {"total_outcomes": 0, "ready_for_calibration": False, "stats_by_catalyst": {}}
    return orch.news_impact_learning.overall_summary()


@router.get("/news-impact/learning/recommendations")
async def news_impact_learning_recommendations_priority():
    """Calibration suggestions based on accumulated outcomes (above {ticker})."""
    orch = _get_orchestrator()
    if orch.news_impact_learning is None:
        return {"recommendations": [], "ready_for_calibration": False}
    recs = orch.news_impact_learning.calibration_recommendations()
    return {
        "recommendations": recs,
        "ready_for_calibration": len(recs) > 0,
    }


@router.get("/news-impact/{ticker}")
async def news_impact_detail(ticker: str):
    """Full V20 news impact detail view for a single ticker."""
    orch = _get_orchestrator()
    ticker = ticker.upper()
    cand = orch.candidates.get(ticker)
    if not cand:
        raise HTTPException(status_code=404, detail=f"Candidate {ticker} not found")
    ni = cand.news_impact
    if not ni.has_evaluation:
        raise HTTPException(status_code=404, detail=f"No news impact evaluation for {ticker}")

    # Look up related pre-news anomaly (best-effort, non-fatal)
    related_pre_news = None
    try:
        from src.core.agentic.pre_news_detector import PreNewsDetector
        det = PreNewsDetector()
        det.load_state()
        anomaly = det.anomalies.get(ticker)
        if anomaly is not None:
            related_pre_news = {
                "ticker": anomaly.ticker,
                "suspicion_score": anomaly.pre_news_suspicion_score,
                "anomaly_type": anomaly.anomaly_type.value if hasattr(anomaly.anomaly_type, "value") else str(anomaly.anomaly_type),
                "rvol": getattr(getattr(anomaly, "volume_metrics", None), "rvol_current", 0),
                "state": anomaly.state if isinstance(anomaly.state, str) else getattr(anomaly.state, "value", str(anomaly.state)),
            }
    except Exception:
        pass

    # Historical outcomes for this catalyst type
    historical = []
    try:
        if orch.news_impact_learning is not None:
            stats = orch.news_impact_learning.stats_by_catalyst()
            this_cat = stats.get(ni.catalyst_type)
            if this_cat is not None:
                historical = [{
                    "catalyst_type": this_cat.catalyst_type,
                    "sample_size": this_cat.sample_size,
                    "avg_move_pct": round(this_cat.avg_move_pct, 1),
                    "median_move_pct": round(this_cat.median_move_pct, 1),
                    "win_rate": round(this_cat.win_rate, 1),
                    "trap_rate": round(this_cat.trap_rate, 1),
                }]
    except Exception:
        pass

    return {
        "ticker": cand.ticker,
        "summary": ni.news_summary,
        "why_it_matters": ni.why_it_matters,
        "bull_case": ni.bull_case,
        "bear_case": ni.bear_case,
        "key_risks": list(ni.key_risks),
        "impact_reasons": list(ni.impact_reasons),
        "impact_warnings": list(ni.impact_warnings),
        "news_decision": ni.news_decision,
        "oracle_action": ni.oracle_action,
        "news_impact_score": round(ni.news_impact_score, 1),
        "catalyst_type": ni.catalyst_type,
        "catalyst_tier": ni.catalyst_tier,
        "component_scores": ni.component_scores,
        "estimated_move_range": ni.estimated_move_range.model_dump(),
        "is_dilution": ni.is_dilution,
        "is_parabolic": ni.is_parabolic,
        "trap_warning": ni.trap_warning,
        "trap_reasons": list(ni.trap_reasons),
        "pre_news_accumulation_detected": ni.pre_news_accumulation_detected,
        "related_pre_news": related_pre_news,
        "related_candidate": cand.to_summary(),
        "historical_outcomes": historical,
    }


# ── Status ───────────────────────────────────────────────────────────────────


@router.get("/status")
async def agentic_status():
    """Get overall status of the agentic system."""
    orch = _get_orchestrator()
    engine = _get_learning()

    active = [c for c in orch.candidates.values() if c.active]
    return {
        "mode": "agentic_catalyst_momentum",
        "active_candidates": len(active),
        "total_candidates": len(orch.candidates),
        "total_alerts": len(orch.alerts),
        "learning_stats": engine.get_stats(),
        "top_candidates": [
            c.to_summary() for c in sorted(active, key=lambda x: x.final_probability, reverse=True)[:5]
        ],
    }
