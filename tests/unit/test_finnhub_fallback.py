"""Finnhub must be available as a quote fallback when FINNHUB_API_KEY is set.

On cloud hosts yfinance is IP-blocked and Alpaca's free IEX feed is sparse, so
candidates sat `blocked/no_price` for many minutes and alerts fired ~20 min
late, only when a price finally trickled in. Finnhub works from the cloud, but
was only used when MARKET_DATA_PROVIDER=finnhub — never as a fallback.
"""

import pytest

from src.core.agentic.news_momentum_orchestrator import NewsMomentumOrchestrator


def _bare_orchestrator():
    orch = object.__new__(NewsMomentumOrchestrator)  # skip heavy __init__
    orch._finnhub_provider = None
    return orch


@pytest.mark.unit
def test_no_finnhub_provider_without_key(monkeypatch):
    monkeypatch.delenv("FINNHUB_API_KEY", raising=False)
    monkeypatch.setattr(
        "src.config.get_settings",
        lambda: type("S", (), {"finnhub_api_key": ""})(),
    )
    assert _bare_orchestrator()._get_finnhub_provider() is None


@pytest.mark.unit
def test_finnhub_provider_built_from_env_key(monkeypatch):
    monkeypatch.setenv("FINNHUB_API_KEY", "test-key-123")
    orch = _bare_orchestrator()
    provider = orch._get_finnhub_provider()
    assert provider is not None
    assert hasattr(provider, "get_live_quote")
    # cached on second call
    assert orch._get_finnhub_provider() is provider


@pytest.mark.unit
def test_enrichment_chain_includes_finnhub_fallback():
    import inspect
    src = inspect.getsource(NewsMomentumOrchestrator)
    assert "_get_finnhub_provider" in src
    # wired into the quote chain, not just defined
    assert src.count("_get_finnhub_provider") >= 2
