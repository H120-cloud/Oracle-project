"""
News Momentum Intelligence API Routes (V22)

Endpoints:
  GET /api/v1/news-momentum/candidates
  GET /api/v1/news-momentum/top-ranked
  GET /api/v1/news-momentum/top-expected-return
  GET /api/v1/news-momentum/top-continuation
  GET /api/v1/news-momentum/top-multiday
  GET /api/v1/news-momentum/telegram-quality
  GET /api/v1/news-momentum/history
  GET /api/v1/news-momentum/config
  POST /api/v1/news-momentum/config
  POST /api/v1/news-momentum/scan-now
  GET /api/v1/news-momentum/stats
  GET /api/v1/news-momentum/catalyst-stats
  GET /api/v1/news-momentum/candidates/{ticker}
  POST /api/v1/news-momentum/candidates/{ticker}/deactivate
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, BackgroundTasks
from pydantic import BaseModel

from src.core.agentic.news_momentum_orchestrator import NewsMomentumOrchestrator
from src.core.agentic.news_momentum_catalyst_classifier import classify_headline
from src.core.agentic.news_momentum_models import NewsEvent, NewsSource, SessionType

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/news-momentum", tags=["news-momentum"])

# Global orchestrator instance (initialized in main.py)
_orchestrator: Optional[NewsMomentumOrchestrator] = None


def set_orchestrator(orch: NewsMomentumOrchestrator) -> None:
    global _orchestrator
    _orchestrator = orch


# ── Pydantic request/response models ─────────────────────────────────────────


class ConfigUpdate(BaseModel):
    enabled: Optional[bool] = None
    min_price: Optional[float] = None
    max_price: Optional[float] = None
    telegram_enabled: Optional[bool] = None
    telegram_min_score: Optional[float] = None
    scan_interval_seconds: Optional[int] = None
    under_1_only: Optional[bool] = None


class ScanNowResponse(BaseModel):
    scan_time: str
    candidates_found: int
    telegram_alerts_sent: int
    session: str


# ── Routes ───────────────────────────────────────────────────────────────────


@router.get("/candidates")
async def get_candidates(
    active_only: bool = Query(True),
    limit: int = Query(50, ge=1, le=200),
):
    if not _orchestrator:
        raise HTTPException(status_code=503, detail="News momentum system not initialized")
    if active_only:
        candidates = _orchestrator.get_active_candidates()
    else:
        candidates = _orchestrator._candidates
    candidates.sort(key=lambda c: c.expected_return_score, reverse=True)
    return [c.model_dump() for c in candidates[:limit]]


@router.get("/candidates/{ticker}")
async def get_candidate(ticker: str):
    if not _orchestrator:
        raise HTTPException(status_code=503, detail="News momentum system not initialized")
    c = _orchestrator.get_candidate(ticker)
    if not c:
        raise HTTPException(status_code=404, detail=f"Candidate {ticker} not found")
    return c.model_dump()


@router.post("/candidates/{ticker}/deactivate")
async def deactivate_candidate(ticker: str):
    if not _orchestrator:
        raise HTTPException(status_code=503, detail="News momentum system not initialized")
    ok = _orchestrator.deactivate_candidate(ticker)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Candidate {ticker} not found")
    return {"status": "deactivated", "ticker": ticker}


@router.get("/top-ranked")
async def get_top_ranked(limit: int = Query(20, ge=1, le=100)):
    if not _orchestrator:
        raise HTTPException(status_code=503, detail="News momentum system not initialized")
    return [c.model_dump() for c in _orchestrator.get_top_ranked(limit)]


@router.get("/top-expected-return")
async def get_top_expected_return(limit: int = Query(20, ge=1, le=100)):
    if not _orchestrator:
        raise HTTPException(status_code=503, detail="News momentum system not initialized")
    active = _orchestrator.get_active_candidates()
    active.sort(key=lambda c: c.expected_return_score, reverse=True)
    return [c.model_dump() for c in active[:limit]]


@router.get("/top-continuation")
async def get_top_continuation(limit: int = Query(20, ge=1, le=100)):
    if not _orchestrator:
        raise HTTPException(status_code=503, detail="News momentum system not initialized")
    active = _orchestrator.get_active_candidates()
    active.sort(key=lambda c: c.continuation_probability, reverse=True)
    return [c.model_dump() for c in active[:limit]]


@router.get("/top-multiday")
async def get_top_multiday(limit: int = Query(20, ge=1, le=100)):
    if not _orchestrator:
        raise HTTPException(status_code=503, detail="News momentum system not initialized")
    active = _orchestrator.get_active_candidates()
    active.sort(key=lambda c: c.multi_day_continuation_score, reverse=True)
    return [c.model_dump() for c in active[:limit]]


@router.get("/telegram-quality")
async def get_telegram_quality():
    if not _orchestrator:
        raise HTTPException(status_code=503, detail="News momentum system not initialized")
    return _orchestrator._telegram_learning.get_overall_quality().model_dump()


@router.get("/history")
async def get_history(limit: int = Query(100, ge=1, le=500)):
    if not _orchestrator:
        raise HTTPException(status_code=503, detail="News momentum system not initialized")
    all_c = _orchestrator._candidates
    all_c.sort(key=lambda c: c.detected_at, reverse=True)
    return [c.model_dump() for c in all_c[:limit]]


@router.get("/config")
async def get_config():
    if not _orchestrator:
        raise HTTPException(status_code=503, detail="News momentum system not initialized")
    return _orchestrator.config.model_dump()


@router.post("/config")
async def update_config(update: ConfigUpdate):
    if not _orchestrator:
        raise HTTPException(status_code=503, detail="News momentum system not initialized")
    changes = {k: v for k, v in update.model_dump().items() if v is not None}
    _orchestrator.update_config(**changes)
    return _orchestrator.config.model_dump()


@router.post("/scan-now", response_model=ScanNowResponse)
async def scan_now():
    if not _orchestrator:
        raise HTTPException(status_code=503, detail="News momentum system not initialized")

    # Run a manual scan with empty news events (will rely on existing candidates)
    # In a real scan, this would fetch fresh news
    result = await _orchestrator.scan([])

    return ScanNowResponse(
        scan_time=result.scan_time.isoformat(),
        candidates_found=len(result.candidates),
        telegram_alerts_sent=result.telegram_alerts_sent,
        session=result.session.value,
    )


@router.get("/stats")
async def get_stats():
    if not _orchestrator:
        raise HTTPException(status_code=503, detail="News momentum system not initialized")
    return _orchestrator.get_stats()


@router.get("/catalyst-stats")
async def get_catalyst_stats():
    if not _orchestrator:
        raise HTTPException(status_code=503, detail="News momentum system not initialized")
    return _orchestrator._catalyst_learning.get_all_stats()


@router.get("/classify-headline")
async def classify_headline_endpoint(headline: str):
    """Test endpoint to classify a headline."""
    from src.core.agentic.news_momentum_catalyst_classifier import classify_headline_with_confidence
    return classify_headline_with_confidence(headline)


@router.get("/missed-winners")
async def get_missed_winners(limit: int = Query(50, ge=1, le=200)):
    """Get missed positive catalyst winners."""
    if not _orchestrator:
        raise HTTPException(status_code=503, detail="News momentum system not initialized")
    records = _orchestrator._missed_learning.get_missed_winners(limit)
    return [r.model_dump(mode="json") for r in records]


@router.get("/missed-winners/report")
async def get_missed_winners_report():
    """Get missed winner learning report."""
    if not _orchestrator:
        raise HTTPException(status_code=503, detail="News momentum system not initialized")
    return _orchestrator._missed_learning.get_report().model_dump(mode="json")


@router.post("/missed-winners/{record_id}/status")
async def update_missed_winner_status(record_id: str, status: str):
    """Update status of a missed winner record (pending, approved, rejected, shadow_applied)."""
    if not _orchestrator:
        raise HTTPException(status_code=503, detail="News momentum system not initialized")
    success = _orchestrator._missed_learning.update_status(record_id, status)
    if not success:
        raise HTTPException(status_code=404, detail="Missed winner record not found")
    return {"status": "updated", "record_id": record_id, "new_status": status}


@router.post("/missed-winners/apply-shadow/{catalyst_type}")
async def apply_shadow_adjustment(catalyst_type: str):
    """Apply shadow adjustments for a specific catalyst type."""
    if not _orchestrator:
        raise HTTPException(status_code=503, detail="News momentum system not initialized")
    from src.core.agentic.news_momentum_models import CatalystSubType
    try:
        sub_type = CatalystSubType(catalyst_type)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid catalyst type: {catalyst_type}")
    applied = _orchestrator._missed_learning.apply_shadow_adjustment(sub_type)
    return {"applied": applied, "catalyst_type": catalyst_type}


# ── EOD Review ──────────────────────────────────────────────────────────────


@router.post("/eod-review/run")
async def run_eod_review(force: bool = Query(False)):
    """Manually trigger the EOD review (Finviz top gainers vs system records)."""
    if not _orchestrator:
        raise HTTPException(status_code=503, detail="News momentum system not initialized")
    reviewer = _orchestrator.get_eod_reviewer()
    result = await reviewer.run_review(force=force)
    return result


@router.get("/eod-review/latest")
async def get_eod_latest():
    """Get the latest EOD review report."""
    if not _orchestrator:
        raise HTTPException(status_code=503, detail="News momentum system not initialized")
    reviewer = _orchestrator.get_eod_reviewer()
    report = reviewer.get_latest_report()
    if not report:
        return {"status": "no_reports_yet"}
    return report


@router.get("/eod-review/history")
async def get_eod_history(limit: int = Query(30, ge=1, le=90)):
    """Get historical EOD reports."""
    if not _orchestrator:
        raise HTTPException(status_code=503, detail="News momentum system not initialized")
    reviewer = _orchestrator.get_eod_reviewer()
    return reviewer.get_all_reports(limit=limit)


# ── ML Engine ───────────────────────────────────────────────────────────────


@router.get("/ml/status")
async def get_ml_status():
    """Return self-training ML model status (version, AUC, top features)."""
    if not _orchestrator:
        raise HTTPException(status_code=503, detail="News momentum system not initialized")
    return _orchestrator.get_ml_engine().get_status()


@router.post("/ml/retrain")
async def trigger_ml_retrain():
    """Manually trigger an ML retrain on all resolved alert outcomes.

    Normally this runs automatically every Sunday at 02:00 UTC. Use this
    endpoint to force an immediate retrain after collecting new outcomes.
    """
    if not _orchestrator:
        raise HTTPException(status_code=503, detail="News momentum system not initialized")
    result = _orchestrator.retrain_ml()
    return {
        "success": result.success,
        "samples": result.samples,
        "auc": result.auc,
        "test_accuracy": result.test_accuracy,
        "train_accuracy": result.train_accuracy,
        "win_rate_baseline": result.win_rate_baseline,
        "promoted": result.promoted,
        "model_version": result.model_version,
        "reason": result.reason,
        "top_features": [
            {"feature": name, "importance": round(weight, 4)}
            for name, weight in result.feature_importance[:15]
        ],
    }


# ── Historical Backfill ─────────────────────────────────────────────────────

_backfill_tasks: dict = {}


class BackfillRequest(BaseModel):
    tickers: str
    start_date: str
    end_date: str
    news_limit: int = 100
    max_concurrent: int = 2
    force: bool = False


def _run_backfill_task(job_id: str, tickers: list, start_date: str, end_date: str, news_limit: int, max_concurrent: int, force: bool = False):
    """Background task for long-running backfill (runs in thread pool)."""
    import asyncio
    async def _async_work():
        from src.core.agentic.news_momentum_historical_backfill import HistoricalBackfillEngine
        engine = HistoricalBackfillEngine()
        _backfill_tasks[job_id] = {
            "status": "running",
            "tickers": tickers,
            "start_date": start_date,
            "end_date": end_date,
            "started_at": datetime.utcnow().isoformat(),
            "result": None,
            "error": None,
        }
        result = await engine.backfill_range(
            tickers=tickers,
            start_date=start_date,
            end_date=end_date,
            news_limit=news_limit,
            max_concurrent=max_concurrent,
            force=force,
        )
        _backfill_tasks[job_id].update({
            "status": "completed",
            "result": result,
            "completed_at": datetime.utcnow().isoformat(),
        })
    try:
        asyncio.run(_async_work())
    except Exception as exc:
        logger.error("Backfill task %s failed: %s", job_id, exc, exc_info=True)
        _backfill_tasks[job_id].update({
            "status": "failed",
            "error": str(exc),
            "completed_at": datetime.utcnow().isoformat(),
        })


@router.post("/backfill")
async def run_backfill(req: BackfillRequest, background_tasks: BackgroundTasks):
    """Start a background backfill job and return immediately.

    Poll /backfill/status to monitor progress. Polygon free tier = ~5 calls/min,
    so a month of data for 5 tickers can take 30+ minutes.
    """
    if not _orchestrator:
        raise HTTPException(status_code=503, detail="News momentum system not initialized")
    try:
        job_id = f"bf_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
        ticker_list = [t.strip().upper() for t in req.tickers.split(",") if t.strip()]
        background_tasks.add_task(
            _run_backfill_task,
            job_id,
            ticker_list,
            req.start_date,
            req.end_date,
            req.news_limit,
            req.max_concurrent,
            req.force,
        )
        return {
            "success": True,
            "job_id": job_id,
            "message": "Backfill started in background. Poll /backfill/status for progress.",
            "tickers": ticker_list,
            "start_date": req.start_date,
            "end_date": req.end_date,
        }
    except Exception as exc:
        logger.error("Backfill failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Backfill failed: {exc}")


class BackfillAndTrainRequest(BaseModel):
    tickers: str
    start_date: str
    end_date: str
    news_limit: int = 100
    max_concurrent: int = 2


@router.post("/backfill-and-train")
async def backfill_and_train(req: BackfillAndTrainRequest, background_tasks: BackgroundTasks):
    """Run backfill then immediately trigger ML retrain."""
    if not _orchestrator:
        raise HTTPException(status_code=503, detail="News momentum system not initialized")
    try:
        from src.core.agentic.news_momentum_historical_backfill import HistoricalBackfillEngine
        engine = HistoricalBackfillEngine()
        ticker_list = [t.strip().upper() for t in req.tickers.split(",") if t.strip()]
        backfill_result = await engine.backfill_range(
            tickers=ticker_list,
            start_date=req.start_date,
            end_date=req.end_date,
            news_limit=req.news_limit,
            max_concurrent=req.max_concurrent,
        )
        # Inject into orchestrator
        injected = engine.inject_into_orchestrator(_orchestrator)
        # Retrain
        train_result = _orchestrator.retrain_ml()
        return {
            "backfill": backfill_result,
            "injected_records": injected,
            "summary": engine.get_summary(),
            "training": {
                "success": train_result.success,
                "samples": train_result.samples,
                "auc": train_result.auc,
                "promoted": train_result.promoted,
                "reason": train_result.reason,
            },
        }
    except Exception as exc:
        logger.error("Backfill+train failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Backfill+train failed: {exc}")


@router.get("/backfill/status")
async def get_backfill_status():
    """Check backfill records and any active background jobs."""
    try:
        from src.core.agentic.news_momentum_historical_backfill import HistoricalBackfillEngine
        engine = HistoricalBackfillEngine()
        summary = engine.get_summary()
        active_jobs = {k: v for k, v in _backfill_tasks.items() if v.get("status") == "running"}
        recent_jobs = {k: v for k, v in _backfill_tasks.items()}
        return {
            "records": summary,
            "active_jobs": len(active_jobs),
            "recent_jobs": recent_jobs,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Status check failed: {exc}")


def _count_by_outcome(records: list) -> dict:
    counts = {}
    for r in records:
        key = r.outcome.value if r.outcome else "unresolved"
        counts[key] = counts.get(key, 0) + 1
    return counts


@router.post("/outcomes/resolve-now")
async def trigger_outcome_resolve():
    """Manually trigger the outcome resolver to fetch follow-up prices and
    label any unresolved alert outcomes. Runs automatically every 30 min."""
    if not _orchestrator:
        raise HTTPException(status_code=503, detail="News momentum system not initialized")
    resolver = _orchestrator.get_outcome_resolver()
    summary = await resolver.run_once()
    return summary


@router.get("/outcomes/unresolved")
async def list_unresolved_outcomes():
    """Return alerts whose outcome has not yet been resolved (still tracking)."""
    if not _orchestrator:
        raise HTTPException(status_code=503, detail="News momentum system not initialized")
    resolver = _orchestrator.get_outcome_resolver()
    pending = resolver.get_unresolved()
    return [
        {
            "alert_id": p.alert_id,
            "ticker": p.ticker,
            "sent_at": p.sent_at.isoformat(),
            "catalyst": p.catalyst_type.value if p.catalyst_type else None,
            "price_at_alert": p.price_at_alert,
            "has_partial_data": any(
                getattr(p, f, None) is not None for f in [
                    "price_15m_later", "price_1h_later", "price_4h_later",
                    "next_day_high", "two_day_high",
                ]
            ),
        }
        for p in pending
    ]
