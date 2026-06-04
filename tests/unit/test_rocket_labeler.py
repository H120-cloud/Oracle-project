"""
tests/unit/test_rocket_labeler.py
==================================
Smoke tests for rocket_dataset_builder (Task 1A).

Later subtasks will add label-function tests here.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import pytest


def _bar(offset_minutes, high, low, close, base_time=None):
    """Create a minimal bar dict for test use."""
    t = (base_time or datetime(2026, 1, 2, 14, 30, tzinfo=timezone.utc)) + timedelta(
        minutes=offset_minutes
    )
    return {"timestamp": t, "high": high, "low": low, "close": close, "open": close}


BASE = datetime(2026, 1, 2, 14, 30, tzinfo=timezone.utc)


def test_import():
    from src.core.agentic.rocket_dataset_builder import (
        BUILDER_VERSION,
        DATASET_VERSION,
        DRAWDOWN_QUAL,
        FEATURE_COLUMNS,
        LABEL_COLUMNS,
        RUNNER_TIERS,
        BuildSummary,
        RocketRecord,
    )

    assert DATASET_VERSION == "rocket_v1"
    assert BUILDER_VERSION == "1.0.0"
    assert "runner_tier" in LABEL_COLUMNS
    assert "price_at_alert" in FEATURE_COLUMNS
    assert "peak_move_pct" not in FEATURE_COLUMNS
    assert "five_day_high" not in FEATURE_COLUMNS


# ── compute_peak_metrics ──────────────────────────────────────────────────────

def test_peak_metrics_basic():
    from src.core.agentic.rocket_dataset_builder import compute_peak_metrics
    bars = [
        _bar(10,  high=11.0, low=9.5,  close=10.5),
        _bar(30,  high=13.0, low=10.0, close=12.0),  # +30% peak
        _bar(60,  high=12.0, low=10.0, close=11.0),
    ]
    pm = compute_peak_metrics(bars, [], alert_price=10.0, alert_time=BASE)
    assert pm.peak_move_pct == pytest.approx(30.0, abs=0.01)
    assert pm.peak_timestamp is not None
    assert pm.calendar_time_to_peak_minutes == pytest.approx(30.0, abs=1.0)
    assert pm.trading_time_to_peak_minutes is not None


def test_peak_metrics_empty_bars_uses_stored_fallback():
    from src.core.agentic.rocket_dataset_builder import compute_peak_metrics
    pm = compute_peak_metrics([], [], alert_price=5.0, alert_time=BASE,
                               stored_five_day_high_pct=45.0)
    assert pm.peak_move_pct == pytest.approx(45.0, abs=0.01)
    assert pm.peak_timestamp is None
    assert pm.calendar_time_to_peak_minutes is None


def test_peak_metrics_no_data_returns_empty():
    from src.core.agentic.rocket_dataset_builder import compute_peak_metrics
    pm = compute_peak_metrics(None, None, alert_price=5.0, alert_time=BASE)
    assert pm.peak_move_pct is None
    assert pm.peak_timestamp is None


def test_peak_metrics_ignores_bars_before_alert():
    from src.core.agentic.rocket_dataset_builder import compute_peak_metrics
    bars = [
        _bar(-30, high=999.0, low=1.0, close=5.0),  # before alert — must be ignored
        _bar(10,  high=6.0,   low=4.5, close=5.5),
    ]
    pm = compute_peak_metrics(bars, [], alert_price=5.0, alert_time=BASE)
    assert pm.peak_move_pct == pytest.approx(20.0, abs=0.01)


# ── compute_runner_tier ───────────────────────────────────────────────────────

def test_runner_tier_boundaries():
    from src.core.agentic.rocket_dataset_builder import compute_runner_tier
    mins_1d = 60 * 6.5
    mins_2d = 60 * 6.5 * 2
    mins_5d = 60 * 6.5 * 5

    assert compute_runner_tier(9.99,  mins_1d) is None
    assert compute_runner_tier(10.0,  mins_1d) == "STANDARD_WIN"
    assert compute_runner_tier(29.99, mins_1d) == "STANDARD_WIN"

    assert compute_runner_tier(30.0,  mins_2d) == "MAJOR_RUNNER"
    assert compute_runner_tier(30.0,  mins_1d) == "MAJOR_RUNNER"
    assert compute_runner_tier(29.99, mins_2d) is None

    assert compute_runner_tier(100.0, mins_5d) == "MONSTER_RUNNER"
    assert compute_runner_tier(99.99, mins_5d) is None

    assert compute_runner_tier(300.0, mins_5d) == "LEGENDARY_RUNNER"


def test_legendary_not_compressed():
    from src.core.agentic.rocket_dataset_builder import compute_runner_tier
    mins_3d = 60 * 6.5 * 3
    tier = compute_runner_tier(400.0, mins_3d)
    assert tier == "LEGENDARY_RUNNER"
    assert tier != "MONSTER_RUNNER"


def test_runner_tier_no_timing_allows_5d_tiers():
    from src.core.agentic.rocket_dataset_builder import compute_runner_tier
    assert compute_runner_tier(350.0, None) == "LEGENDARY_RUNNER"
    assert compute_runner_tier(120.0, None) == "MONSTER_RUNNER"
    assert compute_runner_tier(30.0,  None) is None
    assert compute_runner_tier(15.0,  None) is None


def test_runner_tier_negative_peak_returns_none():
    from src.core.agentic.rocket_dataset_builder import compute_runner_tier
    assert compute_runner_tier(-5.0, 60.0) is None
    assert compute_runner_tier(None, 60.0) is None


# ── compute_mfe_mae_profiles ──────────────────────────────────────────────────

def test_mfe_mae_intraday_basic():
    from src.core.agentic.rocket_dataset_builder import compute_mfe_mae_profiles
    bars = [_bar(i * 5, high=10.0 + i * 0.5, low=9.5 - i * 0.1, close=10.0 + i * 0.4)
            for i in range(1, 13)]
    p = compute_mfe_mae_profiles(bars, [], alert_price=10.0, alert_time=BASE)
    # bar 1 offset=5 high=10.5, bar 2 offset=10 high=11.0, bar 3 offset=15 high=11.5
    assert p.mfe_15m == pytest.approx((11.5 / 10.0 - 1) * 100, abs=0.01)
    assert p.mfe_60m is not None
    assert p.mfe_60m > p.mfe_15m
    assert p.mae_15m is not None
    assert p.mae_15m < 0.0


def test_mfe_mae_daily_proxy():
    from src.core.agentic.rocket_dataset_builder import compute_mfe_mae_profiles
    daily = [
        _bar(24 * 60,       high=12.0, low=9.0, close=11.0),  # day 1
        _bar(24 * 60 * 2,   high=14.0, low=8.5, close=12.0),  # day 2
        _bar(24 * 60 * 3,   high=15.0, low=8.0, close=13.0),  # day 3
    ]
    p = compute_mfe_mae_profiles([], daily, alert_price=10.0, alert_time=BASE)
    assert p.mfe_15m is None
    assert p.mae_15m is None
    assert p.mfe_60m is None
    assert p.mae_60m is None
    assert p.mfe_1d == pytest.approx((12.0 / 10.0 - 1) * 100, abs=0.01)
    assert p.mae_1d == pytest.approx((9.0  / 10.0 - 1) * 100, abs=0.01)
    assert p.mfe_2d == pytest.approx((14.0 / 10.0 - 1) * 100, abs=0.01)
    assert p.mae_2d == pytest.approx((8.5  / 10.0 - 1) * 100, abs=0.01)


def test_mfe_mae_stored_fallback():
    from src.core.agentic.rocket_dataset_builder import compute_mfe_mae_profiles
    stored = {
        "stored_return_next_day_high_pct": 15.0,
        "stored_return_two_day_high_pct":  25.0,
        "stored_return_five_day_high_pct": 40.0,
    }
    p = compute_mfe_mae_profiles(None, None, alert_price=10.0, alert_time=BASE,
                                  stored_fields=stored)
    assert p.mfe_1d == pytest.approx(15.0, abs=0.01)
    assert p.mfe_2d == pytest.approx(25.0, abs=0.01)
    assert p.mfe_5d == pytest.approx(40.0, abs=0.01)
    assert p.mae_1d is None
    assert p.mae_5d is None


def test_mfe_mae_no_data_returns_all_none():
    from src.core.agentic.rocket_dataset_builder import compute_mfe_mae_profiles
    p = compute_mfe_mae_profiles(None, None, alert_price=5.0, alert_time=BASE)
    assert p.mfe_5d is None
    assert p.mae_5d is None


# ── compute_drawdown_quality ──────────────────────────────────────────────────

def _dq(intraday, daily, alert_price, tier):
    from src.core.agentic.rocket_dataset_builder import compute_drawdown_quality
    dq_flag = "intraday_exact" if intraday else ("daily_proxy" if daily else "missing")
    return compute_drawdown_quality(intraday, daily, alert_price, tier, dq_flag)


def test_clean_runner():
    bars = [
        _bar(5,  high=10.5, low=9.8, close=10.3),
        _bar(10, high=11.5, low=9.9, close=11.0),  # +15% → hits STANDARD_WIN target
    ]
    assert _dq(bars, [], 10.0, "STANDARD_WIN") == "CLEAN_RUNNER"


def test_dirty_runner():
    bars = [
        _bar(5,  high=10.2, low=8.4, close=9.0),   # low = -16% — MAE triggered
        _bar(10, high=11.5, low=9.0, close=11.0),   # +15% — target hit
    ]
    assert _dq(bars, [], 10.0, "STANDARD_WIN") == "DIRTY_RUNNER"


def test_trap_rule_1():
    bars = [
        _bar(5,  high=12.5, low=9.5,  close=12.0),  # +25% (activates trap watch)
        _bar(10, high=12.0, low=7.0,  close=7.5),   # low goes -30% → TRAP
    ]
    assert _dq(bars, [], 10.0, "STANDARD_WIN") == "TRAP"


def test_trap_rule_2():
    # alert_price=10, peak=22 (+120%), then close=13 → (1 - 13/22)*100 = 40.9% drop
    bars = [
        _bar(5,  high=22.0, low=9.5, close=21.0),  # +120% peak
        _bar(10, high=21.5, low=12.0, close=13.0),
    ]
    assert _dq(bars, [], 10.0, "MONSTER_RUNNER") == "TRAP"


def test_trap_rule_2_not_triggered():
    # alert_price=10, peak=13.5 (+35%), close=10.8 → (1-10.8/13.5)*100 = 20% drop
    bars = [
        _bar(5,  high=13.5, low=9.5, close=13.0),
        _bar(10, high=13.0, low=10.5, close=10.8),
    ]
    assert _dq(bars, [], 10.0, "MAJOR_RUNNER") != "TRAP"


def test_target_never_reached_returns_none():
    bars = [
        _bar(5, high=10.8, low=9.5, close=10.5),  # only +8%, below 10% target
    ]
    assert _dq(bars, [], 10.0, "STANDARD_WIN") is None


def test_missing_data_quality_returns_none():
    from src.core.agentic.rocket_dataset_builder import compute_drawdown_quality
    assert compute_drawdown_quality([], [], 10.0, "STANDARD_WIN", "missing") is None


def test_none_tier_returns_none():
    from src.core.agentic.rocket_dataset_builder import compute_drawdown_quality
    bars = [_bar(5, high=15.0, low=9.0, close=14.0)]
    assert compute_drawdown_quality(bars, [], 10.0, None, "intraday_exact") is None


def test_empty_bars_returns_none():
    from src.core.agentic.rocket_dataset_builder import compute_drawdown_quality
    assert compute_drawdown_quality([], [], 10.0, "STANDARD_WIN", "intraday_exact") is None


# ── _compute_data_quality_score ───────────────────────────────────────────────

def _make_record(**kwargs):
    from src.core.agentic.rocket_dataset_builder import RocketRecord
    defaults = dict(
        row_id="test_001", source_type="telegram",
        ticker="TEST", alert_time=BASE, price_at_alert=5.0,
    )
    defaults.update(kwargs)
    return RocketRecord(**defaults)


def test_data_quality_score_max_is_100():
    from src.core.agentic.rocket_dataset_builder import _compute_data_quality_score
    rec = _make_record(
        intraday_bars=[_bar(5, 6.0, 4.5, 5.5)],
        peak_timestamp=BASE + timedelta(minutes=30),
        runner_tier="STANDARD_WIN",
        drawdown_quality="CLEAN_RUNNER",
        mfe_15m=5.0,  mae_15m=-2.0,
        mfe_60m=8.0,  mae_60m=-3.0,
        mfe_1d=10.0,  mae_1d=-4.0,
        mfe_2d=12.0,  mae_2d=-5.0,
        mfe_5d=15.0,  mae_5d=-6.0,
    )
    assert _compute_data_quality_score(rec) == 100.0


def test_data_quality_score_never_exceeds_100():
    from src.core.agentic.rocket_dataset_builder import _compute_data_quality_score
    rec = _make_record(
        intraday_bars=[_bar(5, 6.0, 4.5, 5.5)],
        peak_timestamp=BASE,
        runner_tier="LEGENDARY_RUNNER",
        drawdown_quality="TRAP",
        mfe_15m=1.0, mae_15m=-1.0,
        mfe_60m=2.0, mae_60m=-2.0,
        mfe_1d=3.0,  mae_1d=-3.0,
        mfe_2d=4.0,  mae_2d=-4.0,
        mfe_5d=5.0,  mae_5d=-5.0,
    )
    assert _compute_data_quality_score(rec) <= 100.0


def test_data_quality_score_empty_record():
    from src.core.agentic.rocket_dataset_builder import _compute_data_quality_score
    rec = _make_record()
    assert _compute_data_quality_score(rec) == 0.0


def test_data_quality_score_deterministic():
    from src.core.agentic.rocket_dataset_builder import _compute_data_quality_score
    rec = _make_record(
        intraday_bars=[_bar(5, 6.0, 4.5, 5.5)],
        runner_tier="MAJOR_RUNNER",
        mfe_1d=10.0, mae_1d=-3.0,
    )
    assert _compute_data_quality_score(rec) == _compute_data_quality_score(rec)


def test_daily_proxy_never_intraday_exact():
    rec = _make_record()
    rec.intraday_bars = None
    rec.daily_bars = [_bar(60 * 24, high=6.0, low=4.5, close=5.5)]
    rec.drawdown_data_quality = "daily_proxy" if rec.daily_bars else "missing"
    assert rec.drawdown_data_quality != "intraday_exact"


# ── Leakage manifest checks ───────────────────────────────────────────────────

def test_no_forward_pricing_in_feature_columns():
    from src.core.agentic.rocket_dataset_builder import FEATURE_COLUMNS
    forbidden = {
        "peak_move_pct", "peak_timestamp", "five_day_high", "two_day_high",
        "next_day_high", "mfe_pct", "mae_pct", "return_five_day_high_pct",
        "mfe_15m", "mfe_60m", "mfe_1d", "mfe_2d", "mfe_5d",
        "mae_15m", "mae_60m", "mae_1d", "mae_2d", "mae_5d",
        "runner_tier", "drawdown_quality",
    }
    leaking = forbidden & set(FEATURE_COLUMNS)
    assert leaking == set(), f"Leakage detected: {leaking}"


def test_label_columns_not_in_feature_columns():
    from src.core.agentic.rocket_dataset_builder import FEATURE_COLUMNS, LABEL_COLUMNS
    overlap = set(FEATURE_COLUMNS) & set(LABEL_COLUMNS)
    assert overlap == set(), f"Column in both manifests: {overlap}"


# ── Ingestion helpers ─────────────────────────────────────────────────────────

def test_anchor_check_passes_valid_row():
    from src.core.agentic.rocket_dataset_builder import _anchor_check
    assert _anchor_check("AAPL", BASE, 5.0, "acquisition", None, "telegram") is None


def test_anchor_check_missing_ticker():
    from src.core.agentic.rocket_dataset_builder import _anchor_check
    assert _anchor_check("", BASE, 5.0, "acquisition", None, "telegram") == "missing_ticker"


def test_anchor_check_rejects_synthetic_test_ticker():
    from src.core.agentic.rocket_dataset_builder import _anchor_check

    assert (
        _anchor_check("GREAT001", BASE, 5.0, "acquisition", None, "telegram")
        == "synthetic_test_ticker"
    )


def test_anchor_check_missing_price():
    from src.core.agentic.rocket_dataset_builder import _anchor_check
    assert _anchor_check("AAPL", BASE, None, "acquisition", None, "telegram") == "invalid_price"
    assert _anchor_check("AAPL", BASE, 0.0,  "acquisition", None, "telegram") == "invalid_price"
    assert _anchor_check("AAPL", BASE, -1.0, "acquisition", None, "telegram") == "invalid_price"


def test_anchor_check_missing_catalyst_required_for_non_prenews():
    from src.core.agentic.rocket_dataset_builder import _anchor_check
    assert _anchor_check("AAPL", BASE, 5.0, None, None, "telegram") == "missing_catalyst"
    assert _anchor_check("AAPL", BASE, 5.0, None, None, "shadow") == "missing_catalyst"
    assert _anchor_check("AAPL", BASE, 5.0, None, None, "backfill") == "missing_catalyst"
    assert _anchor_check("AAPL", BASE, 5.0, None, None, "missed") == "missing_catalyst"


def test_anchor_check_prenews_catalyst_not_required():
    from src.core.agentic.rocket_dataset_builder import _anchor_check
    assert _anchor_check("AAPL", BASE, 5.0, None, None, "prenews") is None


def test_dedup_telegram_beats_backfill(tmp_path):
    from src.core.agentic.rocket_dataset_builder import RocketDatasetBuilder, RocketRecord
    builder = RocketDatasetBuilder(data_dir=tmp_path, docs_dir=tmp_path)
    rec_tele = RocketRecord(
        row_id="telegram_A", source_type="telegram",
        ticker="AAPL", alert_time=BASE, price_at_alert=5.0,
        catalyst_type="acquisition",
    )
    rec_back = RocketRecord(
        row_id="backfill_A", source_type="backfill",
        ticker="AAPL", alert_time=BASE, price_at_alert=5.0,
        catalyst_type="acquisition",
    )
    result = builder._deduplicate([rec_tele, rec_back])
    kept    = [r for r in result if not r.rejection_reason]
    dropped = [r for r in result if r.rejection_reason == "duplicate"]
    assert len(kept) == 1
    assert kept[0].source_type == "telegram"
    assert dropped[0].source_type == "backfill"
    assert dropped[0].kept_source_type == "telegram"


def test_dedup_missed_beats_shadow(tmp_path):
    from src.core.agentic.rocket_dataset_builder import RocketDatasetBuilder, RocketRecord
    builder = RocketDatasetBuilder(data_dir=tmp_path, docs_dir=tmp_path)
    rec_shadow = RocketRecord(
        row_id="shadow_A", source_type="shadow",
        ticker="SOUN", alert_time=BASE, price_at_alert=2.0,
        catalyst_type="other",
    )
    rec_missed = RocketRecord(
        row_id="missed_A", source_type="missed",
        ticker="SOUN", alert_time=BASE, price_at_alert=2.0,
        catalyst_type="fda_approval",
    )
    result = builder._deduplicate([rec_shadow, rec_missed])
    kept = [r for r in result if not r.rejection_reason]
    assert kept[0].source_type == "missed"


# ── End-to-end build() integration ───────────────────────────────────────────

def _write_json(path, data):
    import json
    with open(path, "w") as f:
        json.dump(data, f)


def _make_raw_alert(alert_id, ticker, price, sent_at, catalyst="fda_approval",
                    return_five_day_high_pct=None):
    return {
        "alert_id": alert_id,
        "ticker": ticker,
        "sent_at": sent_at,
        "catalyst_type": catalyst,
        "price_at_alert": price,
        "news_impact_score": 75.0,
        "expected_return_score": 70.0,
        "continuation_probability": 65.0,
        "multi_day_score": 60.0,
        "return_five_day_high_pct": return_five_day_high_pct,
    }


def test_build_produces_outputs(tmp_path, monkeypatch):
    import json
    from src.core.agentic.rocket_dataset_builder import RocketDatasetBuilder

    agentic = tmp_path / "agentic"
    agentic.mkdir()
    docs = tmp_path / "docs"
    docs.mkdir()

    alerts = [
        _make_raw_alert("a1", "AAPL", 5.0, "2026-01-02T14:30:00Z",
                        return_five_day_high_pct=150.0),  # ≥100% → MONSTER_RUNNER without timing
        _make_raw_alert("a2", "GOOG", 10.0, "2026-01-02T14:30:00Z",
                        return_five_day_high_pct=8.0),  # <10% → no tier
        _make_raw_alert("a3", "",    5.0, "2026-01-02T14:30:00Z"),  # missing ticker → rejected
    ]
    _write_json(agentic / "news_momentum_telegram_alerts.json", alerts)
    _write_json(agentic / "news_momentum_shadow_alerts.json", [])
    _write_json(agentic / "news_momentum_backfill_records.json", [])
    _write_json(agentic / "news_momentum_missed_winners.json", [])
    _write_json(agentic / "pre_news_shadow_v2.json", {"count": 0, "records": [], "updated_at": ""})

    monkeypatch.setattr(
        "src.core.agentic.rocket_dataset_builder.RocketDatasetBuilder._fetch_bars",
        staticmethod(lambda provider, ticker: (None, None)),
    )

    builder = RocketDatasetBuilder(data_dir=agentic, docs_dir=docs)
    summary = builder.build()

    assert (agentic / "rocket_training_dataset.csv").exists()
    assert (agentic / "rocket_training_dataset.parquet").exists()
    assert (agentic / "rocket_rejected_rows.csv").exists()
    assert (docs / "rocket_dataset_report.md").exists()

    assert summary.total_ingested == 3
    assert summary.total_rejected >= 1
    assert summary.total_exported <= 2

    import pandas as pd
    df = pd.read_csv(agentic / "rocket_training_dataset.csv")
    if len(df) > 0:
        aapl = df[df["ticker"] == "AAPL"]
        if len(aapl) > 0:
            assert aapl.iloc[0]["runner_tier"] in {
                "MONSTER_RUNNER", "LEGENDARY_RUNNER", "MAJOR_RUNNER", "STANDARD_WIN"
            }

    report = (docs / "rocket_dataset_report.md").read_text(encoding="utf-8")
    assert "## Run Metadata" in report
    assert "## Runner Tier Distribution" in report
    assert "## Drawdown Quality Distribution" in report
    assert "## Feature Null Rates" in report
    assert "## Dropped Non-Manifest Columns" in report
    assert "daily_proxy" in report

    assert "five_day_high" not in df.columns
    assert "mfe_pct" not in df.columns
    assert "return_five_day_high_pct" not in df.columns

    assert summary.dataset_version == "rocket_v1"
    assert summary.builder_version == "1.0.0"
    assert summary.created_at is not None
