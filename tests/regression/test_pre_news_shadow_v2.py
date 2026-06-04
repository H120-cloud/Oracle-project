"""
Tests for the Pre-News Shadow Logger V2.

Covers the plan's required surfaces:
  - baseline gate decision
  - V2 gate decision
  - shadow record creation
  - outcome resolver fields
  - report generation
  - NO production alert behavior changed (module never imports/calls senders)
"""
from __future__ import annotations

import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

from src.core.agentic.pre_news_shadow_v2 import (
    PreNewsShadowV2, ShadowRecord, baseline_decision, v2_decision,
    V2_QUALIFYING_TYPES,
)

pytestmark = [pytest.mark.regression]


def _anom(**kw):
    base = dict(
        ticker="TST",
        detected_at=datetime.now(timezone.utc).isoformat(),
        anomaly_type="unusual_volume_no_news",
        pre_news_suspicion_score=40.0,
        alert_quality="early",
        price=2.0,
        offering_risk_score=10.0,
        data_quality="full",
        float_shares=5_000_000,
        market_cap=80_000_000,
        volume_anomaly_score=70.0,
        volume_metrics={"volume_acceleration": 1.2},
        price_behaviour={"vwap_distance_pct": 3.0},
    )
    base.update(kw)
    return base


# -- baseline gate -----------------------------------------------------------

def test_baseline_alerts_only_above_75():
    ok, _ = baseline_decision(_anom(pre_news_suspicion_score=80))
    assert ok is True
    no, reason = baseline_decision(_anom(pre_news_suspicion_score=74))
    assert no is False and "suspicion" in reason


def test_baseline_blocks_trap_quality_even_high_score():
    no, reason = baseline_decision(_anom(pre_news_suspicion_score=90, alert_quality="trap_risk"))
    assert no is False and "trap_risk" in reason


# -- V2 gate -----------------------------------------------------------------

def test_v2_alerts_on_qualifying_type_regardless_of_suspicion():
    ok, _ = v2_decision(_anom(pre_news_suspicion_score=11))  # WGRX-style whisper
    assert ok is True


def test_v2_blocks_nonqualifying_type():
    no, reason = v2_decision(_anom(anomaly_type="suspicious_pump_risk"))
    assert no is False and "anomaly_type" in reason


def test_v2_blocks_severe_offering_risk():
    no, reason = v2_decision(_anom(offering_risk_score=85))
    assert no is False and "offering_risk" in reason


def test_v2_blocks_degraded_data_quality():
    no, reason = v2_decision(_anom(data_quality="degraded"))
    assert no is False and "data_quality" in reason


def test_v2_qualifying_types_are_accumulation_archetypes():
    assert "volume_before_news" in V2_QUALIFYING_TYPES
    assert "suspicious_pump_risk" not in V2_QUALIFYING_TYPES


# -- shadow record creation --------------------------------------------------

def test_capture_creates_records_with_both_decisions():
    with tempfile.TemporaryDirectory() as d:
        s = PreNewsShadowV2(path=Path(d) / "shadow.json")
        n = s.capture_from_anomalies([
            _anom(ticker="A", pre_news_suspicion_score=80),
            _anom(ticker="B", pre_news_suspicion_score=11),
        ])
        assert n == 2
        recs = {r.ticker: r for r in s.records}
        assert recs["A"].baseline_would_alert is True
        assert recs["B"].baseline_would_alert is False   # 11 < 75
        assert recs["B"].v2_would_alert is True           # qualifying type
        assert recs["A"].v2_would_alert is True


def test_capture_is_idempotent_per_detection_hour():
    with tempfile.TemporaryDirectory() as d:
        s = PreNewsShadowV2(path=Path(d) / "shadow.json")
        a = _anom(ticker="DUP")
        assert s.capture_from_anomalies([a]) == 1
        assert s.capture_from_anomalies([a]) == 0


def test_capture_persists_and_reloads():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "shadow.json"
        s1 = PreNewsShadowV2(path=p)
        s1.capture_from_anomalies([_anom(ticker="P")])
        assert p.exists()
        s2 = PreNewsShadowV2(path=p)
        assert len(s2.records) == 1


# -- outcome resolver --------------------------------------------------------

def test_resolver_fills_excursion_fields():
    with tempfile.TemporaryDirectory() as d:
        s = PreNewsShadowV2(path=Path(d) / "shadow.json")
        det = datetime.now(timezone.utc) - timedelta(hours=3)
        s.capture_from_anomalies([_anom(ticker="X", price=1.0, detected_at=det.isoformat())])
        r = s.records[0]
        bars = {
            "intraday": [
                (det + timedelta(minutes=5), 1.10, 1.00, 1.05),
                (det + timedelta(minutes=30), 1.30, 1.05, 1.25),
                (det + timedelta(minutes=55), 1.28, 0.95, 1.00),
            ],
            "daily": [],
        }
        ok = s.resolve_record(r, bars)
        assert ok is True
        assert r.resolved is True
        assert r.mfe_60m == pytest.approx(30.0, abs=0.1)
        assert r.hit_20 is True
        assert r.hit_50 is False
        assert r.hit_100 is False
        assert r.mae_60m < 0


def test_resolver_sets_all_required_outcome_fields():
    required = [
        "price_15m", "price_60m", "session_high", "session_low",
        "two_day_high", "two_day_low", "mfe_15m", "mfe_60m", "mfe_session",
        "mfe_2d", "mae_15m", "mae_60m", "mae_session", "mae_2d",
        "hit_20", "hit_50", "hit_100", "hit_300", "hit_1000",
        "next_day_continuation", "became_trap",
    ]
    fields = set(ShadowRecord.__dataclass_fields__.keys())
    for f in required:
        assert f in fields, "resolver field missing: %s" % f


def test_resolver_returns_false_when_no_bars():
    with tempfile.TemporaryDirectory() as d:
        s = PreNewsShadowV2(path=Path(d) / "shadow.json")
        det = datetime.now(timezone.utc) - timedelta(hours=3)
        s.capture_from_anomalies([_anom(ticker="NB", detected_at=det.isoformat())])
        assert s.resolve_record(s.records[0], {"intraday": [], "daily": []}) is False
        assert s.records[0].resolved is False


# -- report generation -------------------------------------------------------

def test_report_builds_from_records():
    from scripts import pre_news_shadow_v2_report as rep
    recs = [
        {"ticker": "A", "detection_time": datetime.now(timezone.utc).isoformat(),
         "anomaly_type": "volume_before_news", "suspicion_score": 80,
         "baseline_would_alert": True, "v2_would_alert": True, "resolved": True,
         "mfe_60m": 25.0, "mae_60m": -5.0, "hit_20": True, "hit_50": False,
         "hit_100": False, "became_trap": False},
        {"ticker": "B", "detection_time": datetime.now(timezone.utc).isoformat(),
         "anomaly_type": "unusual_volume_no_news", "suspicion_score": 11,
         "baseline_would_alert": False, "v2_would_alert": True, "resolved": True,
         "mfe_60m": 5.0, "mae_60m": -2.0, "hit_20": False, "hit_50": False,
         "hit_100": False, "became_trap": False},
    ]
    text, summary = rep.build(recs)
    assert "BASELINE" in text and "V2_SHADOW" in text
    assert summary["base"]["n_all"] == 1
    assert summary["v2"]["n_all"] == 2


# -- NO production behavior changed ------------------------------------------

def test_shadow_module_never_imports_alert_senders():
    src = Path("src/core/agentic/pre_news_shadow_v2.py").read_text()
    for forbidden in ["send_telegram", "telegram_service", "send_alert", "_send"]:
        assert forbidden not in src, "shadow module must not reference %r" % forbidden


def test_shadow_uses_separate_file_not_production_logs():
    from src.core.agentic.pre_news_shadow_v2 import SHADOW_FILE
    assert SHADOW_FILE.name == "pre_news_shadow_v2.json"
    assert "outcomes" not in SHADOW_FILE.name
    assert "anomalies" not in SHADOW_FILE.name
