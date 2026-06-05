from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_strategic_api_exposes_news_momentum_source_health_helper():
    api = (ROOT / "frontend" / "src" / "api_strategic.js").read_text(encoding="utf-8")

    assert "newsMomentumSourceHealth" in api
    assert "/news-momentum/source-health" in api


def test_news_page_renders_scraper_health_panel():
    page = (ROOT / "frontend" / "src" / "pages" / "News.jsx").read_text(encoding="utf-8")

    assert "Scraper Health" in page
    assert "tickered_headline_count" in page
    assert "untickered_headline_count" in page
    assert "dropped_headline_count" in page
    assert "missing_timestamp_count" in page
    assert "parse_error_count" in page
