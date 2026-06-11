from pathlib import Path


def test_global_news_scan_happens_before_ticker_enrichment():
    source = Path("src/main.py").read_text(encoding="utf-8")

    # Two-phase polling: fast wires scanned first, then Finviz ("global"),
    # and BOTH before any ticker-page enrichment fetch.
    fast_scan = source.index('"fast-source")')
    global_scan = source.index('_run_scan(_events_from_items(slow_items), "global")')
    ticker_fetch = source.index("fetch_ticker_news")

    assert fast_scan < global_scan < ticker_fetch


def test_ticker_enrichment_has_timeout_budget():
    source = Path("src/main.py").read_text(encoding="utf-8")

    assert "FINVIZ_TICKER_ENRICHMENT_BUDGET_SECONDS" in source
    assert "asyncio.wait_for" in source
    assert "ticker-specific news timeout" in source

