"""
Pre-News Volume Anomaly Detector — API Routes

All endpoints under /agentic/pre-news.
Follows existing FastAPI style in the project.
"""

import logging
from pathlib import Path
from src.utils.data_paths import agentic_data_dir, agentic_path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from src.core.agentic.pre_news_detector import PreNewsDetector
from src.core.agentic.pre_news_evaluator import PreNewsEvaluator
from src.core.agentic.pre_news_learning import PreNewsLearningEngine
from src.core.agentic.pre_news_models import SuspicionLevel
from src.core.agentic.pre_news_validation import PreNewsValidationTracker

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/agentic/pre-news", tags=["Pre-News Volume Anomaly"])

# ── Singletons ────────────────────────────────────────────────────────────────

_detector: Optional[PreNewsDetector] = None
_evaluator: Optional[PreNewsEvaluator] = None
_learning: Optional[PreNewsLearningEngine] = None
_validation: Optional[PreNewsValidationTracker] = None


def _get_detector() -> PreNewsDetector:
    global _detector
    if _detector is None:
        _detector = PreNewsDetector()
    return _detector


def _get_evaluator() -> PreNewsEvaluator:
    global _evaluator
    if _evaluator is None:
        _evaluator = PreNewsEvaluator()
    return _evaluator


def _get_learning() -> PreNewsLearningEngine:
    global _learning
    if _learning is None:
        _learning = PreNewsLearningEngine()
    return _learning


def _get_validation() -> PreNewsValidationTracker:
    global _validation
    if _validation is None:
        _validation = PreNewsValidationTracker()
    return _validation


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.post("/scan")
async def scan_pre_news(min_rvol: float = Query(2.0, ge=1.0)):
    """Run a full pre-news volume anomaly scan across the universe."""
    detector = _get_detector()
    anomalies = await detector.scan(min_rvol=min_rvol)
    # Also refresh news status for persisted anomalies that may have dropped
    # out of the current universe but still have NO_NEWS_FOUND.
    try:
        await detector.update_news_status()
    except Exception as exc:
        logger.warning("update_news_status failed during /scan: %s", exc)
    # Refresh high-price buckets for all active anomalies (covers tickers
    # that have dropped out of the current Finviz universe).
    try:
        detector.refresh_tracked_prices()
    except Exception as exc:
        logger.warning("refresh_tracked_prices failed during /scan: %s", exc)
    return {
        "anomalies": [a.to_summary() for a in anomalies],
        "total": len(anomalies),
        "high_plus": sum(
            1 for a in anomalies
            if a.classification in (SuspicionLevel.HIGH, SuspicionLevel.EXTREME)
        ),
    }


@router.get("/anomalies")
async def get_anomalies(
    min_score: float = Query(0, ge=0),
    active_only: bool = Query(True),
):
    """Get all tracked pre-news anomalies."""
    detector = _get_detector()
    anomalies = list(detector.anomalies.values())

    if active_only:
        from src.core.agentic.pre_news_models import PreNewsState
        anomalies = [a for a in anomalies if a.state == PreNewsState.PRE_NEWS_WATCH]

    if min_score > 0:
        anomalies = [a for a in anomalies if a.pre_news_suspicion_score >= min_score]

    anomalies.sort(key=lambda a: a.pre_news_suspicion_score, reverse=True)
    return {
        "anomalies": [a.to_summary() for a in anomalies],
        "total": len(anomalies),
    }


@router.get("/learning")
async def get_learning_stats():
    """Get learning statistics and recommendations."""
    learning = _get_learning()
    stats = learning.get_stats()
    recommendations = learning.get_recommendations()
    return {
        "stats": stats,
        "recommendations": recommendations,
    }


@router.post("/evaluation/export/{date}")
async def export_evaluation(date: str):
    """Export daily evaluation JSON + CSV for the given session date (YYYY-MM-DD)."""
    try:
        evaluator = _get_evaluator()
        paths = evaluator.export_daily_report(session_date=date)
        return {
            "date": date,
            "json_path": str(paths["json"]),
            "csv_path": str(paths["csv"]),
            "total_snapshots": len(evaluator.get_filtered_snapshots(date_from=date, date_to=date)),
        }
    except Exception as exc:
        logger.error("Export evaluation failed for %s: %s", date, exc)
        raise HTTPException(status_code=500, detail=f"Export failed: {exc}")


@router.get("/evaluation/exports")
async def list_evaluation_exports():
    """List all available daily evaluation export dates."""
    evaluator = _get_evaluator()
    dates = evaluator.list_available_report_dates()
    return {
        "dates": dates,
        "total": len(dates),
    }


@router.get("/evaluation")
async def get_evaluation(
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    ticker: Optional[str] = Query(None),
    anomaly_type: Optional[str] = Query(None),
    alert_quality: Optional[str] = Query(None),
    min_score: Optional[float] = Query(None),
    outcome_label: Optional[str] = Query(None),
    include_unresolved: bool = Query(True),
):
    """Get V3 evaluation summary with optional filtering."""
    ev = _get_evaluator()
    summary = ev.get_summary()
    snapshots = ev.get_filtered_snapshots(
        date_from=date_from,
        date_to=date_to,
        ticker=ticker,
        anomaly_type=anomaly_type,
        alert_quality=alert_quality,
        min_score=min_score,
        outcome_label=outcome_label,
        include_unresolved=include_unresolved,
    )
    summary["filtered_snapshots"] = [s.model_dump(mode="json") for s in snapshots]
    summary["filtered_count"] = len(snapshots)
    return summary


@router.post("/missed-review")
async def missed_review():
    """Run end-of-day missed opportunity review."""
    detector = _get_detector()
    learning = _get_learning()
    reviews = learning.review_missed(detector.anomalies)
    return {
        "reviews": [r.model_dump(mode="json") for r in reviews],
        "total": len(reviews),
        "caught_early": sum(1 for r in reviews if r.classification.value == "caught_early"),
        "missed": sum(1 for r in reviews if r.classification.value.startswith("missed")),
    }


@router.get("/{ticker}")
async def get_anomaly_detail(ticker: str):
    """Get detailed anomaly data for a specific ticker."""
    detector = _get_detector()
    anomaly = detector.anomalies.get(ticker.upper())
    if not anomaly:
        raise HTTPException(status_code=404, detail=f"No anomaly found for {ticker}")
    return anomaly.model_dump(mode="json")


# ── Validation Endpoints ───────────────────────────────────────────────────────


@router.get("/validation/records")
async def get_validation_records(
    ticker: Optional[str] = Query(None),
    outcome: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
):
    """Get observational validation records for PRE_NEWS_V2 handoffs."""
    tracker = _get_validation()
    records = tracker._records
    if ticker:
        records = [r for r in records if r.ticker.upper() == ticker.upper()]
    if outcome:
        records = [r for r in records if r.outcome_label == outcome]
    records = sorted(records, key=lambda r: r.handoff_at, reverse=True)[:limit]
    return {
        "records": [r.model_dump(mode="json") for r in records],
        "total": len(records),
    }


@router.get("/validation/reports")
async def get_validation_reports():
    """Get all generated weekly validation reports."""
    tracker = _get_validation()
    reports = tracker.get_all_reports()
    return {
        "reports": [r.model_dump(mode="json") for r in reports],
        "total": len(reports),
    }


@router.get("/validation/reports/{week_key}")
async def get_validation_report(week_key: str):
    """Get a specific weekly validation report."""
    tracker = _get_validation()
    reports = tracker.get_all_reports()
    for report in reports:
        if report.week_key == week_key:
            return report.model_dump(mode="json")
    raise HTTPException(status_code=404, detail=f"No report found for {week_key}")


@router.post("/validation/generate-report")
async def generate_validation_report(week_key: Optional[str] = None):
    """On-demand weekly report generation."""
    tracker = _get_validation()
    report = tracker.generate_weekly_report(week_key=week_key)
    return report.model_dump(mode="json")


# ── Success-Rate Analysis Endpoints ───────────────────────────────────────────


@router.post("/evaluation/analyze")
async def trigger_success_rate_analysis():
    """Trigger the full success-rate analysis and regenerate all report files."""
    try:
        from scripts.pre_news_success_rate_analysis import run_analysis
        report = run_analysis(write_outputs=True)
        if "error" in report:
            raise HTTPException(status_code=400, detail=report["error"])
        return {
            "status": "completed",
            "generated_at": report.get("generated_at"),
            "total_detections": report["data_quality"]["total_detections"],
            "usable_detections": report["data_quality"]["usable_for_success_rate"],
            "clean_success_rate": report["overall_metrics"].get("clean_success_rate"),
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Success-rate analysis failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"Analysis failed: {exc}")


@router.get("/evaluation/report")
async def get_success_rate_report():
    """Return the latest success-rate report JSON."""
    report_path = agentic_path("evaluation_reports", "pre_news_success_rate_report.json")
    if not report_path.exists():
        raise HTTPException(status_code=404, detail="No success-rate report found. Run /evaluation/analyze first.")
    try:
        with open(report_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data
    except (json.JSONDecodeError, OSError) as exc:
        # Treat malformed / unreadable report as "not available" rather than 500
        logger.warning("Pre-news success-rate report unreadable: %s", exc)
        raise HTTPException(status_code=404, detail=f"Report exists but is unreadable: {exc}")


@router.get("/evaluation/report/markdown")
async def get_success_rate_report_md():
    """Return the latest success-rate report as Markdown text."""
    report_path = agentic_path("evaluation_reports", "pre_news_success_rate_report.md")
    if not report_path.exists():
        raise HTTPException(status_code=404, detail="No success-rate report found. Run /evaluation/analyze first.")
    try:
        with open(report_path, "r", encoding="utf-8") as f:
            text = f.read()
        return {"markdown": text}
    except OSError as exc:
        logger.warning("Pre-news report markdown unreadable: %s", exc)
        raise HTTPException(status_code=404, detail=f"Report exists but is unreadable: {exc}")


# ── Baseline Endpoints ────────────────────────────────────────────────────────


@router.get("/baselines")
async def get_baselines(
    baseline_type: Optional[str] = Query(None),
    ticker: Optional[str] = Query(None),
    session_date: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
):
    """List baseline snapshots with optional filtering."""
    try:
        from src.core.agentic.pre_news_baseline import PreNewsBaselineTracker
        tracker = PreNewsBaselineTracker()
        items = tracker.get_all()
        if baseline_type:
            items = [b for b in items if b.baseline_type == baseline_type]
        if ticker:
            items = [b for b in items if b.ticker.upper() == ticker.upper()]
        if session_date:
            items = [b for b in items if b.session_date == session_date]
        items = sorted(items, key=lambda x: x.scan_time, reverse=True)[:limit]
        return {"baselines": [b.model_dump() for b in items], "total": len(items)}
    except Exception as exc:
        logger.error("Baseline list failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"Baseline list failed: {exc}")


@router.get("/baselines/summary")
async def get_baselines_summary():
    """Get baseline summary statistics."""
    try:
        from src.core.agentic.pre_news_baseline import PreNewsBaselineTracker
        tracker = PreNewsBaselineTracker()
        return tracker.get_summary()
    except Exception as exc:
        logger.error("Baseline summary failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"Baseline summary failed: {exc}")


@router.post("/baselines/export/{session_date}")
async def export_baselines(session_date: str):
    """Export baseline snapshots for a specific session date."""
    try:
        from src.core.agentic.pre_news_baseline import PreNewsBaselineTracker
        tracker = PreNewsBaselineTracker()
        result = tracker.export_daily_baselines(session_date=session_date)
        return result
    except Exception as exc:
        logger.error("Baseline export failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"Baseline export failed: {exc}")
