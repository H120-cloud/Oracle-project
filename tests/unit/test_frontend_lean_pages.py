from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_frontend_app_exposes_only_strategic_pages():
    source = (ROOT / "frontend/src/App.jsx").read_text(encoding="utf-8")

    kept_routes = [
        'path="/news"',
        'path="/agentic"',
        'path="/news-momentum"',
        'path="/sec-intelligence"',
        'path="/historical-training"',
    ]
    for route in kept_routes:
        assert route in source

    removed_terms = [
        "LegacyArchived",
        "Dashboard",
        "Active Trades",
        "Analysis",
        "Watchlist",
        "Portfolio",
        "Backtest",
        "Paper Trading",
        "Performance",
        "Settings",
        "FRONTEND_FLAGS",
    ]
    for term in removed_terms:
        assert term not in source

    removed_legacy_routes = [
        'path="/dashboard"',
        'path="/intelligence"',
        "to: '/dashboard'",
        "to: '/intelligence'",
        "label: 'Intelligence'",
    ]
    for route in removed_legacy_routes:
        assert route not in source


def test_frontend_public_api_does_not_export_legacy_helpers():
    source = (ROOT / "frontend/src/api.js").read_text(encoding="utf-8")

    assert "api_shared" in source
    assert "api_strategic" in source
    assert "api_legacy" not in source
