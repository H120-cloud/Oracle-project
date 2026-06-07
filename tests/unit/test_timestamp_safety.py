from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from src.core.agentic.catalyst_scanner import CatalystScanner, compute_catalyst_freshness
from src.core.agentic import sec_edgar_firehose
from src.core.agentic.historical_dataset_builder import HistoricalDatasetBuilder
from src.core.agentic.historical_models import DataQuality
from src.core.agentic.models import CatalystType
from src.core.agentic.news_momentum_models import (
    CatalystCategory,
    CatalystSubType,
    NewsMomentumCandidate,
    NewsMomentumConfig,
    NewsSource,
    SessionType,
)
from src.core.agentic.news_momentum_orchestrator import NewsMomentumOrchestrator
from src.core.finviz_news import FinvizNewsItem
from src.core.wire_news import parse_wire_feed_html


class _Summary:
    def __init__(self, items):
        self.news_items = items
        self.blog_items = []


class _Scraper:
    def __init__(self, items):
        self._items = items

    def fetch_all_sync(self):
        return _Summary(self._items)


class _Provider:
    def __init__(self):
        self.calls = []

    def get_live_quote(self, ticker):
        self.calls.append(ticker)
        return {
            "price": 1.2,
            "previous_close": 1.0,
            "volume": 10_000_000,
            "day_high": 1.3,
            "change_pct": 20.0,
            "market_cap": 10_000_000,
        }


def _scanner_with_items(items):
    scanner = object.__new__(CatalystScanner)
    scanner._news_scraper = _Scraper(items)
    scanner._stocktitan_scraper = _Scraper([])
    scanner._provider = _Provider()
    scanner._bad_tickers = set()
    scanner._save_bad_tickers = lambda: None
    return scanner


def _minimal_gate_orchestrator() -> NewsMomentumOrchestrator:
    orch = object.__new__(NewsMomentumOrchestrator)
    orch.config = NewsMomentumConfig(learning_enabled=False)
    orch._alert_cooldown = {}
    orch._headline_alert_cooldown = {}
    orch._unknown_learner = None
    return orch


def _fresh_bullish_candidate(ticker: str = "FAST") -> NewsMomentumCandidate:
    now = datetime.now(timezone.utc)
    return NewsMomentumCandidate(
        ticker=ticker,
        headline=f"{ticker} announces FDA approval for breakthrough therapy",
        source=NewsSource.FINVIZ,
        published_at=now - timedelta(seconds=60),
        detected_at=now - timedelta(seconds=30),
        session=SessionType.REGULAR,
        catalyst_category=CatalystCategory.BIOTECH,
        catalyst_sub_type=CatalystSubType.FDA_APPROVAL,
        current_price=5.0,
        news_impact_score=10.0,
        expected_return_score=10.0,
        continuation_probability=10.0,
        trap_risk=0.0,
        dilution_risk=0.0,
    )


def test_catalyst_scanner_missing_timestamp_does_not_become_fresh():
    item = FinvizNewsItem(
        headline="MISS announces FDA approval for breakthrough therapy",
        source="UnitFeed",
        url="https://example.test/miss",
        timestamp=None,
        tickers=["MISS"],
    )
    scanner = _scanner_with_items([item])

    assert scanner.scan(min_change_pct=1.0, min_rvol=0.0) == []
    assert scanner._provider.calls == []


def test_catalyst_scanner_old_timestamp_is_not_refreshed_by_detection_time(monkeypatch):
    old_timestamp = datetime.now(timezone.utc) - timedelta(hours=8)
    item = FinvizNewsItem(
        headline="OLD wins major government contract",
        source="UnitFeed",
        url="https://example.test/old",
        timestamp=old_timestamp,
        tickers=["OLD"],
    )
    scanner = _scanner_with_items([item])
    monkeypatch.setattr("src.core.agentic.catalyst_scanner.yf.Ticker", lambda ticker: SimpleNamespace(fast_info=SimpleNamespace()))

    result = scanner.scan(min_change_pct=1.0, min_rvol=0.0)

    assert len(result) == 1
    assert result[0].catalyst.discovered_at == old_timestamp
    assert result[0].catalyst.freshness_minutes == 0.0


def test_date_only_wire_timestamp_has_low_confidence():
    html = """
    <rss><channel><item>
      <title>ACME Corp. (NASDAQ: ACME) announces strategic investment</title>
      <link>https://example.test/acme</link>
      <description>TORONTO, June 05, 2026 (GLOBE NEWSWIRE) -- ACME announces strategic investment.</description>
    </item></channel></rss>
    """

    items = parse_wire_feed_html(html, source="GlobeNewswire", base_url="https://example.test")

    assert len(items) == 1
    assert items[0].timestamp is not None
    assert items[0].timestamp_confidence == "LOW"


def test_missing_timestamp_cannot_trigger_first_mover():
    orch = _minimal_gate_orchestrator()
    candidate = _fresh_bullish_candidate("NOPUB2")
    candidate.published_at = None

    orch._should_send_telegram_impl(candidate, adaptive={})

    assert getattr(candidate, "_first_mover", False) is False
    assert candidate.freshness_confidence == "LOW"


def test_missing_timestamp_cannot_trigger_fast_watch(monkeypatch):
    orch = _minimal_gate_orchestrator()
    candidate = _fresh_bullish_candidate("NOWATCH")
    candidate.source = NewsSource.STOCKTITAN
    candidate.catalyst_sub_type = CatalystSubType.FDA_APPROVAL
    candidate.published_at = None

    async def fail_if_called(*_args, **_kwargs):
        raise AssertionError("missing timestamp must not send fast WATCH")

    monkeypatch.setattr(
        "src.core.agentic.news_momentum_orchestrator.send_telegram_alert",
        fail_if_called,
    )

    assert asyncio.run(orch._send_fast_path_watch(candidate)) is False
    assert candidate.fast_path_watch_sent is False


def test_old_timestamp_cannot_be_refreshed_by_detection_time_for_first_mover():
    orch = _minimal_gate_orchestrator()
    candidate = _fresh_bullish_candidate("OLDPUB")
    candidate.published_at = datetime.now(timezone.utc) - timedelta(hours=2)
    candidate.detected_at = datetime.now(timezone.utc) - timedelta(seconds=20)

    orch._should_send_telegram_impl(candidate, adaptive={})

    assert getattr(candidate, "_first_mover", False) is False
    assert candidate.published_age_seconds > 3600


class _SECResponse:
    status_code = 200

    def __init__(self, text: str):
        self.text = text


class _SECClient:
    def __init__(self, text: str):
        self.text = text

    async def get(self, _url: str):
        return _SECResponse(self.text)


def test_sec_firehose_missing_updated_timestamp_is_not_emitted(monkeypatch):
    monkeypatch.setattr(sec_edgar_firehose, "_CIK_TICKER_MAP", {"0000863894": "VERU"})
    text = """
    <feed><entry>
      <title>8-K - VERU INC. (0000863894) (Filer)</title>
      <id>accession-number=0000000000-26-000099&lt;</id>
      <link href="https://www.sec.gov/Archives/edgar/data/863894/x/veru-8k.htm"/>
      <summary>Veru entered into a clinical supply agreement.</summary>
    </entry></feed>
    """
    seen: set[str] = set()

    filings = asyncio.run(sec_edgar_firehose.fetch_current_filings(seen, client=_SECClient(text)))

    assert filings == []
    assert "0000000000-26-000099" in seen


def test_historical_dataset_missing_timestamp_stays_missing(tmp_path):
    builder = HistoricalDatasetBuilder(data_dir=str(tmp_path))

    event = builder.add_event(
        ticker="MISS",
        catalyst_type=CatalystType.CONTRACT,
        headline="MISS wins contract",
        timestamp=None,
    )

    assert event.catalyst_timestamp is None
    assert event.event_date == ""
    assert event.data_quality == DataQuality.PARTIAL
