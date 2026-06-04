from __future__ import annotations

import pandas as pd

from src.core.agentic.rocket_ticker_integrity import (
    SYNTHETIC_REJECTION_REASON,
    is_synthetic_test_ticker,
    partition_synthetic_rows,
)


def test_synthetic_ticker_patterns_are_rejected():
    for ticker in (
        "GREAT001",
        "GOOD099",
        "TEST123",
        "FAKE007",
        "MOCK042",
        "SAMPLE010",
        "DEMO999",
        "LATE048",
        "TRAP099",
    ):
        assert is_synthetic_test_ticker(ticker)


def test_real_and_non_numbered_symbols_are_preserved():
    for ticker in ("AAPL", "BRK-A", "GOOD", "TEST", "GREATNESS", "DEMO-A"):
        assert not is_synthetic_test_ticker(ticker)


def test_partition_marks_and_excludes_synthetic_rows_without_mutating_source():
    source = pd.DataFrame(
        [
            {"ticker": "AAPL", "training_runner_tier": "UNKNOWN"},
            {"ticker": "GOOD001", "training_runner_tier": "UNKNOWN"},
        ]
    )

    eligible, rejected = partition_synthetic_rows(source)

    assert eligible["ticker"].tolist() == ["AAPL"]
    assert rejected["ticker"].tolist() == ["GOOD001"]
    assert rejected.iloc[0]["rejection_reason"] == SYNTHETIC_REJECTION_REASON
    assert "rejection_reason" not in source.columns
