from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_frontend_exposes_timing_review_route_and_nav():
    app = (ROOT / "frontend/src/App.jsx").read_text(encoding="utf-8")

    assert "TimingReview" in app
    assert "/timing-review" in app
    assert "Timing Review" in app


def test_frontend_has_timing_review_api_helpers():
    api = (ROOT / "frontend/src/api_strategic.js").read_text(encoding="utf-8")

    assert "newsMomentumTimingReviews" in api
    assert "newsMomentumTimingSummary" in api
    assert "/news-momentum/timing-reviews" in api


def test_timing_review_page_surfaces_core_labels():
    page = (ROOT / "frontend/src/pages/TimingReview.jsx").read_text(encoding="utf-8")

    for label in [
        "EARLY_WIN",
        "ON_TIME_WIN",
        "LATE_CHASE",
        "MISSED_ALERT",
        "MISSED_DISCOVERY",
        "FALSE_POSITIVE",
    ]:
        assert label in page
