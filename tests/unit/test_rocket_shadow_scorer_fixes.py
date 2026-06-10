"""Rocket shadow scorer: train/live feature parity + bounded predictions log."""

import json
from types import SimpleNamespace

import pytest

from src.core.agentic.rocket_model_shadow import (
    RocketModelShadowScorer,
    build_shadow_feature_row,
)


@pytest.mark.unit
def test_news_branch_catalyst_type_matches_training_semantics():
    """Training rows store the SUBTYPE in catalyst_type (orchestrator sets
    catalyst_type=c.catalyst_sub_type). The live row must do the same — feeding
    the category gives the model unseen values for its key categorical."""
    cand = SimpleNamespace(
        ticker="AAA",
        detected_at=None,
        catalyst_category=SimpleNamespace(value="ai_tech"),
        catalyst_sub_type=SimpleNamespace(value="ai_partnership"),
    )
    row = build_shadow_feature_row(cand, source_pipeline="news_momentum")
    assert row["catalyst_type"] == "ai_partnership"
    assert row["catalyst_subtype"] == "ai_partnership"
    assert row["catalyst_category"] == "ai_tech"


@pytest.mark.unit
def test_append_prediction_compacts_oversized_file(tmp_path):
    path = tmp_path / "preds.jsonl"
    scorer = RocketModelShadowScorer(
        model_path=tmp_path / "missing.joblib",
        predictions_path=path,
        max_predictions_bytes=2000,
    )
    for i in range(100):
        scorer.append_prediction({"ticker": f"T{i}", "logged_at": f"2026-06-10T12:{i % 60:02d}:00"})

    assert path.stat().st_size <= 4000, "predictions file must stay bounded"
    lines = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    # newest records survive compaction
    assert lines[-1]["ticker"] == "T99"
