"""Ticker integrity guards for Rocket training-data pipelines."""
from __future__ import annotations

import re
from typing import Any, Tuple

import pandas as pd

SYNTHETIC_REJECTION_REASON = "synthetic_test_ticker"
SYNTHETIC_TICKER_PREFIXES = (
    "GREAT",
    "GOOD",
    "TEST",
    "FAKE",
    "MOCK",
    "SAMPLE",
    "DEMO",
    "LATE",
    "TRAP",
)

_SYNTHETIC_TICKER_PATTERN = re.compile(
    rf"^(?:{'|'.join(SYNTHETIC_TICKER_PREFIXES)})\d+$",
    re.IGNORECASE,
)


def is_synthetic_test_ticker(ticker: Any) -> bool:
    """Return whether *ticker* matches a reserved synthetic-test pattern."""
    if ticker is None:
        return False
    return bool(_SYNTHETIC_TICKER_PATTERN.fullmatch(str(ticker).strip()))


def synthetic_test_ticker_mask(df: pd.DataFrame) -> pd.Series:
    """Return an index-aligned mask identifying synthetic-test ticker rows."""
    if "ticker" not in df.columns:
        raise ValueError("Rocket dataset is missing required ticker column")
    return df["ticker"].map(is_synthetic_test_ticker)


def partition_synthetic_rows(df: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Return eligible and marked synthetic rows without mutating *df*."""
    working = df.copy(deep=True)
    if "rejection_reason" not in working.columns:
        working["rejection_reason"] = None
    mask = synthetic_test_ticker_mask(working)
    working.loc[mask, "rejection_reason"] = SYNTHETIC_REJECTION_REASON
    return working.loc[~mask].copy(), working.loc[mask].copy()


__all__ = [
    "SYNTHETIC_REJECTION_REASON",
    "SYNTHETIC_TICKER_PREFIXES",
    "is_synthetic_test_ticker",
    "partition_synthetic_rows",
    "synthetic_test_ticker_mask",
]
