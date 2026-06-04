from __future__ import annotations

from datetime import datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.db.session import get_db
from src.models.database import AlertTimingReview, Base


def _client_with_rows(rows):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        for row in rows:
            db.add(AlertTimingReview(**row))
        db.commit()
    finally:
        db.close()

    from src.api.routes.timing_reviews import router

    app = FastAPI()

    def override_db():
        session = Session()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_db
    app.include_router(router, prefix="/api/v1")
    return TestClient(app)


def test_timing_reviews_list_filters_by_label_and_ticker():
    client = _client_with_rows([
        {
            "review_date": "2026-06-04",
            "ticker": "VERU",
            "source_system": "news_momentum",
            "event_type": "blocked",
            "timing_label": "MISSED_ALERT",
            "headline": "Veru secures Novo Nordisk supply",
            "move_after_alert_pct": 400.0,
            "reviewed_at": datetime.utcnow(),
        },
        {
            "review_date": "2026-06-04",
            "ticker": "SPRC",
            "source_system": "news_momentum",
            "event_type": "alerted",
            "timing_label": "EARLY_WIN",
            "headline": "SciSparc deal",
            "move_after_alert_pct": 55.0,
            "reviewed_at": datetime.utcnow(),
        },
    ])

    response = client.get("/api/v1/news-momentum/timing-reviews?label=MISSED_ALERT&ticker=VERU")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["items"][0]["ticker"] == "VERU"
    assert payload["items"][0]["timing_label"] == "MISSED_ALERT"


def test_timing_reviews_summary_counts_labels():
    client = _client_with_rows([
        {
            "review_date": "2026-06-04",
            "ticker": "VERU",
            "source_system": "news_momentum",
            "event_type": "blocked",
            "timing_label": "MISSED_ALERT",
        },
        {
            "review_date": "2026-06-04",
            "ticker": "SPRC",
            "source_system": "news_momentum",
            "event_type": "alerted",
            "timing_label": "EARLY_WIN",
        },
        {
            "review_date": "2026-06-04",
            "ticker": "CHASE",
            "source_system": "news_momentum",
            "event_type": "alerted",
            "timing_label": "LATE_CHASE",
        },
    ])

    response = client.get("/api/v1/news-momentum/timing-reviews/summary")

    assert response.status_code == 200
    assert response.json()["total"] == 3
    assert response.json()["by_label"] == {
        "EARLY_WIN": 1,
        "LATE_CHASE": 1,
        "MISSED_ALERT": 1,
    }
