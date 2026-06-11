"""Rocket shadow scorer improvements: shared artifact cache, monotonic
probabilities, calibration support, weekly time encoding, outcome resolution."""

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

import src.core.agentic.rocket_model_shadow as rms
from src.core.agentic.rocket_model_shadow import (
    RocketModelShadowScorer,
    enforce_monotonic_probabilities,
    resolve_shadow_outcomes,
)


# ── #7: shared artifact cache ────────────────────────────────────────────────

@pytest.mark.unit
def test_artifact_loaded_once_across_instances(tmp_path, monkeypatch):
    model_file = tmp_path / "model.joblib"
    model_file.write_bytes(b"x")  # exists; loading is stubbed
    loads = {"n": 0}

    def _fake_load(path):
        loads["n"] += 1
        return {"models": {}}

    monkeypatch.setattr(rms.joblib, "load", _fake_load)
    rms._ARTIFACT_CACHE.clear()

    s1 = RocketModelShadowScorer(model_path=model_file, predictions_path=tmp_path / "p.jsonl")
    s2 = RocketModelShadowScorer(model_path=model_file, predictions_path=tmp_path / "p.jsonl")
    assert s1.artifact is not None
    assert s2.artifact is not None
    assert loads["n"] == 1, "second instance must reuse the cached artifact"


# ── #5: nested-tier monotonicity ─────────────────────────────────────────────

@pytest.mark.unit
def test_enforce_monotonic_probabilities():
    # P(>=10%) >= P(>=30%) >= P(>=100%) — tiers are nested.
    r, m, mo = enforce_monotonic_probabilities(0.2, 0.5, 0.7)
    assert r >= m >= mo
    # already consistent → unchanged
    assert enforce_monotonic_probabilities(0.8, 0.5, 0.1) == (0.8, 0.5, 0.1)


# ── #3: calibrator application + price_at_alert in record ────────────────────

class _StubModel:
    def predict_proba(self, X):
        return [[0.2, 0.8]]


@pytest.mark.unit
def test_predict_applies_calibrators_and_logs_price(tmp_path):
    calibrator = SimpleNamespace(predict=lambda xs: [0.30])
    artifact = {
        "models": {t: _StubModel() for t in rms._TARGETS},
        "feature_columns": ["price_at_alert", "ticker"],
        "categorical_columns": ["ticker"],
        "calibrators": {t: calibrator for t in rms._TARGETS},
    }
    scorer = RocketModelShadowScorer(
        model_path=tmp_path / "missing.joblib",
        predictions_path=tmp_path / "p.jsonl",
        artifact=artifact,
    )
    cand = SimpleNamespace(ticker="AAA", detected_at=None, current_price=4.2)
    record = scorer.predict_candidate(cand, source_pipeline="news_momentum")
    assert record is not None
    assert record["binary_runner_probability"] == pytest.approx(0.30)
    assert record["price_at_alert"] == pytest.approx(4.2)


# ── #2: weekly time encoding (artifact-gated) ────────────────────────────────

@pytest.mark.unit
def test_prepare_features_weekly_encoding(tmp_path):
    artifact = {
        "feature_columns": ["alert_time", "ticker"],
        "categorical_columns": ["ticker"],
        "alert_time_encoding": "weekly_v2",
    }
    scorer = RocketModelShadowScorer(
        model_path=tmp_path / "missing.joblib",
        predictions_path=tmp_path / "p.jsonl",
        artifact=artifact,
    )
    # Wednesday 2026-06-10 14:00 UTC → dow=2, hour=14 → 2*24+14 = 62
    feats = scorer._prepare_features({"alert_time": "2026-06-10T14:00:00+00:00", "ticker": "AAA"})
    assert float(feats["alert_time"].iloc[0]) == 62.0
    # missing timestamp → -1 sentinel, not int64-min garbage
    feats2 = scorer._prepare_features({"alert_time": None, "ticker": "AAA"})
    assert float(feats2["alert_time"].iloc[0]) == -1.0


# ── #1: outcome resolution (the scoreboard) ──────────────────────────────────

def _bar(day, high):
    return SimpleNamespace(
        timestamp=datetime(2026, 6, day, 20, 0, tzinfo=timezone.utc),
        high=high, low=1.0, open=1.0, close=1.0, volume=1000,
    )


class _Provider:
    def get_ohlcv(self, ticker, **kwargs):
        # alert price 10.0 → day2 high 14 (+40% within 2d), day5 high 25 (+150%)
        return [_bar(2, 11.0), _bar(3, 14.0), _bar(4, 12.0), _bar(5, 13.0), _bar(8, 25.0)]


@pytest.mark.unit
def test_resolve_shadow_outcomes_stamps_forward_returns(tmp_path):
    path = tmp_path / "preds.jsonl"
    logged = datetime(2026, 6, 1, 14, 0, tzinfo=timezone.utc)
    rows = [{
        "ticker": "AAA",
        "price_at_alert": 10.0,
        "logged_at": logged.isoformat(),
        "binary_major_plus_probability": 0.9,
    }]
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")

    stats = resolve_shadow_outcomes(
        provider=_Provider(), path=path,
        now=datetime(2026, 6, 10, 14, 0, tzinfo=timezone.utc),
    )

    assert stats["resolved"] == 1
    out = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()][0]
    assert out["outcome_resolved"] is True
    assert out["fwd_high_2d_pct"] == pytest.approx(40.0)
    assert out["fwd_high_5d_pct"] == pytest.approx(150.0)
    assert out["realized_runner"] is True      # >=10% within 5d
    assert out["realized_major"] is True       # >=30% within 2d
    assert out["realized_monster"] is True     # >=100% within 5d


@pytest.mark.unit
def test_resolve_skips_rows_too_young(tmp_path):
    path = tmp_path / "preds.jsonl"
    logged = datetime(2026, 6, 9, 14, 0, tzinfo=timezone.utc)
    path.write_text(json.dumps({
        "ticker": "AAA", "price_at_alert": 10.0, "logged_at": logged.isoformat(),
    }) + "\n", encoding="utf-8")

    stats = resolve_shadow_outcomes(
        provider=_Provider(), path=path,
        now=datetime(2026, 6, 10, 14, 0, tzinfo=timezone.utc),
    )
    assert stats["resolved"] == 0
    out = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()][0]
    assert "outcome_resolved" not in out or not out["outcome_resolved"]
