"""After a promoted retrain, the ML percentile bands must be recalibrated.

classify_ml_tier buckets win-probabilities against p85/p95/p99 of the model's
own score distribution. A newly promoted model has a different distribution, so
keeping the old bands mis-tiers every alert until the next process restart.
"""

from types import SimpleNamespace

import pytest

from src.core.agentic.news_momentum_orchestrator import NewsMomentumOrchestrator
from src.core.agentic.news_momentum_ml_engine import TrainingResult


def _bare_orch(train_result):
    orch = object.__new__(NewsMomentumOrchestrator)  # skip heavy __init__
    orch._telegram_learning = SimpleNamespace(_alerts=[])
    orch._missed_learning = SimpleNamespace(_records=[])
    orch._ml_engine = SimpleNamespace(train=lambda records, missed_records=None: train_result)
    orch._recalibrated = False
    orch._calibrate_ml_percentiles = lambda: setattr(orch, "_recalibrated", True)
    return orch


@pytest.mark.unit
def test_promoted_retrain_recalibrates_percentile_bands():
    orch = _bare_orch(TrainingResult(success=True, promoted=True))
    result = orch.retrain_ml()
    assert result.promoted
    assert orch._recalibrated, "promoted retrain must recalibrate the ML percentile bands"


@pytest.mark.unit
def test_unpromoted_retrain_keeps_existing_bands():
    orch = _bare_orch(TrainingResult(success=True, promoted=False))
    orch.retrain_ml()
    assert not orch._recalibrated, "bands belong to the live model; no promotion → no recalibration"
