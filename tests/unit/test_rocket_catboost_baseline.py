from __future__ import annotations

import pandas as pd

from src.core.agentic.rocket_catboost_baseline import (
    build_targets,
    metric_block,
    prepare_features,
    rule_score_benchmarks,
    time_based_split,
)
from src.core.agentic.rocket_dataset_builder import FEATURE_COLUMNS, LABEL_COLUMNS


def test_build_targets_maps_requested_classes():
    labels = pd.Series(
        [
            "NON_RUNNER",
            "STANDARD_WIN",
            "MAJOR_RUNNER",
            "MONSTER_RUNNER",
            "LEGENDARY_RUNNER",
        ]
    )

    targets = build_targets(labels)

    assert targets["binary_runner"].tolist() == [0, 1, 1, 1, 1]
    assert targets["binary_major_plus"].tolist() == [0, 0, 1, 1, 1]
    assert targets["binary_monster_plus"].tolist() == [0, 0, 0, 1, 1]


def test_time_based_split_uses_older_rows_for_train():
    df = pd.DataFrame(
        {
            "_alert_dt": pd.to_datetime(
                ["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04", "2026-01-05"],
                utc=True,
            ),
            "ticker": ["A", "B", "C", "D", "E"],
            "row_id": ["1", "2", "3", "4", "5"],
        }
    )

    split = time_based_split(df, test_fraction=0.4)

    assert split.train["ticker"].tolist() == ["A", "B", "C"]
    assert split.test["ticker"].tolist() == ["D", "E"]
    assert split.train["_alert_dt"].max() < split.test["_alert_dt"].min()


def test_prepare_features_uses_feature_columns_only():
    row = {column: None for column in FEATURE_COLUMNS}
    row.update({"row_id": "r1", "ticker": "AAPL", "alert_time": "2026-01-01T12:00:00Z"})
    for column in LABEL_COLUMNS:
        row[column] = "leak"
    df = pd.DataFrame([row])

    features, categorical_columns, _ = prepare_features(df)

    assert list(features.columns) == FEATURE_COLUMNS
    assert not set(LABEL_COLUMNS) & set(features.columns)
    assert "ticker" in categorical_columns
    # weekly_v2 encoding: dow*24 + hour (2026-01-01 is a Thursday, 12:00 → 84)
    assert pd.api.types.is_float_dtype(features["alert_time"])
    assert float(features["alert_time"].iloc[0]) == 84.0


def test_metric_block_reports_top_decile_lift():
    metrics = metric_block([0, 0, 0, 1, 1], [0.1, 0.2, 0.3, 0.8, 0.9])

    assert metrics["auc"] == 1.0
    assert metrics["top_decile_hit_rate"] == 1.0
    assert metrics["lift_over_baseline"] == 2.5


def test_rule_score_benchmarks_uses_available_at_alert_scores():
    df = pd.DataFrame(
        {
            "expected_return_score": list(range(10)),
            "news_impact_score": list(reversed(range(10))),
        }
    )
    targets = {"binary_runner": pd.Series([0, 0, 0, 0, 0, 1, 1, 1, 1, 1])}

    benchmark = rule_score_benchmarks(df, targets)

    assert benchmark["binary_runner"]["best"]["score"] == "expected_return_score"
    assert benchmark["binary_runner"]["best"]["auc"] == 1.0
