"""Training-side feature prep: weekly time encoding + feature-subset support."""

import pandas as pd
import pytest

from src.core.agentic.rocket_catboost_baseline import prepare_features
from src.core.agentic.rocket_dataset_builder import FEATURE_COLUMNS


def _df():
    row = {c: None for c in FEATURE_COLUMNS}
    row["alert_time"] = "2026-06-10T14:00:00+00:00"  # Wednesday 14:00 → 2*24+14
    row["ticker"] = "AAA"
    row["price_at_alert"] = 5.0
    return pd.DataFrame([row])


@pytest.mark.unit
def test_alert_time_uses_weekly_encoding_not_epoch():
    features, _, _ = prepare_features(_df())
    value = float(features["alert_time"].iloc[0])
    assert value == 62.0, "expected dow*24+hour weekly position, not epoch ns"


@pytest.mark.unit
def test_missing_alert_time_becomes_sentinel_not_garbage():
    df = _df()
    df.loc[0, "alert_time"] = None
    features, _, _ = prepare_features(df)
    assert float(features["alert_time"].iloc[0]) == -1.0


@pytest.mark.unit
def test_prepare_features_supports_feature_subset():
    subset = [c for c in FEATURE_COLUMNS if c != "spread_pct_at_alert"]
    features, _, _ = prepare_features(_df(), feature_columns=subset)
    assert "spread_pct_at_alert" not in features.columns
    assert list(features.columns) == subset
