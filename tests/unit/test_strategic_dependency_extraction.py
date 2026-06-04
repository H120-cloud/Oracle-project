from pathlib import Path
from types import SimpleNamespace
import asyncio


def test_strategic_finviz_parser_supports_current_link_shapes():
    from src.core.agentic.finviz_universe import parse_finviz_tickers_from_html

    html = """
    <html><body>
      <a href="stock?t=ASTC&ty=c&p=d&b=1">1</a>
      <td data-boxover-ticker="ASTC">
        <a href="stock?t=ASTC&ty=c&p=d&b=1" class="tab-link">ASTC</a>
      </td>
      <a href="quote.ashx?t=CRCL&p=d">CRCL</a>
    </body></html>
    """

    assert parse_finviz_tickers_from_html(html) == ["ASTC", "CRCL"]


def test_strategic_callers_no_longer_import_legacy_finviz_scanner():
    strategic_files = [
        Path("src/core/agentic/pre_news_detector.py"),
        Path("src/core/agentic/pre_news_learning.py"),
        Path("src/core/agentic/news_momentum_eod_review.py"),
        Path("src/main.py"),
    ]

    for path in strategic_files:
        text = path.read_text(encoding="utf-8")
        assert "src.core.finviz_scanner" not in text
        assert "FinvizScanner" not in text


def test_frontend_api_split_has_strategic_legacy_boundaries():
    strategic = Path("frontend/src/api_strategic.js")
    legacy = Path("frontend/src/api_legacy.js")
    compat = Path("frontend/src/api.js")

    assert strategic.exists()
    assert legacy.exists()
    assert compat.exists()

    strategic_text = strategic.read_text(encoding="utf-8")
    legacy_only_helpers = [
        "getSignals",
        "runBacktest",
        "getWatchlist",
        "analyzeIntelligence",
        "discoverTrading212",
    ]
    for helper in legacy_only_helpers:
        assert f"export const {helper}" not in strategic_text

    compat_text = compat.read_text(encoding="utf-8")
    assert "api_strategic" in compat_text
    assert "api_legacy" in compat_text


def test_ohlcvbar_is_reexported_from_strategic_market_data_model():
    from src.models.market_data import OHLCVBar as StrategicOHLCVBar
    from src.models.schemas import OHLCVBar

    assert OHLCVBar is StrategicOHLCVBar


def test_news_momentum_eod_review_uses_strategic_finviz_snapshot(monkeypatch):
    from src.core.agentic import finviz_universe
    from src.core.agentic.news_momentum_eod_review import NewsMomentumEODReviewer

    monkeypatch.setattr(
        finviz_universe,
        "fetch_finviz_top_gainers_snapshot",
        lambda max_results=30: [
            SimpleNamespace(
                ticker="SPRC",
                change_percent=25.0,
                price=4.2,
                volume=1_500_000,
                rvol=8.5,
            )
        ],
    )

    class Orchestrator:
        _candidates = []

        def get_active_candidates(self):
            return []

    result = asyncio.run(NewsMomentumEODReviewer(Orchestrator()).run_review(force=True))

    assert result["movers_reviewed"] == 1
    assert result["missed_discovery"][0]["ticker"] == "SPRC"


def test_pre_news_manual_universe_no_longer_imports_legacy_watchlist_repository():
    pre_news_text = Path("src/core/agentic/pre_news_detector.py").read_text(encoding="utf-8")

    assert "src.db.repositories" not in pre_news_text
    assert "WatchlistRepository" not in pre_news_text
    assert "get_manual_universe_tickers" in pre_news_text


def test_strategic_manual_universe_uses_strategic_model_alias():
    from src.core.agentic.manual_universe import get_manual_universe_tickers
    from src.models.strategic import ManualUniverseTicker
    from src.models.database import Watchlist

    assert callable(get_manual_universe_tickers)
    assert ManualUniverseTicker is Watchlist


def test_strategic_news_quote_endpoint_replaces_analysis_live_quote():
    strategic_api = Path("frontend/src/api_strategic.js").read_text(encoding="utf-8")
    news_route = Path("src/api/routes/news.py").read_text(encoding="utf-8")
    news_page = Path("frontend/src/pages/News.jsx").read_text(encoding="utf-8")

    assert "/news/quote/" in strategic_api
    assert "/analysis/live-quote" not in strategic_api
    assert '@router.get("/quote/{ticker}")' in news_route
    assert "api_strategic" in news_page
