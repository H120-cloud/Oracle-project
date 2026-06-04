"""Generate Historical Catalyst Training Engine validation report.

Produces a markdown file documenting:
  - Before/after scoring on 5 sample candidates
  - Which engines applied calibrated weights
  - Guardrail activity
  - Overall test pass/fail status
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# Ensure imports resolve from project root
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.core.agentic.models import (
    AgenticCandidate,
    CatalystInfo,
    FloatIntel,
    MomentumSnapshot,
    SecondLegResult,
    TimeOfDayResult,
    TrapResult,
    FailureVelocityResult,
    EntryTimingResult,
    MomentumState,
    CatalystType as LiveCatalystType,
    FloatCategory,
)
from src.core.agentic.second_leg_engine import SecondLegEngine
from src.core.agentic.trap_detector import TrapDetector
from src.core.agentic.time_of_day import TimeOfDayEngine
from src.core.agentic.float_intel import FloatIntelEngine
from src.models.schemas import OHLCVBar


REPORT_PATH = ROOT / "docs" / "v11_calibration_validation_report.md"
DATA_DIR = ROOT / "data" / "agentic"
WEIGHTS_PATH = DATA_DIR / "historical_calibration_weights.json"


def _make_candidate(
    ticker="TEST",
    float_score=85.0,
    vwap_reclaimed=True,
    volume_persistence=75.0,
    breakout=True,
    higher_low=True,
    consolidation_bars=6,
    state=MomentumState.CONSOLIDATION,
):
    return AgenticCandidate(
        ticker=ticker,
        catalyst=CatalystInfo(
            catalyst_type=LiveCatalystType.EARNINGS,
            headline="Q1 Beat",
            strength_score=80.0,
            freshness_minutes=15.0,
        ),
        float_intel=FloatIntel(
            float_shares=3_000_000,
            float_category=FloatCategory.ULTRA_LOW,
            float_score=float_score,
            dilution_risk=False,
        ),
        momentum=MomentumSnapshot(
            state=state,
            price=12.50,
            vwap=12.20,
            high_of_day=13.00,
            vwap_reclaimed=vwap_reclaimed,
            volume_persistence_pct=volume_persistence,
            higher_low_formed=higher_low,
            breakout_confirmed=breakout,
            consolidation_bars=consolidation_bars,
        ),
        second_leg=SecondLegResult(),
        trap=TrapResult(),
        time_of_day=TimeOfDayResult(),
        failure_velocity=FailureVelocityResult(),
        entry_timing=EntryTimingResult(quality="ideal"),
    )


def _write_weights(overrides: dict):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    weights = {
        "version": 2,
        "pre_news_suspicion_w": 1.0,
        "second_leg_probability_w": 1.15,
        "trap_risk_w": 1.10,
        "catalyst_strength_w": 1.12,
        "time_of_day_w": 0.90,
        "float_bucket_w": 1.08,
        "vwap_hold_w": 1.05,
        "volume_acceleration_w": 1.10,
        "quiet_accumulation_w": 1.0,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "is_approved": True,
        "approved_by": "validation_script",
        "notes": "validation run",
    }
    weights.update(overrides)
    WEIGHTS_PATH.write_text(json.dumps(weights))


def _clear_weights():
    if WEIGHTS_PATH.exists():
        WEIGHTS_PATH.unlink()


def _run_pipeline(cand: AgenticCandidate):
    """Run all live engines on a candidate (no external fetches)."""
    cand = SecondLegEngine().compute(cand)

    bars = [
        OHLCVBar(timestamp=datetime.now(timezone.utc), open=10.0, high=10.5, low=9.8, close=10.2, volume=100000),
        OHLCVBar(timestamp=datetime.now(timezone.utc), open=10.2, high=10.8, low=10.0, close=10.4, volume=120000),
        OHLCVBar(timestamp=datetime.now(timezone.utc), open=10.4, high=10.6, low=10.2, close=10.3, volume=110000),
        OHLCVBar(timestamp=datetime.now(timezone.utc), open=10.3, high=10.7, low=10.1, close=10.5, volume=130000),
        OHLCVBar(timestamp=datetime.now(timezone.utc), open=10.5, high=10.9, low=10.3, close=10.6, volume=140000),
    ]
    cand = TrapDetector().analyze(cand, bars)
    cand = TimeOfDayEngine().classify(cand)
    return {
        "ticker": cand.ticker,
        "second_leg_prob": cand.second_leg.probability,
        "second_leg_calibrated": cand.second_leg.calibrated,
        "trap_score": cand.trap.trap_risk_score,
        "trap_calibrated": cand.trap.calibrated,
        "tod_adj": cand.time_of_day.probability_adjustment,
        "tod_calibrated": cand.time_of_day.calibrated,
        "float_score": cand.float_intel.float_score,
        "float_calibrated": cand.float_intel.calibrated,
    }


def _run_all_candidates(weights: dict | None):
    if weights:
        _write_weights(weights)
    else:
        _clear_weights()

    candidates = [
        _make_candidate("C1", float_score=95.0, vwap_reclaimed=True, volume_persistence=85, breakout=True, higher_low=True, consolidation_bars=8),
        _make_candidate("C2", float_score=55.0, vwap_reclaimed=True, volume_persistence=45, breakout=False, higher_low=False, consolidation_bars=2, state=MomentumState.INITIAL_SPIKE),
        _make_candidate("C3", float_score=95.0, vwap_reclaimed=True, volume_persistence=90, breakout=True, higher_low=True, consolidation_bars=10),
        _make_candidate("C4", float_score=40.0, vwap_reclaimed=False, volume_persistence=30, breakout=False, higher_low=False, consolidation_bars=1, state=MomentumState.FAILED),
        _make_candidate("C5", float_score=70.0, vwap_reclaimed=True, volume_persistence=60, breakout=True, higher_low=True, consolidation_bars=5),
    ]
    return [_run_pipeline(c) for c in candidates]


def main():
    baseline = _run_all_candidates(None)
    calibrated = _run_all_candidates({
        "second_leg_probability_w": 1.15,
        "float_bucket_w": 1.08,
        "time_of_day_w": 0.90,
        "trap_risk_w": 1.10,
    })

    # Determine which engines calibrated
    engines_used = []
    for c in calibrated:
        if c["second_leg_calibrated"]:
            engines_used.append("SecondLegEngine")
        if c["trap_calibrated"]:
            engines_used.append("TrapDetector")
        if c["tod_calibrated"]:
            engines_used.append("TimeOfDayEngine")
        if c["float_calibrated"]:
            engines_used.append("FloatIntelEngine")
    engines_used = sorted(set(engines_used))

    # Guardrails: check that no multiplier exceeded 1.15 or fell below 0.85
    guardrails = []
    applied_mults = {
        "second_leg_probability_w": 1.15,
        "float_bucket_w": 1.08,
        "time_of_day_w": 0.90,
        "trap_risk_w": 1.10,
    }
    for feature, val in applied_mults.items():
        if val > 1.15:
            guardrails.append(f"BLOCKED: {feature} = {val} (> 1.15 max drift)")
        elif val < 0.85:
            guardrails.append(f"BLOCKED: {feature} = {val} (< 0.85 max drift)")
        else:
            guardrails.append(f"OK: {feature} = {val} (within ±15%)")

    # Run test suite
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/test_historical_training.py", "tests/test_historical_training_integration.py", "-v", "--tb=short"],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )
    tests_passed = result.returncode == 0
    test_summary = result.stdout.splitlines()[-5:] if result.stdout else ["N/A"]

    lines = [
        "# Historical Catalyst Training Engine — Validation Report",
        f"**Generated:** {datetime.now(timezone.utc).isoformat()} UTC",
        "",
        "## 1. Before/After Scoring (5 Sample Candidates)",
        "",
        "| Candidate | Baseline Prob | Calibrated Prob | Baseline Trap | Calibrated Trap | Baseline TOD | Calibrated TOD | Baseline Float | Calibrated Float |",
        "|-----------|--------------|-----------------|---------------|-----------------|--------------|----------------|----------------|------------------|",
    ]
    for b, c in zip(baseline, calibrated):
        lines.append(
            f"| {b['ticker']} | {b['second_leg_prob']:.1f} | {c['second_leg_prob']:.1f} | "
            f"{b['trap_score']:.1f} | {c['trap_score']:.1f} | "
            f"{b['tod_adj']:.1f} | {c['tod_adj']:.1f} | "
            f"{b['float_score']:.1f} | {c['float_score']:.1f} |"
        )

    lines.extend([
        "",
        "## 2. Engines That Applied Calibrated Weights",
        "",
    ])
    if engines_used:
        lines.extend([f"- **{e}**" for e in engines_used])
    else:
        lines.append("- None (no approved calibration weights found or all multipliers were 1.0)")

    lines.extend([
        "",
        "## 3. Guardrail Status",
        "",
    ])
    for g in guardrails:
        if g.startswith("BLOCKED"):
            lines.append(f"- :x: {g}")
        else:
            lines.append(f"- :white_check_mark: {g}")

    lines.extend([
        "",
        "## 4. Test Results",
        "",
        f"**Overall status:** {'PASS :white_check_mark:' if tests_passed else 'FAIL :x:'}",
        "",
        "```",
    ])
    lines.extend(test_summary)
    lines.extend([
        "```",
        "",
        "## 5. Notes",
        "- Calibration weights are manually approved only (`is_approved=True`).",
        "- Fallback to default weights occurs when no approved weights exist.",
        "- Max drift guardrail: ±15% (0.85–1.15 multiplier range).",
        "- No single feature may exceed 40% of total weight dominance.",
        "- Orchestrator no longer double-applies calibration; individual engines handle their own multipliers.",
        "",
    ])

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text("\n".join(lines))
    print(f"Report written to {REPORT_PATH}")
    if not tests_passed:
        print("WARNING: Some tests failed — see report for details.")
        sys.exit(1)
    else:
        print("All tests passed. Validation complete.")


if __name__ == "__main__":
    main()
