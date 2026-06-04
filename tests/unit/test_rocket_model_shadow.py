from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace

from src.core.agentic.rocket_dataset_builder import FEATURE_COLUMNS, LABEL_COLUMNS
from src.core.agentic.rocket_model_shadow import (
    RocketModelShadowScorer,
    build_shadow_feature_row,
    prediction_confidence,
)
from scripts.rocket_model_shadow_report import summarize_predictions


class _FixedModel:
    def __init__(self, probability: float):
        self.probability = probability

    def predict_proba(self, features):
        return [[1.0 - self.probability, self.probability]]


def _candidate(**overrides):
    base = {
        "id": "cand-1",
        "ticker": "PRFX",
        "headline": "PainReform launches commercial drug program",
        "published_at": datetime(2026, 1, 1, 14, 30, tzinfo=timezone.utc),
        "detected_at": datetime(2026, 1, 1, 14, 31, tzinfo=timezone.utc),
        "session": SimpleNamespace(value="regular"),
        "catalyst_category": SimpleNamespace(value="biotech"),
        "catalyst_sub_type": SimpleNamespace(value="drug_launch"),
        "current_price": 1.25,
        "move_pct": 2.9,
        "volume": 1_250_000,
        "rvol": 8.4,
        "spread_pct": 0.7,
        "trap_risk": 12.0,
        "dilution_risk": 9.0,
        "velocity_score": 7.5,
        "sources_seen_count": 2,
        "is_negative": False,
        "is_vague": False,
        "is_delayed_reaction": False,
        "news_impact_score": 72.0,
        "expected_return_score": 64.0,
        "continuation_probability": 58.0,
        "multi_day_continuation_score": 61.0,
        "float_category": SimpleNamespace(value="ultra_low"),
        "market_cap_category": SimpleNamespace(value="micro"),
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _artifact():
    return {
        "models": {
            "binary_runner": _FixedModel(0.72),
            "binary_major_plus": _FixedModel(0.41),
            "binary_monster_plus": _FixedModel(0.18),
        },
        "feature_columns": FEATURE_COLUMNS,
        "categorical_columns": [
            "row_id",
            "source_type",
            "ticker",
            "catalyst_type",
            "catalyst_subtype",
            "catalyst_category",
            "session_type",
            "float_category",
            "market_cap_category",
            "sec_dilution_behavior",
            "sec_oracle_action",
            "dataset_version",
            "builder_version",
        ],
        "created_at": "2026-06-03T12:00:00+00:00",
    }


def test_build_shadow_feature_row_is_leakage_safe_and_maps_live_scores():
    row = build_shadow_feature_row(_candidate(), source_pipeline="news_momentum")

    assert list(row) == FEATURE_COLUMNS
    assert not set(LABEL_COLUMNS) & set(row)
    assert row["source_type"] == "shadow"
    assert row["ticker"] == "PRFX"
    assert row["catalyst_subtype"] == "drug_launch"
    assert row["multi_day_score"] == 61.0
    assert row["expected_return_score"] == 64.0


def test_shadow_scorer_appends_required_prediction_record(tmp_path):
    output = tmp_path / "shadow.jsonl"
    scorer = RocketModelShadowScorer(artifact=_artifact(), predictions_path=output)

    record = scorer.predict_and_log_candidate(_candidate(), source_pipeline="news_momentum")

    assert output.exists()
    line = json.loads(output.read_text(encoding="utf-8").strip())
    assert line["ticker"] == "PRFX"
    assert line["binary_runner_probability"] == 0.72
    assert line["binary_major_plus_probability"] == 0.41
    assert line["binary_monster_plus_probability"] == 0.18
    assert line["rocket_rank_score"] == record["rocket_rank_score"]
    assert line["model_version"] == "rocket_catboost_baseline_shadow:2026-06-03T12:00:00+00:00"
    assert isinstance(line["feature_null_count"], int)
    assert line["prediction_confidence"] in {"HIGH", "MEDIUM", "LOW"}


def test_prediction_confidence_uses_null_count_and_probability_strength():
    assert prediction_confidence(feature_null_count=2, max_probability=0.76) == "HIGH"
    assert prediction_confidence(feature_null_count=12, max_probability=0.44) == "MEDIUM"
    assert prediction_confidence(feature_null_count=25, max_probability=0.81) == "LOW"


def test_report_summarizes_hits_and_rank_disagreements(tmp_path):
    path = tmp_path / "shadow.jsonl"
    rows = [
        {
            "ticker": "AAA",
            "rocket_rank_score": 0.91,
            "binary_major_plus_probability": 0.8,
            "binary_monster_plus_probability": 0.2,
            "expected_return_score": 30,
            "runner_tier": "MAJOR_RUNNER",
        },
        {
            "ticker": "BBB",
            "rocket_rank_score": 0.15,
            "binary_major_plus_probability": 0.1,
            "binary_monster_plus_probability": 0.02,
            "expected_return_score": 90,
            "runner_tier": "NON_RUNNER",
        },
    ]
    path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")

    summary = summarize_predictions(path)

    assert summary["prediction_count"] == 2
    assert summary["resolved_count"] == 2
    assert summary["major_plus_hit_rate"] == 0.5
    assert summary["monster_plus_hit_rate"] == 0.0
    assert summary["catboost_high_rules_low"][0]["ticker"] == "AAA"
    assert summary["rules_high_catboost_low"][0]["ticker"] == "BBB"
