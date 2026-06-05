from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from src.core.agentic.pre_news_alert_audit import record_pre_news_alert_decision
from src.core.agentic.pre_news_detector import PreNewsDetector
from src.core.agentic.pre_news_models import PriceBehaviour


def _detector() -> PreNewsDetector:
    detector = object.__new__(PreNewsDetector)
    detector._alert_cooldowns = {}
    return detector


def _anomaly(**overrides):
    base = {
        "ticker": "TEST",
        "detected_at": datetime(2026, 6, 5, 14, 30, tzinfo=timezone.utc),
        "pre_news_suspicion_score": 82,
        "smart_money_score": 70,
        "alert_quality": "good",
        "late_detection_flag": False,
        "alert_sent": False,
        "last_alert_score": 0,
        "offering_risk_score": 0,
        "data_quality_state": "ok",
        "news_status": "no_news_found",
        "anomaly_type": "quiet_volume_build",
        "price": 1.23,
        "price_behaviour": SimpleNamespace(
            behaviour=PriceBehaviour.QUIET_ACCUMULATION,
            price_change_pct=1.5,
        ),
        "volume_metrics": SimpleNamespace(
            rvol_current=8.0,
            volume_acceleration=0.2,
            accel_trend="accelerating",
        ),
        "alert_suppression_reasons": [],
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_pre_news_alert_decision_allows_clean_high_score_anomaly():
    decision = _detector().explain_alert_decision(_anomaly())

    assert decision == {"should_alert": True, "reasons": []}


def test_pre_news_alert_decision_lists_all_block_reasons():
    detector = _detector()
    now = datetime(2026, 6, 5, 15, 0, tzinfo=timezone.utc)
    detector._alert_cooldowns["TEST"] = now - timedelta(minutes=5)
    anomaly = _anomaly(
        pre_news_suspicion_score=70,
        alert_quality="late",
        alert_sent=True,
        last_alert_score=68,
        price_behaviour=SimpleNamespace(
            behaviour=PriceBehaviour.ALREADY_EXTENDED,
            price_change_pct=18.0,
        ),
        volume_metrics=SimpleNamespace(
            rvol_current=8.0,
            volume_acceleration=-0.4,
            accel_trend="decelerating",
        ),
        alert_suppression_reasons=["late", "extended", "fading"],
    )

    decision = detector.explain_alert_decision(anomaly, now=now)

    assert decision["should_alert"] is False
    assert decision["reasons"] == [
        "score_below_75",
        "late_quality_score_below_85",
        "already_alerted_score_delta_too_small",
        "cooldown_active",
        "already_extended",
        "volume_fading",
        "too_many_suppression_reasons",
    ]


def test_pre_news_alert_decision_audit_writes_jsonl(tmp_path):
    audit_path = tmp_path / "pre_news_alert_decisions.jsonl"
    anomaly = _anomaly()
    decision = {"should_alert": True, "reasons": []}

    record = record_pre_news_alert_decision(
        anomaly,
        decision,
        telegram_attempted=True,
        telegram_sent=True,
        audit_path=audit_path,
    )

    rows = [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines()]
    assert rows == [record]
    assert rows[0]["ticker"] == "TEST"
    assert rows[0]["should_alert"] is True
    assert rows[0]["telegram_attempted"] is True
    assert rows[0]["telegram_sent"] is True
    assert rows[0]["price_behaviour"] == "quiet_accumulation"
