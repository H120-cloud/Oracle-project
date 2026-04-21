"""
Watchlist API routes — professional watchlist management.

Endpoints:
- GET    /watchlist/              — list all active watchlist items
- POST   /watchlist/              — add ticker to watchlist
- GET    /watchlist/{ticker}      — get detail view (item + alerts + timeline)
- PUT    /watchlist/{ticker}      — update watchlist item
- DELETE /watchlist/{ticker}      — permanently remove
- POST   /watchlist/{ticker}/archive  — archive (soft delete)
- POST   /watchlist/{ticker}/restore  — restore from archive
- GET    /watchlist/alerts/all    — get all unread alerts
- POST   /watchlist/alerts/{id}/read — mark alert as read
- GET    /watchlist/{ticker}/alerts   — get alerts for a ticker
- GET    /watchlist/{ticker}/timeline — get timeline for a ticker
- POST   /watchlist/refresh       — refresh all watchlist metrics
- POST   /watchlist/{ticker}/refresh  — refresh single ticker metrics
"""

import logging
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from src.db.session import get_db
from src.db.repositories import WatchlistRepository
from src.services.watchlist_service import WatchlistService
from src.models.schemas import (
    WatchlistAddRequest, WatchlistUpdateRequest,
    WatchlistResponse, WatchlistItem, WatchlistDetailResponse,
    WatchlistAlertItem, WatchlistTimelineItem,
)

router = APIRouter(prefix="/watchlist", tags=["watchlist"])
logger = logging.getLogger(__name__)


def _to_item(w) -> WatchlistItem:
    """Convert DB Watchlist to schema WatchlistItem."""
    return WatchlistItem.model_validate(w)


# ── List ─────────────────────────────────────────────────────────────────────

@router.get("/", response_model=WatchlistResponse)
def get_watchlist(
    include_archived: bool = Query(False),
    db: Session = Depends(get_db),
):
    """Return all watchlist items (active by default, optionally include archived)."""
    repo = WatchlistRepository(db)
    if include_archived:
        items = repo.get_all(include_archived=True)
    else:
        items = repo.get_all_active()
    return WatchlistResponse(
        items=[_to_item(w) for w in items],
        count=len(items),
    )


# ── Add ──────────────────────────────────────────────────────────────────────

@router.post("/", response_model=WatchlistItem)
def add_to_watchlist(
    req: WatchlistAddRequest,
    db: Session = Depends(get_db),
):
    """Add a ticker to the watchlist with optional metadata."""
    repo = WatchlistRepository(db)

    # Check if already exists
    existing = repo.get_by_ticker(req.ticker)
    if existing:
        if existing.status == "archived":
            # Restore it
            repo.restore(req.ticker)
            return _to_item(repo.get_by_ticker(req.ticker))
        raise HTTPException(status_code=400, detail=f"{req.ticker} already on watchlist")

    try:
        # Fetch company name
        company_name = None
        try:
            import yfinance as yf
            tkr = yf.Ticker(req.ticker.upper())
            company_name = getattr(tkr.info, "shortName", None) or getattr(tkr.info, "longName", None)
        except Exception:
            pass

        item = repo.add(
            ticker=req.ticker,
            company_name=company_name,
            source=req.source,
            tags=req.tags,
            notes=req.notes,
            watch_reason=req.watch_reason,
            priority=req.priority,
            support_level=req.support_level,
            resistance_level=req.resistance_level,
            invalidation_level=req.invalidation_level,
            analysis_snapshot=req.analysis_snapshot,
        )

        # Immediately fetch initial metrics
        try:
            svc = WatchlistService(db)
            svc.refresh_one(req.ticker)
        except Exception:
            pass

        return _to_item(repo.get_by_ticker(req.ticker))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Could not add {req.ticker}: {exc}")


# ── Detail ───────────────────────────────────────────────────────────────────

@router.get("/alerts/all")
def get_all_alerts(db: Session = Depends(get_db)):
    """Get all unread alerts across all watchlist items."""
    repo = WatchlistRepository(db)
    alerts = repo.get_all_unread_alerts()
    return {
        "alerts": [WatchlistAlertItem.model_validate(a) for a in alerts],
        "count": len(alerts),
    }


@router.get("/{ticker}", response_model=WatchlistDetailResponse)
def get_watchlist_detail(
    ticker: str,
    db: Session = Depends(get_db),
):
    """Get full detail for a watchlist item including alerts and timeline."""
    repo = WatchlistRepository(db)
    item = repo.get_by_ticker(ticker)
    if not item:
        raise HTTPException(status_code=404, detail=f"{ticker} not on watchlist")

    alerts = repo.get_alerts(item.id, limit=20)
    timeline = repo.get_timeline(item.id, limit=50)

    return WatchlistDetailResponse(
        item=_to_item(item),
        alerts=[WatchlistAlertItem.model_validate(a) for a in alerts],
        timeline=[WatchlistTimelineItem.model_validate(t) for t in timeline],
    )


# ── Update ───────────────────────────────────────────────────────────────────

@router.put("/{ticker}", response_model=WatchlistItem)
def update_watchlist_item(
    ticker: str,
    req: WatchlistUpdateRequest,
    db: Session = Depends(get_db),
):
    """Update watchlist item metadata (tags, notes, priority, levels)."""
    repo = WatchlistRepository(db)
    update_data = req.model_dump(exclude_none=True)
    if not update_data:
        raise HTTPException(status_code=400, detail="No fields to update")

    item = repo.update(ticker, **update_data)
    if not item:
        raise HTTPException(status_code=404, detail=f"{ticker} not on watchlist")
    return _to_item(item)


# ── Delete ───────────────────────────────────────────────────────────────────

@router.delete("/{ticker}")
def remove_from_watchlist(
    ticker: str,
    db: Session = Depends(get_db),
):
    """Permanently remove a ticker from the watchlist."""
    repo = WatchlistRepository(db)
    removed = repo.remove(ticker)
    if not removed:
        raise HTTPException(status_code=404, detail=f"{ticker} not found in watchlist")
    return {"status": "ok", "ticker": ticker.upper()}


# ── Archive / Restore ────────────────────────────────────────────────────────

@router.post("/{ticker}/archive")
def archive_watchlist_item(
    ticker: str,
    reason: str = Query("manual"),
    db: Session = Depends(get_db),
):
    """Archive a watchlist item (soft delete)."""
    repo = WatchlistRepository(db)
    item = repo.archive(ticker, reason=reason)
    if not item:
        raise HTTPException(status_code=404, detail=f"{ticker} not on watchlist")
    return {"status": "archived", "ticker": ticker.upper(), "reason": reason}


@router.post("/{ticker}/restore")
def restore_watchlist_item(
    ticker: str,
    db: Session = Depends(get_db),
):
    """Restore an archived watchlist item."""
    repo = WatchlistRepository(db)
    item = repo.restore(ticker)
    if not item:
        raise HTTPException(status_code=404, detail=f"{ticker} not on watchlist")
    return {"status": "restored", "ticker": ticker.upper()}


# ── Alerts ───────────────────────────────────────────────────────────────────

@router.get("/{ticker}/alerts")
def get_ticker_alerts(
    ticker: str,
    db: Session = Depends(get_db),
):
    """Get alerts for a specific watchlist item."""
    repo = WatchlistRepository(db)
    item = repo.get_by_ticker(ticker)
    if not item:
        raise HTTPException(status_code=404, detail=f"{ticker} not on watchlist")
    alerts = repo.get_alerts(item.id)
    return {
        "alerts": [WatchlistAlertItem.model_validate(a) for a in alerts],
        "count": len(alerts),
    }


@router.post("/alerts/{alert_id}/read")
def mark_alert_read(
    alert_id: str,
    db: Session = Depends(get_db),
):
    """Mark an alert as read."""
    repo = WatchlistRepository(db)
    ok = repo.mark_alert_read(alert_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Alert not found")
    return {"status": "ok"}


# ── Timeline ────────────────────────────────────────────────────────────────

@router.get("/{ticker}/timeline")
def get_ticker_timeline(
    ticker: str,
    db: Session = Depends(get_db),
):
    """Get timeline/history for a watchlist item."""
    repo = WatchlistRepository(db)
    item = repo.get_by_ticker(ticker)
    if not item:
        raise HTTPException(status_code=404, detail=f"{ticker} not on watchlist")
    entries = repo.get_timeline(item.id)
    return {
        "timeline": [WatchlistTimelineItem.model_validate(t) for t in entries],
        "count": len(entries),
    }


# ── Refresh ──────────────────────────────────────────────────────────────────

@router.post("/refresh")
def refresh_all_watchlist(db: Session = Depends(get_db)):
    """Refresh metrics and run event detection for all active watchlist items."""
    svc = WatchlistService(db)
    stats = svc.refresh_all()
    return stats


@router.post("/{ticker}/refresh")
def refresh_one_watchlist(
    ticker: str,
    db: Session = Depends(get_db),
):
    """Refresh metrics for a single watchlist item."""
    svc = WatchlistService(db)
    result = svc.refresh_one(ticker)
    if not result:
        raise HTTPException(status_code=404, detail=f"{ticker} not on watchlist or no data")
    return result


# ── Custom Price Alerts ──────────────────────────────────────────────────────

from src.db.repositories import CustomAlertRepository
from src.models.schemas import CustomAlertCreate, CustomAlertItem, CustomAlertListResponse


@router.post("/{ticker}/alerts/custom")
def create_custom_alert(
    ticker: str,
    req: CustomAlertCreate,
    db: Session = Depends(get_db),
):
    """Create a custom price alert for a ticker."""
    repo = CustomAlertRepository(db)

    # Calculate expiration date
    from datetime import timedelta
    expires_at = None
    if req.expires_days:
        expires_at = datetime.utcnow() + timedelta(days=req.expires_days)

    alert = repo.create(
        ticker=ticker,
        alert_type=req.alert_type,
        target_value=req.target_value,
        reference_price=req.reference_price,
        message=req.message,
        expires_at=expires_at,
    )
    return CustomAlertItem.model_validate(alert)


@router.get("/{ticker}/alerts/custom")
def get_custom_alerts_for_ticker(
    ticker: str,
    db: Session = Depends(get_db),
):
    """Get all custom alerts for a ticker."""
    repo = CustomAlertRepository(db)
    alerts = repo.get_by_ticker(ticker)
    return {
        "alerts": [CustomAlertItem.model_validate(a) for a in alerts],
        "active_count": sum(1 for a in alerts if a.is_active),
        "triggered_count": sum(1 for a in alerts if not a.is_active and a.triggered_at),
    }


@router.get("/alerts/custom/all")
def get_all_custom_alerts(
    db: Session = Depends(get_db),
):
    """Get all active custom alerts across all tickers."""
    repo = CustomAlertRepository(db)
    alerts = repo.get_all_active()
    return {
        "alerts": [CustomAlertItem.model_validate(a) for a in alerts],
        "count": len(alerts),
    }


@router.delete("/alerts/custom/{alert_id}")
def delete_custom_alert(
    alert_id: str,
    db: Session = Depends(get_db),
):
    """Delete a custom alert."""
    repo = CustomAlertRepository(db)
    success = repo.delete(alert_id)
    if not success:
        raise HTTPException(status_code=404, detail="Alert not found")
    return {"status": "deleted", "id": alert_id}


# ── Earnings Calendar ─────────────────────────────────────────────────────────

@router.post("/refresh-earnings")
def refresh_earnings_calendar(
    db: Session = Depends(get_db),
):
    """Fetch upcoming earnings dates for all watchlist items."""
    svc = WatchlistService(db)
    result = svc.refresh_earnings_dates()
    return result


@router.post("/check-earnings-warnings")
def check_earnings_warnings(
    db: Session = Depends(get_db),
):
    """Check for earnings warnings (within 2 days)."""
    svc = WatchlistService(db)
    warnings = svc.check_earnings_warnings()
    return {"warnings": warnings, "count": len(warnings)}


@router.get("/{ticker}/earnings")
def get_ticker_earnings(
    ticker: str,
    db: Session = Depends(get_db),
):
    """Get earnings date for a specific ticker."""
    repo = WatchlistRepository(db)
    item = repo.get_by_ticker(ticker)
    if not item:
        raise HTTPException(status_code=404, detail="Ticker not on watchlist")

    return {
        "ticker": ticker,
        "next_earnings_date": item.next_earnings_date.isoformat() if item.next_earnings_date else None,
        "days_until": (item.next_earnings_date - datetime.utcnow()).days if item.next_earnings_date else None,
        "warning_shown": item.earnings_warning_shown,
    }


# ── News Feed ─────────────────────────────────────────────────────────────────

from src.core.news_service import NewsService


@router.get("/{ticker}/news")
def get_ticker_news(
    ticker: str,
    limit: int = Query(10, ge=1, le=20),
):
    """Get recent news headlines for a ticker."""
    svc = NewsService()
    try:
        news = svc.get_ticker_news(ticker, max_items=limit)
        return {
            "ticker": ticker.upper(),
            "news": [
                {
                    "headline": n.headline,
                    "source": n.source,
                    "url": n.url,
                    "sentiment": n.sentiment,
                }
                for n in news
            ],
            "count": len(news),
        }
    finally:
        svc.close()


@router.post("/check-htf")
def check_htf_alerts(db: Session = Depends(get_db)):
    """Check all watchlist items for HTF context changes and generate alerts.
    
    V9: HTF Change Detection endpoint.
    Detects bias flips, alignment changes, strength threshold crossings,
    and stocks becoming HTF blocked or favorable.
    """
    svc = WatchlistService(db)
    try:
        result = svc.check_htf_changes()
        return {
            "success": True,
            "htf_alerts_generated": result["htf_alerts_generated"],
            "by_severity": result["by_severity"],
            "alerts": result["alerts"],
            "message": f"Checked watchlist - {result['htf_alerts_generated']} HTF alerts generated"
        }
    finally:
        svc.close()


@router.get("/htf-alerts/{ticker}")
def get_htf_alerts_for_ticker(ticker: str, db: Session = Depends(get_db)):
    """Check HTF changes for a specific ticker."""
    svc = WatchlistService(db)
    try:
        from src.services.htf_alert_service import HTFAlert
        alert = svc.check_htf_for_ticker(ticker)
        if alert:
            return {
                "success": True,
                "has_change": True,
                "alert": {
                    "ticker": alert.ticker,
                    "type": alert.alert_type.value,
                    "severity": alert.severity,
                    "explanation": alert.explanation,
                    "previous_bias": alert.previous_bias,
                    "new_bias": alert.new_bias,
                    "previous_strength": alert.previous_strength,
                    "new_strength": alert.new_strength,
                    "timestamp": alert.timestamp
                }
            }
        return {"success": True, "has_change": False}
    finally:
        svc.close()
