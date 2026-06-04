from __future__ import annotations

import json

import pandas as pd
import pytest


def _row(**overrides):
    row = {
        "row_id": "row-1",
        "runner_tier": None,
        "mfe_1d": None,
        "mfe_2d": None,
        "mfe_5d": None,
    }
    row.update(overrides)
    return row


@pytest.mark.parametrize(
    ("row", "expected"),
    [
        (_row(mfe_1d=10.0, mfe_2d=10.0, mfe_5d=10.0), "STANDARD_WIN"),
        (_row(mfe_1d=10.0, mfe_2d=30.0, mfe_5d=30.0), "MAJOR_RUNNER"),
        (_row(mfe_1d=10.0, mfe_2d=30.0, mfe_5d=100.0), "MONSTER_RUNNER"),
        (_row(mfe_1d=10.0, mfe_2d=30.0, mfe_5d=300.0), "LEGENDARY_RUNNER"),
        (_row(mfe_1d=9.99, mfe_2d=29.99, mfe_5d=99.99), "NON_RUNNER"),
    ],
)
def test_exact_boundaries(row, expected):
    from src.core.agentic.rocket_label_reconstructor import reconstruct_labels

    result = reconstruct_labels(pd.DataFrame([row]))

    assert result.loc[0, "reconstructed_runner_tier"] == expected
    assert result.loc[0, "training_runner_tier"] == expected
    assert result.loc[0, "label_source"] == "reconstructed_exact"
    assert result.loc[0, "label_confidence"] == "HIGH"


@pytest.mark.parametrize(
    ("row", "expected"),
    [
        (_row(mfe_1d=10.0), "PROVISIONAL_STANDARD_WIN"),
        (_row(mfe_2d=30.0), "PROVISIONAL_MAJOR_RUNNER"),
        (_row(mfe_5d=100.0), "PROVISIONAL_MONSTER_RUNNER"),
    ],
)
def test_partial_positive_is_provisional(row, expected):
    from src.core.agentic.rocket_label_reconstructor import reconstruct_labels

    result = reconstruct_labels(pd.DataFrame([row]), include_provisional=True)

    assert result.loc[0, "reconstructed_runner_tier"] == expected
    assert result.loc[0, "label_source"] == "reconstructed_provisional"
    assert result.loc[0, "label_confidence"] == "MEDIUM"


def test_partial_positive_stays_unknown_by_default():
    from src.core.agentic.rocket_label_reconstructor import reconstruct_labels

    result = reconstruct_labels(pd.DataFrame([_row(mfe_1d=10.0)]))

    assert result.loc[0, "reconstructed_runner_tier"] == "UNKNOWN"
    assert result.loc[0, "label_source"] == "insufficient_evidence"
    assert result.loc[0, "label_confidence"] == "LOW"


def test_existing_runner_tier_is_preserved_without_overwriting_raw_column():
    from src.core.agentic.rocket_label_reconstructor import reconstruct_labels

    df = pd.DataFrame([_row(runner_tier="MONSTER_RUNNER")])
    result = reconstruct_labels(df)

    assert result.loc[0, "runner_tier"] == "MONSTER_RUNNER"
    assert result.loc[0, "reconstructed_runner_tier"] == "MONSTER_RUNNER"
    assert result.loc[0, "training_runner_tier"] == "MONSTER_RUNNER"
    assert result.loc[0, "label_source"] == "existing_runner_tier"
    assert result.loc[0, "label_confidence"] == "HIGH"


def test_conflicting_aliases_remain_unknown():
    from src.core.agentic.rocket_label_reconstructor import reconstruct_labels

    df = pd.DataFrame(
        [
            _row(
                mfe_1d=10.0,
                return_next_day_high_pct=30.0,
                mfe_2d=30.0,
                mfe_5d=100.0,
            )
        ]
    )
    result = reconstruct_labels(df)

    assert result.loc[0, "reconstructed_runner_tier"] == "UNKNOWN"
    assert result.loc[0, "label_source"] == "insufficient_evidence"
    assert result.loc[0, "label_reason_code"] == "ambiguous_historical_values"


def test_non_unknown_labels_have_structured_provenance():
    from src.core.agentic.rocket_label_reconstructor import reconstruct_labels

    result = reconstruct_labels(
        pd.DataFrame([_row(mfe_1d=10.0, mfe_2d=30.0, mfe_5d=300.0)])
    )
    provenance = json.loads(result.loc[0, "label_provenance"])

    assert provenance["mapping_rule_id"] == "RLR_EXACT_LEGENDARY_V1"
    assert provenance["reconstruction_version"] == "rocket_labels_v1_no_fetch"
    assert provenance["source_values"]["mfe_5d"] == 300.0


def test_input_dataframe_is_not_mutated():
    from src.core.agentic.rocket_label_reconstructor import reconstruct_labels

    df = pd.DataFrame([_row(mfe_1d=10.0, mfe_2d=10.0, mfe_5d=10.0)])
    original = df.copy(deep=True)

    reconstruct_labels(df)

    pd.testing.assert_frame_equal(df, original)


def test_csv_and_parquet_inputs_are_supported(tmp_path):
    from src.core.agentic.rocket_label_reconstructor import reconstruct_file

    df = pd.DataFrame([_row(mfe_1d=10.0, mfe_2d=10.0, mfe_5d=10.0)])
    csv_path = tmp_path / "dataset.csv"
    parquet_path = tmp_path / "dataset.parquet"
    df.to_csv(csv_path, index=False)
    df.to_parquet(parquet_path, index=False)

    csv_result = reconstruct_file(csv_path)
    parquet_result = reconstruct_file(parquet_path)

    assert csv_result.loc[0, "training_runner_tier"] == "STANDARD_WIN"
    assert parquet_result.loc[0, "training_runner_tier"] == "STANDARD_WIN"


def test_report_totals_sum_to_total_rows():
    from src.core.agentic.rocket_label_reconstructor import (
        generate_label_coverage_report,
        reconstruct_labels,
    )

    df = pd.DataFrame(
        [
            _row(row_id="exact", mfe_1d=10.0, mfe_2d=10.0, mfe_5d=10.0),
            _row(row_id="provisional", mfe_1d=10.0),
            _row(row_id="unknown"),
        ]
    )
    result = reconstruct_labels(df, include_provisional=True)
    report = generate_label_coverage_report(result)

    assert report["total_rows"] == 3
    assert (
        report["exact_label_count"]
        + report["provisional_label_count"]
        + report["unknown_count"]
        == report["total_rows"]
    )


def test_reconstruction_is_deterministic():
    from src.core.agentic.rocket_label_reconstructor import reconstruct_labels

    df = pd.DataFrame([_row(mfe_1d=10.0, mfe_2d=30.0, mfe_5d=300.0)])

    first = reconstruct_labels(df, include_provisional=True)
    second = reconstruct_labels(df, include_provisional=True)

    pd.testing.assert_frame_equal(first, second)


def test_module_does_not_import_network_or_ml_packages():
    import ast
    from pathlib import Path

    module_path = Path("src/core/agentic/rocket_label_reconstructor.py")
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    imported_roots = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imported_roots.update(
        node.module.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    )

    assert imported_roots.isdisjoint(
        {"requests", "httpx", "aiohttp", "yfinance", "alpaca", "sklearn", "xgboost"}
    )
