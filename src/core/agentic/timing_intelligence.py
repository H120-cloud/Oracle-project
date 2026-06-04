"""Observe-only timing intelligence for Oracle alerts and candidates."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy.orm import Session

from src.models.database import AlertTimingReview

LATE_CHASE_BEFORE_MOVE_PCT = 50.0
WIN_AFTER_MOVE_PCT = 10.0
STRONG_AFTER_MOVE_PCT = 30.0
TRAP_AFTER_MOVE_PCT = 2.0


def _utc_naive(dt: Any) -> Optional[datetime]:
    if not dt:
        return None
    if isinstance(dt, str):
        try:
            dt = datetime.fromisoformat(dt.replace("Z", "+00:00"))
        except ValueError:
            return None
    if not isinstance(dt, datetime):
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _value(obj: Any, default: Optional[str] = None) -> Optional[str]:
    if obj is None:
        return default
    value = getattr(obj, "value", obj)
    return str(value) if value is not None else default


def _num(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def classify_timing(
    *,
    move_before_pct: Optional[float],
    move_after_pct: Optional[float],
    alerted: bool,
    discovered: bool,
) -> str:
    """Classify whether Oracle was early, late, wrong, or blind."""
    before = _num(move_before_pct)
    after = _num(move_after_pct) or 0.0

    if not discovered:
        return "MISSED_DISCOVERY" if after >= STRONG_AFTER_MOVE_PCT else "NO_ACTION_NEEDED"
    if before is not None and before >= LATE_CHASE_BEFORE_MOVE_PCT:
        return "LATE_CHASE"
    if not alerted and after >= STRONG_AFTER_MOVE_PCT:
        return "MISSED_ALERT"
    if alerted and after >= STRONG_AFTER_MOVE_PCT:
        return "EARLY_WIN"
    if alerted and after >= WIN_AFTER_MOVE_PCT:
        return "ON_TIME_WIN"
    if alerted and after < TRAP_AFTER_MOVE_PCT:
        return "FALSE_POSITIVE"
    return "NEUTRAL"


def _review_key(review_date: str, ticker: str, source_system: str, event_type: str) -> tuple[str, str, str, str]:
    return (review_date, ticker.upper(), source_system, event_type)


class TimingReviewService:
    """Persists EOD timing reviews into the backend database."""

    def __init__(self, db: Session):
        self.db = db

    def upsert_candidate_review(
        self,
        *,
        review_date: str,
        candidate: Any,
        mover: Any,
        event_type: str,
        source_system: str = "news_momentum",
    ) -> AlertTimingReview:
        ticker = str(getattr(candidate, "ticker", "") or getattr(mover, "ticker", "")).upper()
        source = _value(getattr(candidate, "source", None))
        move_before = _num(getattr(candidate, "move_pct", None))
        move_after = _num(getattr(mover, "change_percent", None))
        alerted = bool(getattr(candidate, "telegram_sent", False) or event_type == "alerted")
        discovered = event_type != "missed_discovery"
        label = classify_timing(
            move_before_pct=move_before,
            move_after_pct=move_after,
            alerted=alerted,
            discovered=discovered,
        )
        primary_issue = str(getattr(candidate, "_block_reason", "") or "") or None
        if event_type == "missed_discovery":
            primary_issue = "no_news_event_registered"

        existing = (
            self.db.query(AlertTimingReview)
            .filter(
                AlertTimingReview.review_date == review_date,
                AlertTimingReview.ticker == ticker,
                AlertTimingReview.source_system == source_system,
                AlertTimingReview.event_type == event_type,
            )
            .one_or_none()
        )
        row = existing or AlertTimingReview(
            review_date=review_date,
            ticker=ticker,
            source_system=source_system,
            event_type=event_type,
        )
        row.timing_label = label
        row.headline = getattr(candidate, "headline", None)
        row.source = source
        row.catalyst_category = _value(getattr(candidate, "catalyst_category", None))
        row.catalyst_sub_type = _value(getattr(candidate, "catalyst_sub_type", None))
        row.primary_issue = primary_issue
        row.published_at = _utc_naive(getattr(candidate, "published_at", None))
        row.detected_at = _utc_naive(getattr(candidate, "detected_at", None))
        row.alerted_at = _utc_naive(getattr(candidate, "alert_sent_at", None))
        row.reviewed_at = datetime.utcnow()
        row.price_at_detection = _num(getattr(candidate, "prior_price", None))
        row.price_at_alert = _num(getattr(candidate, "current_price", None))
        row.price_before_alert = _num(getattr(candidate, "prior_price", None))
        row.price_eod = _num(getattr(mover, "price", None))
        row.move_before_alert_pct = move_before
        row.move_after_alert_pct = move_after
        row.max_after_alert_pct = move_after
        row.volume = _num(getattr(mover, "volume", None))
        row.news_impact_score = _num(getattr(candidate, "news_impact_score", None))
        row.expected_return_score = _num(getattr(candidate, "expected_return_score", None))
        row.continuation_probability = _num(getattr(candidate, "continuation_probability", None))
        row.feature_snapshot = {
            "telegram_alert_id": getattr(candidate, "telegram_alert_id", None),
            "block_reason": primary_issue,
            "mover_change_percent": move_after,
            "mover_price": _num(getattr(mover, "price", None)),
        }
        if existing is None:
            self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def upsert_missed_discovery(
        self,
        *,
        review_date: str,
        mover: Any,
        source_system: str = "news_momentum",
    ) -> AlertTimingReview:
        candidate = type(
            "MissedDiscoveryCandidate",
            (),
            {
                "ticker": getattr(mover, "ticker", ""),
                "headline": None,
                "source": None,
                "published_at": None,
                "detected_at": None,
                "telegram_sent": False,
                "move_pct": None,
                "current_price": None,
                "prior_price": None,
                "news_impact_score": None,
                "expected_return_score": None,
                "continuation_probability": None,
                "catalyst_category": None,
                "catalyst_sub_type": None,
            },
        )()
        return self.upsert_candidate_review(
            review_date=review_date,
            candidate=candidate,
            mover=mover,
            event_type="missed_discovery",
            source_system=source_system,
        )

    def record_eod_reviews(
        self,
        *,
        review_date: str,
        items: list[dict[str, Any]],
        source_system: str = "news_momentum",
    ) -> list[AlertTimingReview]:
        rows: list[AlertTimingReview] = []
        for item in items:
            event_type = str(item.get("event_type") or "")
            mover = item.get("mover")
            if event_type == "missed_discovery":
                rows.append(
                    self.upsert_missed_discovery(
                        review_date=review_date,
                        mover=mover,
                        source_system=source_system,
                    )
                )
                continue
            candidate = item.get("candidate")
            if candidate is None or mover is None:
                continue
            rows.append(
                self.upsert_candidate_review(
                    review_date=review_date,
                    candidate=candidate,
                    mover=mover,
                    event_type=event_type,
                    source_system=source_system,
                )
            )
        return rows
