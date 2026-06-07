from scripts.dev.fake_rocket_news_site_simulation import (
    FAKE_CASES,
    build_candidate,
    fetch_fake_news,
    fetch_fake_quote,
    run_with_local_fake_site,
    FakeSiteHandler,
)
from http.server import ThreadingHTTPServer
import threading
from datetime import datetime, timezone


def _serve_fake_site():
    FakeSiteHandler.now = datetime.now(timezone.utc)
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeSiteHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, f"http://{server.server_address[0]}:{server.server_address[1]}"


def test_fake_site_serves_expected_case_mix():
    assert len(FAKE_CASES) == 10
    assert sum(1 for c in FAKE_CASES if c.actual_outcome == "ROCKET") == 1
    assert sum(1 for c in FAKE_CASES if c.actual_outcome == "LEGENDARY") == 3
    assert sum(1 for c in FAKE_CASES if c.actual_outcome == "NON_RUNNER") == 6


def test_fake_site_scrape_and_quote_to_candidate():
    server, thread, base_url = _serve_fake_site()
    try:
        items = fetch_fake_news(base_url)
        assert len(items) == 10
        first = items[0]
        quote = fetch_fake_quote(base_url, first["ticker"])
        candidate = build_candidate(first, quote, base_url)
        assert candidate.ticker == "ORCK"
        assert candidate.source.value == "oracle_scanner"
        assert candidate.current_price == quote["current_price"]
        assert candidate.rvol == quote["rvol"]
        assert candidate.catalyst_sub_type.value in {
            "government_contract",
            "major_partnership",
            "other",
        }
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_fake_site_simulation_is_dry_run_and_reports_results():
    result = run_with_local_fake_site()
    assert result["total_cases"] == 10
    assert result["expected_positive_cases"] == 4
    assert result["expected_non_runner_cases"] == 6
    assert result["positive_alert_recall_pct"] == 100.0
    assert result["non_runner_suppression_pct"] == 100.0
    assert result["misses"] == []
    assert result["false_alerts"] == []
    assert len(result["telegram_messages"]) == result["dry_run_telegram_alerts"]
    assert all(msg["alert_type"] == "dry_run_news_momentum" for msg in result["telegram_messages"])
