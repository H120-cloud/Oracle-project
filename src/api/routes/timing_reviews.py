"""Timing Intelligence API routes."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from src.db.session import get_db
from src.models.database import AlertTimingReview

router = APIRouter(prefix="/news-momentum/timing-reviews", tags=["timing-reviews"])


def _parse_date(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)


def _row(row: AlertTimingReview) -> dict:
    return {
        "id": row.id,
        "review_date": row.review_date,
        "ticker": row.ticker,
        "source_system": row.source_system,
        "event_type": row.event_type,
        "timing_label": row.timing_label,
        "headline": row.headline,
        "source": row.source,
        "catalyst_category": row.catalyst_category,
        "catalyst_sub_type": row.catalyst_sub_type,
        "primary_issue": row.primary_issue,
        "published_at": row.published_at.isoformat() if row.published_at else None,
        "detected_at": row.detected_at.isoformat() if row.detected_at else None,
        "alerted_at": row.alerted_at.isoformat() if row.alerted_at else None,
        "reviewed_at": row.reviewed_at.isoformat() if row.reviewed_at else None,
        "price_at_alert": row.price_at_alert,
        "price_eod": row.price_eod,
        "move_before_alert_pct": row.move_before_alert_pct,
        "move_after_alert_pct": row.move_after_alert_pct,
        "max_after_alert_pct": row.max_after_alert_pct,
        "volume": row.volume,
        "news_impact_score": row.news_impact_score,
        "expected_return_score": row.expected_return_score,
        "continuation_probability": row.continuation_probability,
        "feature_snapshot": row.feature_snapshot,
        "notes": row.notes,
    }


def _query(
    db: Session,
    *,
    ticker: Optional[str] = None,
    label: Optional[str] = None,
    source_system: Optional[str] = None,
    event_type: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
):
    query = db.query(AlertTimingReview)
    if ticker:
        query = query.filter(AlertTimingReview.ticker == ticker.upper())
    if label:
        query = query.filter(AlertTimingReview.timing_label == label.upper())
    if source_system:
        query = query.filter(AlertTimingReview.source_system == source_system)
    if event_type:
        query = query.filter(AlertTimingReview.event_type == event_type)
    if date_from:
        query = query.filter(AlertTimingReview.review_date >= date_from)
    if date_to:
        query = query.filter(AlertTimingReview.review_date <= date_to)
    return query


@router.get("")
async def list_timing_reviews(
    ticker: Optional[str] = Query(None),
    label: Optional[str] = Query(None),
    source_system: Optional[str] = Query(None),
    event_type: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    query = _query(
        db,
        ticker=ticker,
        label=label,
        source_system=source_system,
        event_type=event_type,
        date_from=date_from,
        date_to=date_to,
    )
    total = query.count()
    rows = (
        query.order_by(AlertTimingReview.reviewed_at.desc(), AlertTimingReview.ticker.asc())
        .limit(limit)
        .all()
    )
    return {"total": total, "items": [_row(row) for row in rows]}


@router.get("/summary")
async def timing_reviews_summary(
    ticker: Optional[str] = Query(None),
    source_system: Optional[str] = Query(None),
    event_type: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    rows = _query(
        db,
        ticker=ticker,
        source_system=source_system,
        event_type=event_type,
        date_from=date_from,
        date_to=date_to,
    ).all()
    by_label: dict[str, int] = {}
    by_source: dict[str, int] = {}
    by_event_type: dict[str, int] = {}
    for row in rows:
        by_label[row.timing_label] = by_label.get(row.timing_label, 0) + 1
        by_source[row.source_system] = by_source.get(row.source_system, 0) + 1
        by_event_type[row.event_type] = by_event_type.get(row.event_type, 0) + 1
    return {
        "total": len(rows),
        "by_label": dict(sorted(by_label.items())),
        "by_source": dict(sorted(by_source.items())),
        "by_event_type": dict(sorted(by_event_type.items())),
    }
