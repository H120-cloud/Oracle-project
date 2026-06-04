"""
Threshold-centralization equivalence test (P0).

Pins every centralized threshold in NewsMomentumConfig to the literal value
it had before the centralization refactor. If a default changes, this test
fails — that is the intended safety net.

To deliberately tune a threshold, update both the default AND this snapshot
in the same commit, with a paired entry in
docs/refactor/P0_test_infra_and_threshold_centralization.md explaining why.
"""

from __future__ import annotations

import pytest

from src.core.agentic.news_momentum_models import NewsMomentumConfig

pytestmark = [pytest.mark.unit, pytest.mark.gate]


# Snapshot of the literal values that lived inline in the orchestrator and
# winners modules prior to the P0 centralization. Changing any of these
# IS a behavior change.
_THRESHOLD_SNAPSHOT = {
    # ML hard floor / veto
    "ml_min_win_probability": 0.25,
    "ml_veto_win_probability": 0.20,
    "ml_veto_min_confidence": 0.6,
    "ml_amplify_win_probability": 0.75,
    "ml_bypass_impact_threshold": 75.0,
    # Sub-$10 leniency
    "under_1_lenient_step_down": 15.0,
    "under_1_min_floor": 35.0,
    "under_1_max_price": 10.0,
    # High-conviction step-down
    "high_conviction_step_down": 10.0,
    "high_conviction_min_floor": 30.0,
    # First-mover speed tier (MAX-SPEED tuning 2026-05-29: wider window + lower
    # floors so fresh strong-positive catalysts alert before the spike).
    "first_mover_max_age_seconds": 300,
    "first_mover_min_impact": 20.0,
    "first_mover_min_return": 20.0,
    "first_mover_min_continuation": 15.0,
    "first_mover_min_multi_day": 15.0,
    "first_mover_impact_floor": 20.0,
    # Price-action breakout
    "breakout_mega_move_pct": 35.0,
    "breakout_mega_rvol": 5.0,
    "breakout_strong_move_pct": 20.0,
    "breakout_strong_rvol": 3.0,
    "breakout_mega_impact_floor": 25.0,
    "breakout_strong_impact_floor": 35.0,
    "breakout_relax_min_impact": 35.0,
    "breakout_relax_min_continuation": 30.0,
    # Impact floor base
    "impact_floor_default": 50.0,
    "impact_floor_under_1": 45.0,
    # Risk gates
    "high_dilution_block_threshold": 70.0,
    "high_trap_block_threshold": 70.0,
    # Winner ML tier bands
    "ml_band_p85": 0.20,
    "ml_band_p95": 0.30,
    "ml_band_p99": 0.40,
    "ml_tier_high_conviction_adjust": 15.0,
    "ml_tier_watch_adjust": -10.0,
}


@pytest.fixture(scope="module")
def default_config() -> NewsMomentumConfig:
    return NewsMomentumConfig()


@pytest.mark.parametrize("field,expected", list(_THRESHOLD_SNAPSHOT.items()))
def test_threshold_default_matches_snapshot(default_config, field, expected):
    actual = getattr(default_config, field)
    assert actual == expected, (
        f"NewsMomentumConfig.{field} default has drifted: "
        f"got {actual!r}, snapshot expected {expected!r}. "
        "Update both the default and this snapshot in the same commit, "
        "and document why in docs/refactor/."
    )


def test_no_centralized_field_is_missing():
    """If a field is removed from the model entirely, fail loudly."""
    fields = NewsMomentumConfig.model_fields.keys()
    missing = [k for k in _THRESHOLD_SNAPSHOT if k not in fields]
    assert not missing, f"Centralized fields removed from model: {missing}"


def test_winner_module_band_seeds_match_config_defaults():
    """
    The winners module owns mutable percentile-band globals seeded with
    literal values. Drift between those seeds and the config defaults
    means they could diverge silently when the config is tuned.
    """
    from src.core.agentic.news_momentum_winners import _ML_PERCENTILE_BANDS

    cfg = NewsMomentumConfig()
    assert _ML_PERCENTILE_BANDS["p85"] == cfg.ml_band_p85
    assert _ML_PERCENTILE_BANDS["p95"] == cfg.ml_band_p95
    assert _ML_PERCENTILE_BANDS["p99"] == cfg.ml_band_p99
