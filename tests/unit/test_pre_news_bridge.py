from src.core.agentic import pre_news_bridge
from src.core.agentic.pre_news_bridge import apply_pre_news_to_candidate


class _Trap:
    def __init__(self):
        self.trap_risk_score = 20


class _Catalyst:
    def __init__(self):
        self.strength_score = 40


class _Candidate:
    ticker = "PNX"

    def __init__(self):
        self.trap = _Trap()
        self.catalyst = _Catalyst()
        self.pre_news_suspicion_score = 0
        self.pre_news_has_anomaly = False


def test_bridge_reads_current_pre_news_fields_for_no_news_anomaly(monkeypatch):
    monkeypatch.setattr(
        pre_news_bridge,
        "get_pre_news_for_ticker",
        lambda ticker: {
            "ticker": ticker,
            "classification": "high",
            "pre_news_suspicion_score": 72,
            "news_status": "no_news_found",
        },
    )
    candidate = _Candidate()

    apply_pre_news_to_candidate(candidate)

    assert candidate.pre_news_has_anomaly is True
    assert candidate.pre_news_suspicion_score == 72
    assert candidate.trap.trap_risk_score == 30


def test_bridge_reads_current_confirmed_news_status(monkeypatch):
    monkeypatch.setattr(
        pre_news_bridge,
        "get_pre_news_for_ticker",
        lambda ticker: {
            "ticker": ticker,
            "classification": "extreme",
            "pre_news_suspicion_score": 88,
            "news_status": "news_lag_confirmed",
        },
    )
    candidate = _Candidate()

    apply_pre_news_to_candidate(candidate)

    assert candidate.pre_news_has_anomaly is True
    assert candidate.pre_news_suspicion_score == 88
    assert candidate.catalyst.strength_score == 48
