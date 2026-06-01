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
