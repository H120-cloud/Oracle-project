from __future__ import annotations

from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.routes import news_momentum
from src.core.agentic.source_health_registry import source_health_tracker


def test_news_momentum_source_health_endpoint_returns_live_tracker_state():
    source_health_tracker.reset()
    now = datetime(2026, 6, 4, tzinfo=timezone.utc)
    source_health_tracker.record_fetch("Finviz", 25, now=now)
    source_health_tracker.record_tickered_headline("Finviz", 20)
    source_health_tracker.record_untickered_headline("Finviz", 5)

    app = FastAPI()
    app.include_router(news_momentum.router, prefix="/api/v1")
    client = TestClient(app)

    response = client.get("/api/v1/news-momentum/source-health")

    assert response.status_code == 200
    data = response.json()
    assert data["total_sources"] >= 1
    assert data["sources"]["finviz"]["headlines_fetched"] == 25
    assert data["sources"]["finviz"]["tickered_headline_count"] == 20
    assert data["sources"]["finviz"]["untickered_headline_count"] == 5
    assert data["sources"]["finviz"]["dropped_headline_count"] == 5
