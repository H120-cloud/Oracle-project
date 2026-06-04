from datetime import datetime, timezone
from types import SimpleNamespace

from src.core.agentic import pre_news_validation as validation


def _value(name):
    return SimpleNamespace(value=name)


def _anomaly(ticker="MRM"):
    return SimpleNamespace(
        ticker=ticker,
        detected_at=datetime(2026, 5, 22, 18, 44, tzinfo=timezone.utc),
        smart_money_score=91.0,
        pre_news_suspicion_score=89.6,
        anomaly_type=_value("quiet_volume_build"),
        timing_stage=_value("early"),
        buy_pressure_score=83.0,
        float_pressure_score=77.0,
        offering_risk_score=10.0,
        move_type_prediction=_value("potential_runner"),
        discovery_source="test",
        session_quality_score=72.0,
        confidence_decay_factor=1.0,
        late_detection_flag=False,
        price=2.31,
    )


def _candidate(price=2.31, alertable=True):
    return SimpleNamespace(
        entry_timing=SimpleNamespace(
            timing_state=_value("ready"),
            entry_zone_low=price * 0.98,
            entry_zone_high=price * 1.02,
            stop_level=price * 0.95,
            target_1=price * 1.15,
            target_2=price * 1.30,
            invalidation_level=price * 0.94,
        ),
        final_probability=89.6,
        alertable=alertable,
        last_price=price,
    )


def test_record_handoff_updates_existing_open_record(monkeypatch, tmp_path):
    monkeypatch.setattr(validation, "DATA_DIR", tmp_path)
    monkeypatch.setattr(validation, "VALIDATION_FILE", tmp_path / "pre_news_validation.json")
    monkeypatch.setattr(validation, "WEEKLY_REPORTS_DIR", tmp_path / "validation_reports")

    tracker = validation.PreNewsValidationTracker()
    anomaly = _anomaly()

    first = tracker.record_handoff(anomaly, _candidate(price=2.31))
    tracker.record_alert(anomaly.ticker)
    second = tracker.record_handoff(anomaly, _candidate(price=2.50, alertable=False))

    assert first.record_id == second.record_id
    assert len(tracker.get_open_records()) == 1
    assert second.last_checked_price == 2.50
    assert second.agentic_alertable is False
    assert second.telegram_alert_sent is True
    assert second.alert_sent_at is not None
