"""Regression: post-news price fetch must not block the asyncio event loop.

`_fetch_post_news_prices` used to call the blocking `yfinance` API directly on
the event loop. On cloud hosts (Railway) yfinance is throttled and the call
hangs for minutes, freezing the entire single-threaded server — every request,
including /health, stalled until it returned. The fetch must run off-loop so a
slow provider can't starve request handling.
"""

import asyncio
import time

import pandas as pd
import pytest
import yfinance

from src.core.agentic.news_momentum_orchestrator import NewsMomentumOrchestrator


class _SlowTicker:
    """Simulates a slow/blocked yfinance call."""

    def __init__(self, *args, **kwargs):
        pass

    def history(self, *args, **kwargs):
        time.sleep(0.3)  # blocking — stands in for a throttled cloud fetch
        return pd.DataFrame()  # empty → method returns None


class _Candidate:
    ticker = "AAA"
    published_at = None
    detected_at = None
    current_price = None


@pytest.mark.unit
def test_fetch_post_news_prices_does_not_block_event_loop(monkeypatch):
    monkeypatch.setattr(yfinance, "Ticker", _SlowTicker)
    orch = object.__new__(NewsMomentumOrchestrator)  # skip the heavy __init__

    async def _run():
        ticks = 0

        async def heartbeat():
            nonlocal ticks
            for _ in range(50):
                await asyncio.sleep(0.02)
                ticks += 1

        hb = asyncio.ensure_future(heartbeat())
        result = await orch._fetch_post_news_prices(_Candidate())
        hb.cancel()
        return result, ticks

    result, ticks = asyncio.run(_run())

    assert result is None
    # If the blocking fetch runs ON the loop, the heartbeat is starved during the
    # 0.3s sleep and ticks ~0. Run off-loop, it keeps ticking (~15).
    assert ticks >= 3, f"event loop was blocked during the fetch (ticks={ticks})"
