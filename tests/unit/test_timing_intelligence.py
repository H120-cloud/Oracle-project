from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.models.database import Base


def test_timing_classifier_labels_core_outcomes():
    from src.core.agentic.timing_intelligence import classify_timing

    assert classify_timing(
        move_before_pct=3.0,
        move_after_pct=45.0,
        alerted=True,
        discovered=True,
    ) == "EARLY_WIN"
    assert classify_timing(
        move_before_pct=90.0,
        move_after_pct=4.0,
        alerted=True,
        discovered=True,
    ) == "LATE_CHASE"
    assert classify_timing(
        move_before_pct=2.0,
        move_after_pct=55.0,
        alerted=False,
        discovered=True,
    ) == "MISSED_ALERT"
    assert classify_timing(
        move_before_pct=None,
        move_after_pct=80.0,
        alerted=False,
        discovered=False,
    ) == "MISSED_DISCOVERY"
    assert classify_timing(
        move_before_pct=2.0,
        move_after_pct=1.0,
        alerted=True,
        discovered=True,
    ) == "FALSE_POSITIVE"


def test_timing_review_service_upserts_one_row_per_ticker_source_date():
    from src.core.agentic.timing_intelligence import TimingReviewService
    from src.models.database import AlertTimingReview

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        service = TimingReviewService(db)
        review_date = "2026-06-04"
        candidate = SimpleNamespace(
            ticker="VERU",
            headline="Veru secures Novo Nordisk Wegovy supply for Phase 2b trial",
            source=SimpleNamespace(value="stocktitan"),
            published_at=datetime(2026, 6, 4, 13, 0, tzinfo=timezone.utc),
            detected_at=datetime(2026, 6, 4, 13, 2, tzinfo=timezone.utc),
            telegram_sent=False,
            telegram_alert_id=None,
            current_price=5.0,
            prior_price=4.9,
            move_pct=2.0,
            news_impact_score=82.0,
            expected_return_score=74.0,
            continuation_probability=70.0,
            catalyst_category=SimpleNamespace(value="biotech"),
            catalyst_sub_type=SimpleNamespace(value="phase_2"),
            _block_reason="score_gate",
        )
        mover = SimpleNamespace(
            ticker="VERU",
            change_percent=400.0,
            price=25.0,
            volume=8_000_000,
        )

        first = service.upsert_candidate_review(
            review_date=review_date,
            candidate=candidate,
            mover=mover,
            event_type="blocked",
            source_system="news_momentum",
        )
        second = service.upsert_candidate_review(
            review_date=review_date,
            candidate=candidate,
            mover=mover,
            event_type="blocked",
            source_system="news_momentum",
        )

        rows = db.query(AlertTimingReview).all()
        assert len(rows) == 1
        assert first.id == second.id
        assert rows[0].ticker == "VERU"
        assert rows[0].timing_label == "MISSED_ALERT"
        assert rows[0].move_after_alert_pct == 400.0
        assert rows[0].primary_issue == "score_gate"
    finally:
        db.close()


def test_timing_review_service_records_eod_caught_blocked_and_missed_discovery():
    from src.core.agentic.timing_intelligence import TimingReviewService
    from src.models.database import AlertTimingReview

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        service = TimingReviewService(db)
        review_date = "2026-06-04"
        caught = SimpleNamespace(
            ticker="SPRC",
            headline="SciSparc receives approval",
            source=SimpleNamespace(value="finviz"),
            published_at=datetime(2026, 6, 4, 12, 0, tzinfo=timezone.utc),
            detected_at=datetime(2026, 6, 4, 12, 1, tzinfo=timezone.utc),
            telegram_sent=True,
            telegram_alert_id="alert_sprc",
            current_price=2.0,
            prior_price=1.95,
            move_pct=2.5,
            news_impact_score=80.0,
            expected_return_score=75.0,
            continuation_probability=70.0,
            catalyst_category=SimpleNamespace(value="biotech"),
            catalyst_sub_type=SimpleNamespace(value="fda_approval"),
        )
        blocked = SimpleNamespace(
            ticker="VERU",
            headline="Veru secures Novo Nordisk supply",
            source=SimpleNamespace(value="stocktitan"),
            published_at=datetime(2026, 6, 4, 13, 0, tzinfo=timezone.utc),
            detected_at=datetime(2026, 6, 4, 13, 2, tzinfo=timezone.utc),
            telegram_sent=False,
            telegram_alert_id=None,
            current_price=5.0,
            prior_price=4.9,
            move_pct=2.0,
            news_impact_score=82.0,
            expected_return_score=44.0,
            continuation_probability=40.0,
            catalyst_category=SimpleNamespace(value="biotech"),
            catalyst_sub_type=SimpleNamespace(value="phase_2"),
            _block_reason="score_gate",
        )
        inputs = [
            {
                "candidate": caught,
                "mover": SimpleNamespace(ticker="SPRC", change_percent=60.0, price=3.2, volume=1_000_000),
                "event_type": "alerted",
            },
            {
                "candidate": blocked,
                "mover": SimpleNamespace(ticker="VERU", change_percent=400.0, price=25.0, volume=8_000_000),
                "event_type": "blocked",
            },
            {
                "mover": SimpleNamespace(ticker="BLIND", change_percent=120.0, price=8.8, volume=2_000_000),
                "event_type": "missed_discovery",
            },
        ]

        service.record_eod_reviews(review_date=review_date, items=inputs)

        rows = {row.ticker: row for row in db.query(AlertTimingReview).all()}
        assert rows["SPRC"].timing_label == "EARLY_WIN"
        assert rows["VERU"].timing_label == "MISSED_ALERT"
        assert rows["BLIND"].timing_label == "MISSED_DISCOVERY"
    finally:
        db.close()
