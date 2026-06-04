from __future__ import annotations

import asyncio
import sys
import time
from datetime import datetime, timezone
from types import SimpleNamespace

from src.core.agentic.news_momentum_models import (
    CatalystCategory,
    CatalystSubType,
    NewsMomentumCandidate,
    NewsMomentumConfig,
    NewsSource,
    SessionType,
)
from src.core.agentic.news_momentum_orchestrator import NewsMomentumOrchestrator


def _candidate() -> NewsMomentumCandidate:
    return NewsMomentumCandidate(
        ticker="SLOW",
        headline="SLOW announces FDA approval",
        source=NewsSource.FINVIZ,
        published_at=datetime.now(timezone.utc),
        session=SessionType.REGULAR,
        catalyst_category=CatalystCategory.BIOTECH,
        catalyst_sub_type=CatalystSubType.FDA_APPROVAL,
    )


def test_slow_provider_times_out_without_blocking_scan(monkeypatch):
    class SlowProvider:
        def get_live_quote(self, ticker):
            time.sleep(0.2)
            return {"price": 4.2, "previous_close": 4.0}

    orch = object.__new__(NewsMomentumOrchestrator)
    orch.config = NewsMomentumConfig(learning_enabled=False)
    orch._get_polygon_provider = lambda: None
    monkeypatch.setattr(
        "src.services.market_data.get_market_data_provider",
        lambda: SlowProvider(),
    )
    monkeypatch.setenv("NEWS_MARKET_DATA_CANDIDATE_BUDGET_SECONDS", "0.05")

    candidate = _candidate()
    started = time.perf_counter()
    asyncio.run(orch._enrich_with_market_data(candidate))
    elapsed = time.perf_counter() - started

    assert elapsed < 0.5
    assert candidate.price_status == "pending"
    assert candidate.current_price is None


def test_fast_provider_marks_price_complete(monkeypatch):
    class FastProvider:
        def get_live_quote(self, ticker):
            return {"price": 4.2, "previous_close": 4.0, "volume": 1000, "average_volume": 500}

    orch = object.__new__(NewsMomentumOrchestrator)
    orch.config = NewsMomentumConfig(learning_enabled=False)
    orch._get_polygon_provider = lambda: None
    monkeypatch.setattr(
        "src.services.market_data.get_market_data_provider",
        lambda: FastProvider(),
    )
    monkeypatch.setenv("NEWS_MARKET_DATA_CANDIDATE_BUDGET_SECONDS", "1")
    fake_fast_info = SimpleNamespace(
        last_price=4.2,
        previous_close=4.0,
        last_volume=1000,
        three_month_average_volume=500,
    )
    fake_yfinance = SimpleNamespace(
        Ticker=lambda ticker: SimpleNamespace(
            fast_info=fake_fast_info,
            info={"floatShares": 1_000_000, "marketCap": 10_000_000},
        )
    )
    monkeypatch.setitem(sys.modules, "yfinance", fake_yfinance)

    candidate = _candidate()
    asyncio.run(orch._enrich_with_market_data(candidate))

    assert candidate.price_status == "complete"
    assert candidate.current_price == 4.2
    assert candidate.move_pct == 5.0
