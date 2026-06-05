"""Admin Diagnostics — read-only observability endpoints.

GET-only views over the diagnostics JSONL artifacts (news latency, Rocket
shadow, Telegram outbox). These endpoints NEVER write, mutate, score, gate, or
influence production alert decisions. They exist purely to explain why alerts
were delayed, blocked, missed, retried, or ranked.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Query

from src.services import admin_diagnostics as ad

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["Admin Diagnostics"])

# Shared query params (documented once, reused across endpoints).
_Ticker = Query(None, description="Filter by ticker (case-insensitive contains)")
_Source = Query(None, description="Filter by source / pipeline")
_Status = Query(None, description="Filter by status")
_Start = Query(None, description="ISO8601 start of date range (inclusive)")
_End = Query(None, description="ISO8601 end of date range (inclusive)")
_Page = Query(1, ge=1, description="1-based page number")
_PageSize = Query(50, ge=1, le=1000, description="Page size")


@router.get("/news-latency", summary="News alert latency diagnostics")
def news_latency(
    ticker: Optional[str] = _Ticker,
    source: Optional[str] = _Source,
    status: Optional[str] = _Status,
    start: Optional[str] = _Start,
    end: Optional[str] = _End,
    page: int = _Page,
    page_size: int = _PageSize,
):
    return ad.read_news_latency(
        ticker=ticker, source=source, status=status, start=start, end=end,
        page=page, page_size=page_size,
    )


@router.get("/rocket-shadow", summary="Rocket CatBoost shadow prediction diagnostics")
def rocket_shadow(
    ticker: Optional[str] = _Ticker,
    source: Optional[str] = _Source,
    status: Optional[str] = Query(None, description="Filter by prediction_confidence (HIGH/MEDIUM/LOW)"),
    start: Optional[str] = _Start,
    end: Optional[str] = _End,
    page: int = _Page,
    page_size: int = _PageSize,
    view: Optional[str] = Query(None, description="top_rank|highest_monster|highest_major|highest_confidence"),
):
    return ad.read_rocket_shadow(
        ticker=ticker, source=source, status=status, start=start, end=end,
        page=page, page_size=page_size, view=view,
    )


@router.get("/telegram-outbox", summary="Telegram outbox delivery diagnostics")
def telegram_outbox(
    ticker: Optional[str] = _Ticker,
    status: Optional[str] = Query(None, description="pending|failed|sent|dead_letter"),
    source: Optional[str] = Query(None, description="Filter by alert_type"),
    start: Optional[str] = _Start,
    end: Optional[str] = _End,
    page: int = _Page,
    page_size: int = _PageSize,
):
    return ad.read_telegram_outbox(
        ticker=ticker, status=status, alert_type=source, start=start, end=end,
        page=page, page_size=page_size,
    )


# ── Optional endpoints ──────────────────────────────────────────────────────

@router.get("/source-health", summary="Per-source latency / block health")
def source_health(
    start: Optional[str] = _Start,
    end: Optional[str] = _End,
):
    return ad.read_source_health(start=start, end=end)


@router.get("/blocked-alerts", summary="Blocked alerts (latency trace, blocked only)")
def blocked_alerts(
    ticker: Optional[str] = _Ticker,
    source: Optional[str] = _Source,
    status: Optional[str] = Query(None, description="Blocked sub-category filter"),
    start: Optional[str] = _Start,
    end: Optional[str] = _End,
    page: int = _Page,
    page_size: int = _PageSize,
):
    return ad.read_blocked_alerts(
        ticker=ticker, source=source, status=status, start=start, end=end,
        page=page, page_size=page_size,
    )


@router.get("/fast-watch-alerts", summary="FAST WATCH alerts (latency trace, fast_path only)")
def fast_watch_alerts(
    ticker: Optional[str] = _Ticker,
    source: Optional[str] = _Source,
    start: Optional[str] = _Start,
    end: Optional[str] = _End,
    page: int = _Page,
    page_size: int = _PageSize,
):
    return ad.read_fast_watch_alerts(
        ticker=ticker, source=source, start=start, end=end,
        page=page, page_size=page_size,
    )
