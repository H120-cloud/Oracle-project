from pathlib import Path


def test_global_news_scan_happens_before_ticker_enrichment():
    source = Path("src/main.py").read_text(encoding="utf-8")

    global_scan = source.index("NewsMomentum: global scan found")
    ticker_fetch = source.index("fetch_ticker_news")

    assert global_scan < ticker_fetch


def test_ticker_enrichment_has_timeout_budget():
    source = Path("src/main.py").read_text(encoding="utf-8")

    assert "FINVIZ_TICKER_ENRICHMENT_BUDGET_SECONDS" in source
    assert "asyncio.wait_for" in source
    assert "ticker-specific news timeout" in source

