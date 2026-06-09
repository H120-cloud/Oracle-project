"""Baseline regression coverage for six runtime crashes fixed via static analysis.

Each of these code paths previously raised NameError / ImportError at runtime
because a symbol was used but never imported (or a parameter was never passed),
and none had test coverage to catch it. These lean happy-path tests pin the call
sites so the specific regressions cannot return. External I/O (yfinance, the
market-data provider, the DecisionEngine) is mocked to keep them fast and
deterministic.
"""

import asyncio
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from src.models.schemas import OHLCVBar, DipResult, BounceResult


def _bars(closes, *, start=None, spread=0.3, volume=1000):
    """Build OHLCVBars from a list of close prices (open = previous close)."""
    base = start or datetime(2026, 1, 1, tzinfo=timezone.utc)
    bars = []
    prev = closes[0]
    for i, close in enumerate(closes):
        open_ = prev
        high = max(open_, close) + spread
        low = min(open_, close) - spread
        bars.append(OHLCVBar(
            timestamp=base + timedelta(minutes=5 * i),
            open=open_, high=high, low=low, close=close, volume=volume + i,
        ))
        prev = close
    return bars


# 1. pre_news.py — JSON success-rate report endpoint (the missing `json` import).
def test_pre_news_success_rate_report_reads_json(tmp_path, monkeypatch):
    import src.api.routes.pre_news as pn

    payload = {
        "generated_at": "2026-06-09T00:00:00Z",
        "data_quality": {"total_detections": 5, "usable_for_success_rate": 3},
        "overall_metrics": {"clean_success_rate": 0.42},
    }
    report = tmp_path / "pre_news_success_rate_report.json"
    report.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(pn, "agentic_path", lambda *parts: report)

    result = asyncio.run(pn.get_success_rate_report())  # exercises json.load via to_thread
    assert result == payload


def test_pre_news_success_rate_report_markdown(tmp_path, monkeypatch):
    import src.api.routes.pre_news as pn

    report = tmp_path / "pre_news_success_rate_report.md"
    report.write_text("# Success Rate\nclean runners: 42%", encoding="utf-8")
    monkeypatch.setattr(pn, "agentic_path", lambda *parts: report)

    result = asyncio.run(pn.get_success_rate_report_md())
    assert result["markdown"].startswith("# Success Rate")


# 2. pre_news_detector.py — random.sample in _capture_baselines (the missing `random` import).
def test_capture_baselines_executes_random_sample_without_nameerror():
    from src.core.agentic.pre_news_detector import PreNewsDetector

    # Bypass the heavy, disk-touching __init__; the method only needs these two.
    det = PreNewsDetector.__new__(PreNewsDetector)
    det._get_baseline_tracker = lambda: MagicMock()

    class _Provider:
        # price <= 0 makes every ticker short-circuit right after random.sample,
        # so no real quote/bars/yfinance work runs.
        def get_live_quote(self, ticker):
            return {"price": 0.0}

        def get_ohlcv(self, *a, **k):
            return []

    det._provider = _Provider()

    # Regression: random.sample(...) at the top of the method must not NameError.
    det._capture_baselines(["AAA", "BBB", "CCC", "DDD", "EEE"])


# 3. liquidity_engine.py — _detect_fake_breakouts / _detect_inducement use `o` (opens).
def test_liquidity_engine_analyze_uses_open_prices():
    from src.core.liquidity_engine import LiquidityEngine

    # 40 alternating up/down bars: >= 30 (analyze gate) and >= 15 (fake-breakout
    # gate), and the wick loop dereferences o[idx] on the last bars.
    closes = [10.0 + (0.2 if i % 2 == 0 else -0.15) * (i + 1) for i in range(40)]
    result = LiquidityEngine().analyze("TEST", _bars(closes))

    # Reaching a result proves the o[idx] call sites are stable (no NameError).
    assert result is not None
    assert result.ticker == "TEST"


# 4. main.py — _fetch_anomaly_prices (lifted to a module-level function).
def test_main_fetch_anomaly_prices_returns_peak_and_close(monkeypatch):
    import sys
    import src.main as main

    # Minimal stand-in for the pandas frame: hist["High"].max() and
    # hist["Close"].iloc[-1] are the only accesses the function makes.
    class _Col:
        def max(self):
            return 12.5

        @property
        def iloc(self):
            return {-1: 11.0}

    class _Hist:
        empty = False

        def __getitem__(self, column):
            return _Col()

    fake_yf = MagicMock()
    fake_yf.Ticker.return_value.history.return_value = _Hist()
    monkeypatch.setitem(sys.modules, "yfinance", fake_yf)  # local import resolves to the fake

    peak, last_close = main._fetch_anomaly_prices("ABCD")
    assert (peak, last_close) == (12.5, 11.0)
    fake_yf.Ticker.assert_called_once_with("ABCD")


def test_main_fetch_anomaly_prices_empty_history_returns_none(monkeypatch):
    import sys
    import src.main as main

    fake_yf = MagicMock()
    fake_yf.Ticker.return_value.history.return_value = MagicMock(empty=True)
    monkeypatch.setitem(sys.modules, "yfinance", fake_yf)

    assert main._fetch_anomaly_prices("ABCD") == (None, None)


# 5. regime_aware_backtester.py — IMarketDataProvider import + config.interval reference.
def test_regime_backtester_generate_signal_uses_interval():
    # Importing the class at all would fail if the IMarketDataProvider annotation
    # were still unresolved at import time.
    from src.core.regime_aware_backtester import RegimeAwareBacktester

    bt = RegimeAwareBacktester()
    sentinel = object()
    bt.decision_engine = MagicMock()
    bt.decision_engine.decide.return_value = sentinel

    bars = _bars([10.0 + i * 0.1 for i in range(12)])  # rising → no dip/bounce branch

    # Daily branch: interval == "1d" selects daily_bars = bars.
    assert bt._generate_signal("TEST", bars, bars[-1], "1d") is sentinel
    assert bt.decision_engine.decide.call_args.kwargs["daily_bars"] == bars

    # Non-daily branch: daily_bars = [].
    bt._generate_signal("TEST", bars, bars[-1], "5m")
    assert bt.decision_engine.decide.call_args.kwargs["daily_bars"] == []


# 6. live_trading_simulator.py — DipPhase / DipFeatures / BounceFeatures imports.
def test_live_simulator_detect_dip_and_bounce_construct_models():
    from src.core.live_trading_simulator import LiveTradingSimulator

    sim = LiveTradingSimulator.__new__(LiveTradingSimulator)  # methods only need .ticker
    sim.ticker = "TEST"

    # Falling closes (~ -25%) trigger the dip branch → builds DipPhase + DipFeatures.
    dip = sim._detect_dip(_bars([10.0 - i * 0.5 for i in range(6)]))
    assert isinstance(dip, DipResult)

    # last>prev and prev<prev-prev triggers the bounce branch → builds BounceFeatures.
    bounce = sim._detect_bounce(_bars([10.0, 9.5, 9.9]))
    assert isinstance(bounce, BounceResult)
