from __future__ import annotations

import asyncio
import threading
import time
from types import SimpleNamespace

from src.core.agentic.pre_news_detector import PreNewsDetector
from src.core.agentic.pre_news_models import SuspicionLevel


def _anomaly(ticker: str, score: float = 50.0):
    return SimpleNamespace(
        ticker=ticker,
        pre_news_suspicion_score=score,
        classification=SuspicionLevel.LOW,
    )


def _detector(universe):
    detector = object.__new__(PreNewsDetector)
    detector._get_universe = lambda: universe
    detector._fetch_news_batch = lambda: _async_value([])
    detector._enrich_top_anomalies_with_polygon = lambda results, news_items=None: results
    detector._persist_state = lambda: None
    detector._capture_baselines = lambda tickers, news_items=None: None
    detector._get_evaluator = lambda: SimpleNamespace(record_detection=lambda *args, **kwargs: None)
    return detector


async def _async_value(value):
    return value


def test_pre_news_concurrency_respects_limit(monkeypatch):
    detector = _detector(["A", "B", "C", "D"])
    lock = threading.Lock()
    active = 0
    max_seen = 0

    def analyze(ticker, min_rvol, news_items):
        nonlocal active, max_seen
        with lock:
            active += 1
            max_seen = max(max_seen, active)
        time.sleep(0.05)
        with lock:
            active -= 1
        return _anomaly(ticker)

    detector._analyze_ticker = analyze
    monkeypatch.setenv("PRE_NEWS_MAX_CONCURRENT_ANALYSES", "2")
    monkeypatch.setenv("PRE_NEWS_PER_TICKER_TIMEOUT_SECONDS", "1")
    monkeypatch.setenv("PRE_NEWS_SCAN_BUDGET_SECONDS", "5")

    results = asyncio.run(detector.scan())

    assert len(results) == 4
    assert max_seen <= 2


def test_pre_news_timeout_does_not_kill_full_scan(monkeypatch):
    detector = _detector(["SLOW", "FAST"])

    def analyze(ticker, min_rvol, news_items):
        if ticker == "SLOW":
            time.sleep(0.7)
            return _anomaly(ticker)
        return _anomaly(ticker)

    detector._analyze_ticker = analyze
    monkeypatch.setenv("PRE_NEWS_MAX_CONCURRENT_ANALYSES", "2")
    monkeypatch.setenv("PRE_NEWS_PER_TICKER_TIMEOUT_SECONDS", "0.05")
    monkeypatch.setenv("PRE_NEWS_SCAN_BUDGET_SECONDS", "5")

    results = asyncio.run(detector.scan())

    assert [r.ticker for r in results] == ["FAST"]
