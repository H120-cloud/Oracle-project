"""Before-vs-After Calibration Validation for Agentic Pipeline.

Generates a replay dataset with ground-truth outcomes, runs the pipeline
with default weights then calibrated weights, and reports comparative metrics.
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

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
    CatalystType,
    FloatCategory,
    TradingSession,
    ConfidenceLevel,
    OutcomeClass,
)
from src.core.agentic.second_leg_engine import SecondLegEngine
from src.core.agentic.trap_detector import TrapDetector
from src.core.agentic.time_of_day import TimeOfDayEngine
from src.core.agentic.float_intel import FloatIntelEngine
from src.models.schemas import OHLCVBar


# ── Replay dataset definition ────────────────────────────────────────────────

@dataclass
class ReplayCase:
    ticker: str
    catalyst_type: CatalystType
    catalyst_strength: float
    float_shares: float
    float_score: float
    state: MomentumState
    vwap_reclaimed: bool
    volume_persistence: float
    breakout: bool
    higher_low: bool
    consolidation_bars: int
    time_of_day_session: TradingSession
    tod_adjustment: float
    trap_score_gt: float  # baseline trap risk score we will inject
    
    # Ground truth outcome
    outcome_class: OutcomeClass
    mfe_pct: float        # max favorable excursion % after alert time
    mae_pct: float        # max adverse excursion % after alert time
    eod_move_pct: float   # price move from alert time to EOD


def build_replay_dataset(n_per_profile: int = 10) -> list[ReplayCase]:
    """Build a diverse replay dataset with realistic ground-truth outcomes."""
    cases: list[ReplayCase] = []
    
    profiles = [
        # Winners — strong setups
        {
            "catalyst_type": CatalystType.EARNINGS,
            "catalyst_strength": 85,
            "float_shares": 3_000_000,
            "float_score": 90,
            "state": MomentumState.CONSOLIDATION,
            "vwap_reclaimed": True,
            "volume_persistence": 80,
            "breakout": True,
            "higher_low": True,
            "consolidation_bars": 8,
            "time_of_day_session": TradingSession.OPEN,
            "tod_adjustment": 10,
            "trap_score_gt": 15,
            "outcome_class": OutcomeClass.CLEAN_CONTINUATION,
            "mfe_pct": 35,
            "mae_pct": -2,
            "eod_move_pct": 28,
        },
        {
            "catalyst_type": CatalystType.CONTRACT,
            "catalyst_strength": 75,
            "float_shares": 4_000_000,
            "float_score": 85,
            "state": MomentumState.SECOND_LEG_FORMING,
            "vwap_reclaimed": True,
            "volume_persistence": 70,
            "breakout": True,
            "higher_low": True,
            "consolidation_bars": 6,
            "time_of_day_session": TradingSession.POWER_HOUR,
            "tod_adjustment": 5,
            "trap_score_gt": 20,
            "outcome_class": OutcomeClass.CLEAN_CONTINUATION,
            "mfe_pct": 22,
            "mae_pct": -3,
            "eod_move_pct": 18,
        },
        {
            "catalyst_type": CatalystType.FDA,
            "catalyst_strength": 90,
            "float_shares": 2_000_000,
            "float_score": 95,
            "state": MomentumState.CONTINUATION_CONFIRMED,
            "vwap_reclaimed": True,
            "volume_persistence": 95,
            "breakout": True,
            "higher_low": True,
            "consolidation_bars": 10,
            "time_of_day_session": TradingSession.OPEN,
            "tod_adjustment": 10,
            "trap_score_gt": 10,
            "outcome_class": OutcomeClass.CLEAN_CONTINUATION,
            "mfe_pct": 55,
            "mae_pct": -1,
            "eod_move_pct": 48,
        },
        # Losers — weak / trap setups
        {
            "catalyst_type": CatalystType.OFFERING,
            "catalyst_strength": 30,
            "float_shares": 50_000_000,
            "float_score": 25,
            "state": MomentumState.FAILED,
            "vwap_reclaimed": False,
            "volume_persistence": 20,
            "breakout": False,
            "higher_low": False,
            "consolidation_bars": 1,
            "time_of_day_session": TradingSession.MIDDAY,
            "tod_adjustment": -10,
            "trap_score_gt": 70,
            "outcome_class": OutcomeClass.FAILED,
            "mfe_pct": 1,
            "mae_pct": -12,
            "eod_move_pct": -8,
        },
        {
            "catalyst_type": CatalystType.EARNINGS,
            "catalyst_strength": 40,
            "float_shares": 30_000_000,
            "float_score": 40,
            "state": MomentumState.INITIAL_SPIKE,
            "vwap_reclaimed": False,
            "volume_persistence": 35,
            "breakout": False,
            "higher_low": False,
            "consolidation_bars": 2,
            "time_of_day_session": TradingSession.AFTERHOURS,
            "tod_adjustment": -15,
            "trap_score_gt": 55,
            "outcome_class": OutcomeClass.FAILED,
            "mfe_pct": 3,
            "mae_pct": -8,
            "eod_move_pct": -5,
        },
        {
            "catalyst_type": CatalystType.OTHER_NEWS,
            "catalyst_strength": 50,
            "float_shares": 15_000_000,
            "float_score": 55,
            "state": MomentumState.SPIKE_PULLBACK,
            "vwap_reclaimed": True,
            "volume_persistence": 45,
            "breakout": False,
            "higher_low": False,
            "consolidation_bars": 3,
            "time_of_day_session": TradingSession.MIDDAY,
            "tod_adjustment": -10,
            "trap_score_gt": 45,
            "outcome_class": OutcomeClass.FAILED,
            "mfe_pct": 5,
            "mae_pct": -5,
            "eod_move_pct": -2,
        },
        # Edge cases — mixed
        {
            "catalyst_type": CatalystType.LEGAL_PATENT,
            "catalyst_strength": 65,
            "float_shares": 8_000_000,
            "float_score": 70,
            "state": MomentumState.CONSOLIDATION,
            "vwap_reclaimed": True,
            "volume_persistence": 55,
            "breakout": True,
            "higher_low": True,
            "consolidation_bars": 5,
            "time_of_day_session": TradingSession.POWER_HOUR,
            "tod_adjustment": 5,
            "trap_score_gt": 35,
            "outcome_class": OutcomeClass.PARTIAL,
            "mfe_pct": 12,
            "mae_pct": -4,
            "eod_move_pct": 8,
        },
        {
            "catalyst_type": CatalystType.MERGER,
            "catalyst_strength": 55,
            "float_shares": 6_000_000,
            "float_score": 75,
            "state": MomentumState.INITIAL_SPIKE,
            "vwap_reclaimed": False,
            "volume_persistence": 50,
            "breakout": False,
            "higher_low": False,
            "consolidation_bars": 2,
            "time_of_day_session": TradingSession.OPEN,
            "tod_adjustment": 10,
            "trap_score_gt": 40,
            "outcome_class": OutcomeClass.FAILED,
            "mfe_pct": 4,
            "mae_pct": -6,
            "eod_move_pct": -3,
        },
    ]
    
    for idx, p in enumerate(profiles):
        for i in range(n_per_profile):
            cases.append(ReplayCase(
                ticker=f"R{idx}{i:02d}",
                catalyst_type=p["catalyst_type"],
                catalyst_strength=p["catalyst_strength"] + (i * 2 - n_per_profile),  # slight variation
                float_shares=p["float_shares"],
                float_score=p["float_score"] + (i - n_per_profile // 2),
                state=p["state"],
                vwap_reclaimed=p["vwap_reclaimed"],
                volume_persistence=max(0, min(100, p["volume_persistence"] + (i * 3 - n_per_profile))),
                breakout=p["breakout"],
                higher_low=p["higher_low"],
                consolidation_bars=p["consolidation_bars"],
                time_of_day_session=p["time_of_day_session"],
                tod_adjustment=p["tod_adjustment"],
                trap_score_gt=p["trap_score_gt"],
                outcome_class=p["outcome_class"],
                mfe_pct=p["mfe_pct"] + (i - n_per_profile // 2),
                mae_pct=p["mae_pct"] + (i - n_per_profile // 2) * 0.5,
                eod_move_pct=p["eod_move_pct"] + (i - n_per_profile // 2) * 0.8,
            ))
    
    return cases


def _case_to_candidate(case: ReplayCase) -> AgenticCandidate:
    """Convert a ReplayCase into a fully-populated AgenticCandidate."""
    return AgenticCandidate(
        ticker=case.ticker,
        catalyst=CatalystInfo(
            catalyst_type=case.catalyst_type,
            headline=f"{case.catalyst_type.value} catalyst",
            strength_score=case.catalyst_strength,
            freshness_minutes=15.0,
        ),
        float_intel=FloatIntel(
            float_shares=case.float_shares,
            float_category=FloatCategory.ULTRA_LOW if case.float_shares < 5_000_000 else (
                FloatCategory.LOW if case.float_shares < 20_000_000 else FloatCategory.NORMAL
            ),
            float_score=case.float_score,
            dilution_risk=case.catalyst_type == CatalystType.OFFERING,
            dilution_risk_reason="Offering detected" if case.catalyst_type == CatalystType.OFFERING else None,
        ),
        momentum=MomentumSnapshot(
            state=case.state,
            price=12.50,
            vwap=12.20,
            high_of_day=13.00,
            vwap_reclaimed=case.vwap_reclaimed,
            volume_persistence_pct=case.volume_persistence,
            higher_low_formed=case.higher_low,
            breakout_confirmed=case.breakout,
            consolidation_bars=case.consolidation_bars,
        ),
        second_leg=SecondLegResult(),
        trap=TrapResult(),
        time_of_day=TimeOfDayResult(
            session=case.time_of_day_session,
            probability_adjustment=case.tod_adjustment,
            reason=f"Session: {case.time_of_day_session.value}",
        ),
        failure_velocity=FailureVelocityResult(
            is_distribution=case.state in (MomentumState.FAILED, MomentumState.DEAD),
        ),
        entry_timing=EntryTimingResult(
            quality="ideal" if case.state == MomentumState.CONSOLIDATION else (
                "early" if case.state == MomentumState.INITIAL_SPIKE else "late"
            ),
        ),
    )


def _make_bars_for_case(case: ReplayCase) -> list[OHLCVBar]:
    """Generate synthetic bars that produce the desired trap score."""
    bars = []
    base = 10.0
    for i in range(10):
        # Higher trap_score_gt -> more upper wicks and reversals
        reversal_factor = case.trap_score_gt / 100
        high = base * (1 + 0.02 * i * (1 + reversal_factor))
        low = base * (1 - 0.01 * i * reversal_factor)
        close = base + (0.01 * i if case.outcome_class != OutcomeClass.FAILED else -0.005 * i)
        vol = 100000 * (1 + i * 0.1)
        bars.append(OHLCVBar(
            timestamp=datetime.now(timezone.utc),
            open=base,
            high=high,
            low=low,
            close=close,
            volume=int(vol),
        ))
    return bars


def run_pipeline(case: ReplayCase) -> AgenticCandidate:
    """Run a single case through the live engines (no external fetches)."""
    cand = _case_to_candidate(case)
    
    # Second leg engine
    cand = SecondLegEngine().compute(cand)
    
    # Trap detector
    bars = _make_bars_for_case(case)
    cand = TrapDetector().analyze(cand, bars)
    
    # Override trap score with ground-truth profile for consistency
    # (the synthetic bars approximate it, but we want exact profiles)
    cand.trap.trap_risk_score = case.trap_score_gt
    cand.trap.is_trap = case.trap_score_gt >= 65
    
    # Time of day
    cand = TimeOfDayEngine().classify(cand)
    # Restore the profile's TOD adjustment (TimeOfDayEngine uses real clock)
    cand.time_of_day.probability_adjustment = case.tod_adjustment
    cand.time_of_day.session = case.time_of_day_session
    
    # Final probability composition (mirror orchestrator logic)
    prob = cand.second_leg.probability
    prob += cand.time_of_day.probability_adjustment
    
    trap_threshold = 65
    trap_warn_threshold = 40
    if cand.trap.trap_risk_score >= trap_threshold:
        prob *= 0.4
        cand.rejection_reasons.append(f"Trap risk {cand.trap.trap_risk_score:.0f}%")
    elif cand.trap.trap_risk_score >= trap_warn_threshold:
        prob *= 0.7
    
    if cand.failure_velocity.is_distribution:
        prob *= 0.5
        cand.rejection_reasons.append("Distribution detected")
    
    prob = round(max(0, min(100, prob)), 1)
    cand.final_probability = prob
    
    # Alertable decision (mirror orchestrator)
    from src.core.agentic.models import EntryQuality
    cand.alertable = (
        prob >= 70
        and cand.entry_timing.quality == EntryQuality.IDEAL
        and cand.trap.trap_risk_score < 65
        and not cand.failure_velocity.is_distribution
        and cand.momentum.state not in (MomentumState.DEAD, MomentumState.FAILED)
    )
    
    return cand


# ── Metrics ────────────────────────────────────────────────────────────────

@dataclass
class RunMetrics:
    total_candidates: int = 0
    alerts_generated: int = 0
    clean_continuation_rate: float = 0.0
    false_alert_rate: float = 0.0
    missed_runner_rate: float = 0.0
    avg_mfe: float = 0.0
    avg_mae: float = 0.0
    avg_prob_winners: float = 0.0
    avg_prob_losers: float = 0.0
    by_catalyst: dict = field(default_factory=dict)
    by_float: dict = field(default_factory=dict)
    by_tod: dict = field(default_factory=dict)


def compute_metrics(cases: list[ReplayCase], cands: list[AgenticCandidate]) -> RunMetrics:
    m = RunMetrics()
    m.total_candidates = len(cases)
    
    alerted = [(c, cand) for c, cand in zip(cases, cands) if cand.alertable]
    m.alerts_generated = len(alerted)
    
    # Winners are clean continuations
    winners = [c for c in cases if c.outcome_class == OutcomeClass.CLEAN_CONTINUATION]
    losers = [c for c in cases if c.outcome_class != OutcomeClass.CLEAN_CONTINUATION]
    
    # Clean continuation rate = alerted winners / total alerts
    alerted_winners = [c for c, _ in alerted if c.outcome_class == OutcomeClass.CLEAN_CONTINUATION]
    if m.alerts_generated > 0:
        m.clean_continuation_rate = len(alerted_winners) / m.alerts_generated * 100
        m.false_alert_rate = (m.alerts_generated - len(alerted_winners)) / m.alerts_generated * 100
    
    # Missed runner rate = winners NOT alerted / total winners
    missed_winners = [c for c in winners if not any(cc.ticker == c.ticker for cc, _ in alerted)]
    if winners:
        m.missed_runner_rate = len(missed_winners) / len(winners) * 100
    
    # MFE / MAE for alerts
    if alerted:
        m.avg_mfe = sum(c.mfe_pct for c, _ in alerted) / len(alerted)
        m.avg_mae = sum(c.mae_pct for c, _ in alerted) / len(alerted)
    
    # Probabilities
    winner_probs = [cand.final_probability for c, cand in zip(cases, cands) if c.outcome_class == OutcomeClass.CLEAN_CONTINUATION]
    loser_probs = [cand.final_probability for c, cand in zip(cases, cands) if c.outcome_class != OutcomeClass.CLEAN_CONTINUATION]
    if winner_probs:
        m.avg_prob_winners = sum(winner_probs) / len(winner_probs)
    if loser_probs:
        m.avg_prob_losers = sum(loser_probs) / len(loser_probs)
    
    # By catalyst type
    for ct in CatalystType:
        ct_cases = [(c, cand) for c, cand in zip(cases, cands) if c.catalyst_type == ct]
        ct_alerted = [(c, cand) for c, cand in ct_cases if cand.alertable]
        ct_winners = [c for c, _ in ct_alerted if c.outcome_class == OutcomeClass.CLEAN_CONTINUATION]
        m.by_catalyst[ct.value] = {
            "total": len(ct_cases),
            "alerts": len(ct_alerted),
            "win_rate": len(ct_winners) / len(ct_alerted) * 100 if ct_alerted else 0,
        }
    
    # By float bucket
    for fb in ["ultra_low", "low", "normal"]:
        fb_cases = [(c, cand) for c, cand in zip(cases, cands)
                    if (c.float_shares < 5_000_000 and fb == "ultra_low") or
                       (5_000_000 <= c.float_shares < 20_000_000 and fb == "low") or
                       (c.float_shares >= 20_000_000 and fb == "normal")]
        fb_alerted = [(c, cand) for c, cand in fb_cases if cand.alertable]
        fb_winners = [c for c, _ in fb_alerted if c.outcome_class == OutcomeClass.CLEAN_CONTINUATION]
        m.by_float[fb] = {
            "total": len(fb_cases),
            "alerts": len(fb_alerted),
            "win_rate": len(fb_winners) / len(fb_alerted) * 100 if fb_alerted else 0,
        }
    
    # By time of day
    for tod in TradingSession:
        tod_cases = [(c, cand) for c, cand in zip(cases, cands) if c.time_of_day_session == tod]
        tod_alerted = [(c, cand) for c, cand in tod_cases if cand.alertable]
        tod_winners = [c for c, _ in tod_alerted if c.outcome_class == OutcomeClass.CLEAN_CONTINUATION]
        m.by_tod[tod.value] = {
            "total": len(tod_cases),
            "alerts": len(tod_alerted),
            "win_rate": len(tod_winners) / len(tod_alerted) * 100 if tod_alerted else 0,
        }
    
    return m


# ── Report generation ─────────────────────────────────────────────────────

def generate_report(default_metrics: RunMetrics, calibrated_metrics: RunMetrics, output_path: Path):
    def fmt(val: float) -> str:
        return f"{val:.1f}"
    
    def delta(before: float, after: float) -> str:
        diff = after - before
        arrow = "↑" if diff > 0 else "↓" if diff < 0 else "→"
        return f"{arrow} {diff:+.1f}"
    
    lines = [
        "# Agentic Calibration Validation Report: Default vs Calibrated",
        f"**Generated:** {datetime.now(timezone.utc).isoformat()} UTC",
        "",
        "## Executive Summary",
        "",
        f"| Metric | Default | Calibrated | Delta |",
        f"|--------|---------|------------|-------|",
        f"| Total Candidates | {default_metrics.total_candidates} | {calibrated_metrics.total_candidates} | — |",
        f"| Alerts Generated | {default_metrics.alerts_generated} | {calibrated_metrics.alerts_generated} | {delta(default_metrics.alerts_generated, calibrated_metrics.alerts_generated)} |",
        f"| Clean Continuation Rate | {fmt(default_metrics.clean_continuation_rate)}% | {fmt(calibrated_metrics.clean_continuation_rate)}% | {delta(default_metrics.clean_continuation_rate, calibrated_metrics.clean_continuation_rate)} |",
        f"| False Alert Rate | {fmt(default_metrics.false_alert_rate)}% | {fmt(calibrated_metrics.false_alert_rate)}% | {delta(default_metrics.false_alert_rate, calibrated_metrics.false_alert_rate)} |",
        f"| Missed Runner Rate | {fmt(default_metrics.missed_runner_rate)}% | {fmt(calibrated_metrics.missed_runner_rate)}% | {delta(default_metrics.missed_runner_rate, calibrated_metrics.missed_runner_rate)} |",
        f"| Avg MFE (alerts) | {fmt(default_metrics.avg_mfe)}% | {fmt(calibrated_metrics.avg_mfe)}% | {delta(default_metrics.avg_mfe, calibrated_metrics.avg_mfe)} |",
        f"| Avg MAE (alerts) | {fmt(default_metrics.avg_mae)}% | {fmt(calibrated_metrics.avg_mae)}% | {delta(default_metrics.avg_mae, calibrated_metrics.avg_mae)} |",
        f"| Avg Prob (Winners) | {fmt(default_metrics.avg_prob_winners)} | {fmt(calibrated_metrics.avg_prob_winners)} | {delta(default_metrics.avg_prob_winners, calibrated_metrics.avg_prob_winners)} |",
        f"| Avg Prob (Losers) | {fmt(default_metrics.avg_prob_losers)} | {fmt(calibrated_metrics.avg_prob_losers)} | {delta(default_metrics.avg_prob_losers, calibrated_metrics.avg_prob_losers)} |",
        "",
        "### Interpretation",
        "- **Clean Continuation Rate** = alerted winners / total alerts. Higher is better.",
        "- **False Alert Rate** = alerted losers / total alerts. Lower is better.",
        "- **Missed Runner Rate** = winners not alerted / total winners. Lower is better.",
        "- **MFE/MAE** = reward/risk profile of alerted trades.",
        "",
        "## Performance by Catalyst Type",
        "",
        "| Catalyst | Default Total | Default Alerts | Default Win% | Calibrated Total | Calibrated Alerts | Calibrated Win% |",
        "|----------|---------------|----------------|--------------|------------------|-------------------|-----------------|",
    ]
    
    for ct in sorted(default_metrics.by_catalyst.keys()):
        d = default_metrics.by_catalyst[ct]
        c = calibrated_metrics.by_catalyst.get(ct, {"total": 0, "alerts": 0, "win_rate": 0})
        lines.append(f"| {ct} | {d['total']} | {d['alerts']} | {fmt(d['win_rate'])}% | {c['total']} | {c['alerts']} | {fmt(c['win_rate'])}% |")
    
    lines.extend([
        "",
        "## Performance by Float Bucket",
        "",
        "| Float Bucket | Default Total | Default Alerts | Default Win% | Calibrated Total | Calibrated Alerts | Calibrated Win% |",
        "|--------------|---------------|----------------|--------------|------------------|-------------------|-----------------|",
    ])
    
    for fb in ["ultra_low", "low", "normal"]:
        d = default_metrics.by_float[fb]
        c = calibrated_metrics.by_float.get(fb, {"total": 0, "alerts": 0, "win_rate": 0})
        lines.append(f"| {fb} | {d['total']} | {d['alerts']} | {fmt(d['win_rate'])}% | {c['total']} | {c['alerts']} | {fmt(c['win_rate'])}% |")
    
    lines.extend([
        "",
        "## Performance by Time of Day",
        "",
        "| Session | Default Total | Default Alerts | Default Win% | Calibrated Total | Calibrated Alerts | Calibrated Win% |",
        "|---------|---------------|----------------|--------------|------------------|-------------------|-----------------|",
    ])
    
    for tod in sorted(default_metrics.by_tod.keys()):
        d = default_metrics.by_tod[tod]
        c = calibrated_metrics.by_tod.get(tod, {"total": 0, "alerts": 0, "win_rate": 0})
        lines.append(f"| {tod} | {d['total']} | {d['alerts']} | {fmt(d['win_rate'])}% | {c['total']} | {c['alerts']} | {fmt(c['win_rate'])}% |")
    
    lines.extend([
        "",
        "## Conclusion",
        "",
    ])
    
    # Auto-generate conclusion
    improvements = []
    regressions = []
    
    if calibrated_metrics.clean_continuation_rate > default_metrics.clean_continuation_rate:
        improvements.append(f"clean continuation rate improved by {calibrated_metrics.clean_continuation_rate - default_metrics.clean_continuation_rate:.1f}pp")
    elif calibrated_metrics.clean_continuation_rate < default_metrics.clean_continuation_rate:
        regressions.append(f"clean continuation rate declined by {default_metrics.clean_continuation_rate - calibrated_metrics.clean_continuation_rate:.1f}pp")
    
    if calibrated_metrics.false_alert_rate < default_metrics.false_alert_rate:
        improvements.append(f"false alert rate dropped by {default_metrics.false_alert_rate - calibrated_metrics.false_alert_rate:.1f}pp")
    elif calibrated_metrics.false_alert_rate > default_metrics.false_alert_rate:
        regressions.append(f"false alert rate rose by {calibrated_metrics.false_alert_rate - calibrated_metrics.false_alert_rate:.1f}pp")
    
    if calibrated_metrics.missed_runner_rate < default_metrics.missed_runner_rate:
        improvements.append(f"missed runner rate dropped by {default_metrics.missed_runner_rate - calibrated_metrics.missed_runner_rate:.1f}pp")
    elif calibrated_metrics.missed_runner_rate > default_metrics.missed_runner_rate:
        regressions.append(f"missed runner rate rose by {calibrated_metrics.missed_runner_rate - calibrated_metrics.missed_runner_rate:.1f}pp")
    
    if improvements:
        lines.append(f"- **Improvements:** {', '.join(improvements)}.")
    if regressions:
        lines.append(f"- **Regressions:** {', '.join(regressions)}.")
    if not improvements and not regressions:
        lines.append("- No meaningful change detected between default and calibrated scoring.")
    
    lines.extend([
        "",
        "---",
        "*Report generated by scripts/calibration_before_after_validation.py*",
    ])
    
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Report written to {output_path}")


# ── Main ───────────────────────────────────────────────────────────────────

def main():
    print("Building replay dataset...")
    cases = build_replay_dataset(n_per_profile=10)
    print(f"  → {len(cases)} cases created")
    
    # Ensure no calibration weights exist for default run
    weights_path = ROOT / "data" / "agentic" / "historical_calibration_weights.json"
    backup_path = None
    if weights_path.exists():
        backup_path = weights_path.with_suffix(".json.bak")
        weights_path.rename(backup_path)
        print("  → Temporarily moved existing calibration weights")
    
    # Clear any cached calibration in provider modules
    import src.core.agentic.calibration_provider as cp
    cp.DATA_DIR = str(ROOT / "data" / "agentic")
    
    print("Running DEFAULT pipeline...")
    default_results = [run_pipeline(c) for c in cases]
    default_metrics = compute_metrics(cases, default_results)
    
    # Write calibrated weights
    print("Running CALIBRATED pipeline...")
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
    weights_path.parent.mkdir(parents=True, exist_ok=True)
    weights_path.write_text(json.dumps(weights))
    
    # Re-import engines so they pick up the new weights
    # Python caches imports, but each engine calls get_calibration_weights() at init time
    # Since we write the file but modules are cached, we need to reload or re-instantiate
    # The simplest approach: re-instantiate fresh engines by clearing module cache
    for mod_name in list(sys.modules.keys()):
        if "second_leg_engine" in mod_name or "trap_detector" in mod_name or "time_of_day" in mod_name or "float_intel" in mod_name:
            del sys.modules[mod_name]
    
    # Also clear provider cache
    if "src.core.agentic.calibration_provider" in sys.modules:
        del sys.modules["src.core.agentic.calibration_provider"]
    
    # Re-import
    from src.core.agentic.second_leg_engine import SecondLegEngine
    from src.core.agentic.trap_detector import TrapDetector
    from src.core.agentic.time_of_day import TimeOfDayEngine
    from src.core.agentic.float_intel import FloatIntelEngine
    
    calibrated_results = [run_pipeline(c) for c in cases]
    calibrated_metrics = compute_metrics(cases, calibrated_results)
    
    # Restore weights file
    weights_path.unlink()
    if backup_path:
        backup_path.rename(weights_path)
        print("  → Restored original calibration weights")
    
    # Generate report
    report_path = ROOT / "docs" / "v11_before_after_calibration_report.md"
    generate_report(default_metrics, calibrated_metrics, report_path)
    
    # Print summary to console
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Total candidates:         {default_metrics.total_candidates}")
    print(f"Default alerts:           {default_metrics.alerts_generated}")
    print(f"Calibrated alerts:        {calibrated_metrics.alerts_generated}")
    print(f"Default clean cont rate:  {default_metrics.clean_continuation_rate:.1f}%")
    print(f"Calibrated clean cont:    {calibrated_metrics.clean_continuation_rate:.1f}%")
    print(f"Default false alert:      {default_metrics.false_alert_rate:.1f}%")
    print(f"Calibrated false alert:   {calibrated_metrics.false_alert_rate:.1f}%")
    print(f"Default missed runner:    {default_metrics.missed_runner_rate:.1f}%")
    print(f"Calibrated missed runner: {calibrated_metrics.missed_runner_rate:.1f}%")
    print(f"Default avg MFE:          {default_metrics.avg_mfe:.1f}%")
    print(f"Calibrated avg MFE:       {calibrated_metrics.avg_mfe:.1f}%")
    print(f"Default avg MAE:          {default_metrics.avg_mae:.1f}%")
    print(f"Calibrated avg MAE:       {calibrated_metrics.avg_mae:.1f}%")
    print(f"Default prob winners:     {default_metrics.avg_prob_winners:.1f}")
    print(f"Calibrated prob winners:  {calibrated_metrics.avg_prob_winners:.1f}")
    print(f"Default prob losers:      {default_metrics.avg_prob_losers:.1f}")
    print(f"Calibrated prob losers:   {calibrated_metrics.avg_prob_losers:.1f}")


if __name__ == "__main__":
    main()
