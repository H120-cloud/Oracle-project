"""Rocket shadow model status + Railway seeding tests (shadow-mode only)."""

import json

import pytest

import src.core.agentic.rocket_model_shadow as rms
from src.core.agentic.rocket_model_shadow import RocketModelShadowScorer
from src.utils.data_paths import seed_agentic_data_dir

pytestmark = pytest.mark.unit

ROCKET_MODEL = "rocket_catboost_baseline_shadow.joblib"


def _loaded_artifact():
    # Minimal artifact: status() only reads created_at; it never predicts here.
    return {"models": {}, "created_at": "2026-06-03T12:00:00+00:00"}


def test_status_reports_loaded_with_version_and_prediction_stats(tmp_path):
    preds = tmp_path / "preds.jsonl"
    preds.write_text(
        json.dumps({"ticker": "AAA", "logged_at": "2026-06-09T10:00:00+00:00"}) + "\n"
        + json.dumps({"ticker": "BBB", "logged_at": "2026-06-09T11:30:00+00:00"}) + "\n",
        encoding="utf-8",
    )
    scorer = RocketModelShadowScorer(artifact=_loaded_artifact(), predictions_path=preds)

    status = scorer.status()
    assert status["model_loaded"] is True
    assert "2026-06-03" in status["model_version"]
    assert status["last_load_error"] is None
    assert status["prediction_count"] == 2
    assert status["last_prediction_at"] == "2026-06-09T11:30:00+00:00"


def test_status_reports_missing_model_with_clear_reason(tmp_path):
    scorer = RocketModelShadowScorer(model_path=tmp_path / "nope.joblib",
                                     predictions_path=tmp_path / "preds.jsonl")
    status = scorer.status()
    assert status["model_loaded"] is False
    assert "not found" in (status["last_load_error"] or "")
    assert status["prediction_count"] == 0
    assert status["last_prediction_at"] is None


def test_status_surfaces_catboost_load_error(tmp_path, monkeypatch):
    # Model file exists but loading it raises (e.g. catboost not installed).
    model = tmp_path / ROCKET_MODEL
    model.write_bytes(b"not-a-real-joblib")

    def _boom(_path):
        raise ModuleNotFoundError("No module named 'catboost'")

    monkeypatch.setattr(rms.joblib, "load", _boom)
    scorer = RocketModelShadowScorer(model_path=model, predictions_path=tmp_path / "preds.jsonl")

    status = scorer.status()
    assert status["model_loaded"] is False
    assert "catboost" in (status["last_load_error"] or "")


def test_status_reports_disabled(tmp_path):
    scorer = RocketModelShadowScorer(model_path=tmp_path / ROCKET_MODEL,
                                     predictions_path=tmp_path / "preds.jsonl",
                                     enabled=False)
    status = scorer.status()
    assert status["enabled"] is False
    assert status["model_loaded"] is False
    assert "disabled" in (status["last_load_error"] or "")


def test_seed_copies_rocket_model_only_when_absent(tmp_path):
    seed = tmp_path / "seed"
    seed.mkdir()
    (seed / ROCKET_MODEL).write_bytes(b"MODEL-BYTES")
    target = tmp_path / "agentic"

    # Absent on the volume -> seeded from the image.
    seeded = seed_agentic_data_dir(seed_dir=seed, target_dir=target)
    assert ROCKET_MODEL in seeded
    assert (target / ROCKET_MODEL).read_bytes() == b"MODEL-BYTES"

    # A live model on the volume must NEVER be overwritten by the seed.
    (target / ROCKET_MODEL).write_bytes(b"LIVE-MODEL")
    seeded_again = seed_agentic_data_dir(seed_dir=seed, target_dir=target)
    assert ROCKET_MODEL not in seeded_again
    assert (target / ROCKET_MODEL).read_bytes() == b"LIVE-MODEL"
