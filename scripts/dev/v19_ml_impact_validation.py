"""
V19 ML Advisory Impact Validation — Simulation

Compares three scenarios:
  1. Rule-only Agentic (baseline)
  2. Agentic + ML advisory (shadow predictions)
  3. Agentic + ML soft filter on borderline candidates (60-80 prob)

Focus: candidates with final probability 60-80
Metrics: precision, recall, FPR, missed runner rate, MFE, MAE,
         calibration curve, predicted vs actual winners/losers,
         SHAP feature consistency.

Output: docs/v19_ml_impact_validation.md

NOTE: ML remains advisory-only unless this validation proves >10% improvement
      in risk-adjusted returns (Sharpe-like metric: avg MFE / avg MAE).
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.core.agentic.ml_advisory import MLAdvisoryEngine, FeatureEngineer
from src.core.agentic.models import (
    AgenticOutcome,
    CatalystInfo,
    CatalystType,
    ConfidenceLevel,
    EntryQuality,
    EntryTimingResult,
    EntryTimingState,
    FailureVelocityResult,
    FloatCategory,
    FloatIntel,
    MLPredictionResult,
    MomentumSnapshot,
    MomentumState,
    OutcomeClass,
    QualitySeparatorResult,
    SecondLegResult,
    TimeOfDayResult,
    TradingSession,
    TrapResult,
)

# ── Constants ─────────────────────────────────────────────────────────

random.seed(42)
np.random.seed(42)

N_CANDIDATES = 500
N_TRAIN = 150
N_TEST = 350
BORDERLINE_LOW = 60.0
BORDERLINE_HIGH = 80.0
SOFT_FILTER_THRESHOLD = 0.40  # ML continuation_prob below this suppresses borderline alert
MIN_SAMPLE_PER_SCENARIO = 30
SHARPE_IMPROVEMENT_THRESHOLD = 0.10

# ── Synthetic Data Generator ─────────────────────────────────────────


def _make_outcome(i: int, bias_good: bool = False) -> AgenticOutcome:
    """Generate a synthetic outcome with realistic feature correlations."""
    # Base traits that determine true outcome
    true_prob = random.uniform(30, 95)
    true_trap = random.uniform(10, 90)
    true_vol = random.uniform(20, 90)
    true_catalyst = random.uniform(20, 90)
    has_hl = random.random() < 0.5
    vwap_ok = random.random() < 0.6

    # True label: good candidates have high prob, low trap, high volume, vwap held, HL
    good_score = (
        true_prob * 0.35
        - true_trap * 0.25
        + true_vol * 0.20
        + (20 if has_hl else 0)
        + (15 if vwap_ok else 0)
        + true_catalyst * 0.10
    )
    # Add noise
    good_score += random.gauss(0, 8)
    is_good = good_score > 50

    # Final probability reported by rule system (noisy version of true_prob)
    reported_prob = true_prob + random.gauss(0, 5)
    reported_prob = max(20, min(98, reported_prob))

    # MFE / MAE
    if is_good:
        mfe = random.uniform(5, 35)
        mae = random.uniform(0.5, 4)
        outcome = random.choice([OutcomeClass.CLEAN_CONTINUATION, OutcomeClass.PARTIAL])
    else:
        mfe = random.uniform(0.5, 6)
        mae = random.uniform(3, 12)
        outcome = random.choice([OutcomeClass.FAILED, OutcomeClass.DEAD])

    # Probability adjustment: good outcomes slightly boost reported prob
    if is_good and random.random() < 0.3:
        reported_prob += random.uniform(2, 8)

    # V19.1 — Market regime features (correlated with outcome quality)
    spy_trend = random.uniform(-3, 5) if is_good else random.uniform(-5, 2)
    vix = random.uniform(12, 22) if is_good else random.uniform(20, 35)
    sector_rsi = random.uniform(55, 75) if is_good else random.uniform(35, 55)
    market_breadth = random.uniform(60, 85) if is_good else random.uniform(30, 55)

    # V19.1 — Time & volume profile features
    minutes_since = random.uniform(5, 45) if is_good else random.uniform(30, 90)
    vol_slope = random.uniform(0.5, 3) if is_good else random.uniform(-2, 1)
    float_turnover = random.uniform(0.1, 0.8) if is_good else random.uniform(0.5, 2.5)
    rel_vol_sector = random.uniform(1.5, 5) if is_good else random.uniform(0.5, 2)

    return AgenticOutcome(
        candidate_id=f"sim-{i}",
        ticker=f"SIM{i:03d}",
        outcome_class=outcome,
        entry_price=10.0,
        peak_price=10 + mfe / 100 * 10,
        exit_price=10 + (mfe - mae) / 100 * 10,
        max_favorable_excursion_pct=mfe,
        max_adverse_excursion_pct=mae,
        vwap_held=vwap_ok,
        state=random.choice([
            MomentumState.CONSOLIDATION,
            MomentumState.SECOND_LEG_FORMING,
            MomentumState.CONTINUATION_CONFIRMED,
            MomentumState.FAILED,
        ]).value,
        probability=reported_prob,
        trap_risk=true_trap,
        volume_persistence=true_vol,
        higher_low_formed=has_hl,
        float_category=random.choice([FloatCategory.ULTRA_LOW, FloatCategory.LOW, FloatCategory.NORMAL]).value,
        catalyst_type=random.choice(list(CatalystType)).value,
        catalyst_strength=true_catalyst,
        time_of_day_session=random.choice(list(TradingSession)).value,
        entry_quality=random.choice(list(EntryQuality)).value,
        rejected=random.random() < 0.05,
        alertable=reported_prob >= 70 and true_trap < 65 and not (reported_prob < 80 and true_trap > 55),
        rejection_reasons=[],
        # V19.1 — New features
        spy_trend_5d=spy_trend,
        vix_level=vix,
        sector_rsi=sector_rsi,
        market_breadth=market_breadth,
        minutes_since_spike=minutes_since,
        volume_profile_slope=vol_slope,
        float_turnover_pct=float_turnover,
        relative_volume_vs_sector=rel_vol_sector,
    )


def generate_dataset(n: int, bias_good: bool = False) -> list[AgenticOutcome]:
    return [_make_outcome(i, bias_good) for i in range(n)]


# ── Scenario Evaluators ───────────────────────────────────────────────


def scenario_rule_only(outcomes: list[AgenticOutcome]) -> dict:
    """Baseline: alerts strictly based on rule-based `alertable` flag."""
    alerts = [o for o in outcomes if o.alertable]
    positives = [o for o in alerts if o.outcome_class in (OutcomeClass.CLEAN_CONTINUATION, OutcomeClass.PARTIAL)]
    negatives = [o for o in alerts if o.outcome_class not in (OutcomeClass.CLEAN_CONTINUATION, OutcomeClass.PARTIAL)]

    all_good = [o for o in outcomes if o.outcome_class in (OutcomeClass.CLEAN_CONTINUATION, OutcomeClass.PARTIAL)]
    missed = [o for o in all_good if not o.alertable]

    total_alerted = len(alerts)
    total_good = len(all_good)
    precision = len(positives) / total_alerted if total_alerted else 0.0
    recall = len(positives) / total_good if total_good else 0.0
    fpr = len(negatives) / total_alerted if total_alerted else 0.0
    missed_rate = len(missed) / total_good if total_good else 0.0
    avg_mfe = np.mean([o.max_favorable_excursion_pct for o in alerts]) if alerts else 0.0
    avg_mae = np.mean([o.max_adverse_excursion_pct for o in alerts]) if alerts else 0.0
    sharpe = avg_mfe / avg_mae if avg_mae > 0 else 0.0

    return {
        "scenario": "Rule-only",
        "total_alerted": total_alerted,
        "total_good": total_good,
        "precision": precision,
        "recall": recall,
        "fpr": fpr,
        "missed_runner_rate": missed_rate,
        "avg_mfe": avg_mfe,
        "avg_mae": avg_mae,
        "sharpe_like": sharpe,
        "positives": len(positives),
        "negatives": len(negatives),
    }


def scenario_ml_advisory(outcomes: list[AgenticOutcome], ml_engine: MLAdvisoryEngine) -> dict:
    """Scenario 2: ML runs in shadow, rules unchanged."""
    # Same as rule-only for alert decisions
    result = scenario_rule_only(outcomes)
    result["scenario"] = "Rule + ML Advisory (Shadow)"

    # Add ML prediction stats for reporting
    preds = []
    for o in outcomes:
        # Reconstruct minimal candidate from outcome
        # Use outcome fields as proxy
        pred = _predict_from_outcome(ml_engine, o)
        preds.append(pred)

    ml_winners = [p for p, o in zip(preds, outcomes) if p.continuation_prob >= 0.5]
    actual_winners = [o for o in outcomes if o.outcome_class in (OutcomeClass.CLEAN_CONTINUATION, OutcomeClass.PARTIAL)]
    ml_winners_actual = sum(1 for p, o in zip(preds, outcomes) if p.continuation_prob >= 0.5 and o.outcome_class in (OutcomeClass.CLEAN_CONTINUATION, OutcomeClass.PARTIAL))
    ml_losers_actual = sum(1 for p, o in zip(preds, outcomes) if p.continuation_prob < 0.5 and o.outcome_class not in (OutcomeClass.CLEAN_CONTINUATION, OutcomeClass.PARTIAL))

    result["ml_predicted_winners"] = len(ml_winners)
    result["actual_winners"] = len(actual_winners)
    result["ml_winners_correct"] = ml_winners_actual
    result["ml_losers_correct"] = ml_losers_actual
    result["ml_accuracy"] = (ml_winners_actual + ml_losers_actual) / len(outcomes) if outcomes else 0.0

    return result


def scenario_ml_soft_filter(outcomes: list[AgenticOutcome], ml_engine: MLAdvisoryEngine) -> dict:
    """Scenario 3: ML suppresses borderline (60-80 prob) alerts with low continuation_prob."""
    alerts = []
    for o in outcomes:
        is_borderline = BORDERLINE_LOW <= o.probability <= BORDERLINE_HIGH
        if not is_borderline:
            # Non-borderline: use rule-based decision
            if o.alertable:
                alerts.append(o)
            continue

        # Borderline: apply ML soft filter using dynamic optimal threshold
        pred = _predict_from_outcome(ml_engine, o)
        threshold = getattr(ml_engine, "optimal_threshold", SOFT_FILTER_THRESHOLD)
        if pred.continuation_prob >= threshold and o.alertable:
            alerts.append(o)

    positives = [o for o in alerts if o.outcome_class in (OutcomeClass.CLEAN_CONTINUATION, OutcomeClass.PARTIAL)]
    negatives = [o for o in alerts if o.outcome_class not in (OutcomeClass.CLEAN_CONTINUATION, OutcomeClass.PARTIAL)]

    all_good = [o for o in outcomes if o.outcome_class in (OutcomeClass.CLEAN_CONTINUATION, OutcomeClass.PARTIAL)]
    missed = [o for o in all_good if o not in alerts]

    total_alerted = len(alerts)
    total_good = len(all_good)
    precision = len(positives) / total_alerted if total_alerted else 0.0
    recall = len(positives) / total_good if total_good else 0.0
    fpr = len(negatives) / total_alerted if total_alerted else 0.0
    missed_rate = len(missed) / total_good if total_good else 0.0
    avg_mfe = np.mean([o.max_favorable_excursion_pct for o in alerts]) if alerts else 0.0
    avg_mae = np.mean([o.max_adverse_excursion_pct for o in alerts]) if alerts else 0.0
    sharpe = avg_mfe / avg_mae if avg_mae > 0 else 0.0

    return {
        "scenario": f"Rule + ML Soft Filter (borderline {BORDERLINE_LOW:.0f}-{BORDERLINE_HIGH:.0f}, threshold={threshold:.2f})",
        "total_alerted": total_alerted,
        "total_good": total_good,
        "precision": precision,
        "recall": recall,
        "fpr": fpr,
        "missed_runner_rate": missed_rate,
        "avg_mfe": avg_mfe,
        "avg_mae": avg_mae,
        "sharpe_like": sharpe,
        "positives": len(positives),
        "negatives": len(negatives),
    }


def _predict_from_outcome(ml_engine: MLAdvisoryEngine, outcome: AgenticOutcome):
    """Create a minimal proxy candidate for ML prediction from an outcome."""
    # The ml_advisory engine expects an AgenticCandidate but uses specific fields.
    # We create a lightweight proxy that exposes the needed attributes.
    class _ProxyCandidate:
        def __init__(self, o: AgenticOutcome):
            self.final_probability = o.probability
            self.trap = _ProxyObj(trap_risk_score=o.trap_risk)
            self.momentum = _ProxyObj(
                volume_persistence_pct=o.volume_persistence,
                higher_low_formed=o.higher_low_formed,
                vwap_reclaimed=o.vwap_held,
                state=MomentumState(o.state) if o.state else MomentumState.CONSOLIDATION,
            )
            self.catalyst = _ProxyObj(
                strength_score=o.catalyst_strength,
                catalyst_type=CatalystType(o.catalyst_type) if o.catalyst_type else CatalystType.EARNINGS,
            )
            self.entry_timing = _ProxyObj(
                quality=EntryQuality(o.entry_quality) if o.entry_quality else EntryQuality.IDEAL,
            )
            self.time_of_day = _ProxyObj(
                session=TradingSession(o.time_of_day_session) if o.time_of_day_session else TradingSession.OPEN,
            )
            self.rejected = o.rejected
            self.alertable = o.alertable
            self.float_intel = _ProxyObj(
                float_category=FloatCategory(o.float_category) if o.float_category else FloatCategory.NORMAL,
            )
            self.quality_separator = _ProxyObj(quality_decision="allow")
            self.second_leg = _ProxyObj(probability=o.probability)
            # V19.1 — New features
            self.spy_trend_5d = getattr(o, "spy_trend_5d", 0.0)
            self.vix_level = getattr(o, "vix_level", 20.0)
            self.sector_rsi = getattr(o, "sector_rsi", 50.0)
            self.market_breadth = getattr(o, "market_breadth", 50.0)
            self.minutes_since_spike = getattr(o, "minutes_since_spike", 30.0)
            self.volume_profile_slope = getattr(o, "volume_profile_slope", 0.0)
            self.float_turnover_pct = getattr(o, "float_turnover_pct", 0.0)
            self.relative_volume_vs_sector = getattr(o, "relative_volume_vs_sector", 1.0)

    class _ProxyObj:
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)

    proxy = _ProxyCandidate(outcome)
    return ml_engine.predict(proxy)


# ── Calibration Analysis ────────────────────────────────────────────


def calibration_analysis(outcomes: list[AgenticOutcome], ml_engine: MLAdvisoryEngine) -> list[dict]:
    """Bin ML predicted probabilities and compare to actual win rates."""
    bins = {i: {"preds": [], "actuals": []} for i in range(10)}
    for o in outcomes:
        pred = _predict_from_outcome(ml_engine, o)
        bin_idx = min(9, int(pred.continuation_prob * 10))
        bins[bin_idx]["preds"].append(pred.continuation_prob)
        is_win = o.outcome_class in (OutcomeClass.CLEAN_CONTINUATION, OutcomeClass.PARTIAL)
        bins[bin_idx]["actuals"].append(1.0 if is_win else 0.0)

    result = []
    for i in range(10):
        b = bins[i]
        if not b["actuals"]:
            continue
        avg_pred = np.mean(b["preds"])
        avg_actual = np.mean(b["actuals"])
        result.append({
            "bin": f"{i*10}-{(i+1)*10}%",
            "n": len(b["actuals"]),
            "avg_predicted_prob": round(avg_pred, 3),
            "actual_win_rate": round(avg_actual, 3),
            "calibration_error": round(abs(avg_pred - avg_actual), 3),
        })
    return result


# ── SHAP Feature Consistency ───────────────────────────────────────


def shap_consistency(outcomes: list[AgenticOutcome], ml_engine: MLAdvisoryEngine) -> dict:
    """Aggregate SHAP features across predictions to find most consistent drivers."""
    feature_counts: dict[str, int] = {}
    feature_direction: dict[str, list[float]] = {}

    for o in outcomes[:100]:  # sample for speed
        pred = _predict_from_outcome(ml_engine, o)
        for sf in pred.top_shap_features:
            feat = sf["feature"]
            feature_counts[feat] = feature_counts.get(feat, 0) + 1
            feature_direction.setdefault(feat, []).append(sf["shap_value"])

    # Top 5 most frequently appearing SHAP features
    top = sorted(feature_counts.items(), key=lambda x: x[1], reverse=True)[:5]
    result = {}
    for feat, count in top:
        vals = feature_direction[feat]
        result[feat] = {
            "appearance_rate": round(count / min(100, len(outcomes)), 2),
            "avg_shap": round(np.mean(vals), 4),
            "direction": "positive" if np.mean(vals) > 0 else "negative",
        }
    return result


# ── Main ─────────────────────────────────────────────────────────────


def main():
    print("=" * 70)
    print("V19 ML Advisory Impact Validation — Simulation")
    print("=" * 70)

    # 1. Generate data
    print(f"\n[1/6] Generating {N_CANDIDATES} synthetic outcomes...")
    all_outcomes = generate_dataset(N_CANDIDATES)
    train_outcomes = all_outcomes[:N_TRAIN]
    test_outcomes = all_outcomes[N_TRAIN:]
    print(f"      Train: {len(train_outcomes)} | Test: {len(test_outcomes)}")

    # 2. Train ML model
    print("\n[2/6] Training ML advisory engine...")
    ml_engine = MLAdvisoryEngine()
    version = ml_engine.train(train_outcomes)
    if version is None:
        print("      WARNING: Training returned None (insufficient samples or quality).")
        print("      Running with fallback mode...")
    else:
        print(f"      Trained version: {version.version}")
        print(f"      Metrics — AUC: {version.metrics.auc_roc:.3f}, F-beta: {version.metrics.fbeta:.3f}, Brier: {version.metrics.brier_score:.3f}")

    # 3. Run scenarios
    print("\n[3/6] Evaluating scenarios...")
    s1 = scenario_rule_only(test_outcomes)
    s2 = scenario_ml_advisory(test_outcomes, ml_engine)
    s3 = scenario_ml_soft_filter(test_outcomes, ml_engine)

    scenarios = [s1, s2, s3]

    # 4. Focus on borderline 60-80
    borderline = [o for o in test_outcomes if BORDERLINE_LOW <= o.probability <= BORDERLINE_HIGH]
    print(f"\n[4/6] Borderline candidates ({BORDERLINE_LOW:.0f}-{BORDERLINE_HIGH:.0f}): {len(borderline)}")
    b1 = scenario_rule_only(borderline)
    b2 = scenario_ml_advisory(borderline, ml_engine)
    b3 = scenario_ml_soft_filter(borderline, ml_engine)
    borderline_results = [b1, b2, b3]

    # 5. Calibration + SHAP
    print("\n[5/6] Calibration analysis...")
    calib = calibration_analysis(test_outcomes, ml_engine)
    print("      Done.")

    print("\n[6/6] SHAP feature consistency...")
    shap_cons = shap_consistency(test_outcomes, ml_engine)
    print("      Done.")

    # 6. Generate report
    print("\n[7/7] Generating report...")
    _generate_report(scenarios, borderline_results, calib, shap_cons, version, train_outcomes, test_outcomes)
    print("      Report saved to docs/v19_ml_impact_validation.md")

    # 7. Summary
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    for s in scenarios:
        print(f"\n{s['scenario']}")
        print(f"  Alerts: {s['total_alerted']} | Precision: {s['precision']:.1%} | Recall: {s['recall']:.1%}")
        print(f"  FPR: {s['fpr']:.1%} | Missed: {s['missed_runner_rate']:.1%}")
        print(f"  Avg MFE: {s['avg_mfe']:.2f}% | Avg MAE: {s['avg_mae']:.2f}% | Sharpe: {s['sharpe_like']:.2f}")

    # Recommendation
    baseline_sharpe = s1["sharpe_like"]
    soft_sharpe = s3["sharpe_like"]
    improvement = (soft_sharpe - baseline_sharpe) / baseline_sharpe if baseline_sharpe > 0 else 0.0

    print(f"\n{'=' * 70}")
    print("RECOMMENDATION")
    print(f"{'=' * 70}")
    if improvement >= SHARPE_IMPROVEMENT_THRESHOLD:
        print(f"ML soft filter shows {improvement:.1%} improvement in risk-adjusted returns.")
        print("RECOMMENDATION: Approve ML soft filter for live use after manual review.")
    elif improvement > 0:
        print(f"ML soft filter shows {improvement:.1%} improvement (below {SHARPE_IMPROVEMENT_THRESHOLD:.0%} threshold).")
        print("RECOMMENDATION: Continue shadow mode. Collect more outcomes before promotion.")
    else:
        print(f"ML soft filter shows {improvement:.1%} change (no improvement).")
        print("RECOMMENDATION: Keep ML advisory-only. Do NOT use as filter.")

    print(f"\n{'=' * 70}")
    print("ML remains ADVISORY-ONLY pending validation proof.")
    print(f"{'=' * 70}")


def _generate_report(scenarios, borderline, calibration, shap_cons, version, train_outcomes, test_outcomes):
    report_path = project_root / "docs" / "v19_ml_impact_validation.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    def _fmt_scenario(s):
        return f"""| {s['scenario']} | {s['total_alerted']} | {s['precision']:.1%} | {s['recall']:.1%} | {s['fpr']:.1%} | {s['missed_runner_rate']:.1%} | {s['avg_mfe']:.1f}% | {s['avg_mae']:.1f}% | {s['sharpe_like']:.2f} |"""

    def _fmt_borderline(s):
        return f"""| {s['scenario']} | {s['total_alerted']} | {s['precision']:.1%} | {s['recall']:.1%} | {s['fpr']:.1%} | {s['missed_runner_rate']:.1%} | {s['avg_mfe']:.1f}% | {s['avg_mae']:.1f}% | {s['sharpe_like']:.2f} |"""

    calib_rows = "\n".join(
        f"| {c['bin']} | {c['n']} | {c['avg_predicted_prob']:.1%} | {c['actual_win_rate']:.1%} | {c['calibration_error']:.3f} |"
        for c in calibration
    )

    shap_rows = "\n".join(
        f"| {feat} | {info['appearance_rate']:.0%} | {info['avg_shap']:+.4f} | {info['direction']} |"
        for feat, info in shap_cons.items()
    )

    ml_info = "No model trained (insufficient data)"
    if version:
        ml_info = f"""
**Model:** {version.version}
**Hash:** {version.model_hash[:16]}...
**AUC-ROC:** {version.metrics.auc_roc:.3f}
**F-beta (0.5):** {version.metrics.fbeta:.3f}
**Brier Score:** {version.metrics.brier_score:.3f}
**N Train:** {version.metrics.n_train} | **N Test:** {version.metrics.n_test}
"""

    baseline_sharpe = scenarios[0]["sharpe_like"]
    soft_sharpe = scenarios[2]["sharpe_like"]
    improvement = (soft_sharpe - baseline_sharpe) / baseline_sharpe if baseline_sharpe > 0 else 0.0

    if improvement >= SHARPE_IMPROVEMENT_THRESHOLD:
        rec = "**APPROVE** — ML soft filter shows sufficient improvement to promote from advisory to active filter. Manual review still required."
    elif improvement > 0:
        rec = "**HOLD** — Improvement observed but below threshold. Continue shadow mode and collect more outcomes."
    else:
        rec = "**REJECT** — No improvement observed. Keep ML strictly advisory-only."

    report = f"""# V19 ML Advisory Impact Validation Report

**Generated:** {now}
**Methodology:** Synthetic simulation with realistic feature correlations
**Train samples:** {len(train_outcomes)} | **Test samples:** {len(test_outcomes)}

---

## Executive Summary

This report compares three Agentic scenarios to determine whether the V19 ML advisory layer should remain advisory-only or be promoted to an active soft filter on borderline candidates.

**Key Finding:** The ML soft filter scenario{' **improves**' if improvement > 0 else ' does **not improve**'} risk-adjusted returns by {abs(improvement):.1%} vs rule-only baseline.

**Recommendation:** {rec}

---

## Scenarios Compared

1. **Rule-only** — Alerts based purely on existing rule-based thresholds (baseline)
2. **Rule + ML Advisory (Shadow)** — ML predictions generated but do not affect alert decisions
3. **Rule + ML Soft Filter** — For borderline candidates ({BORDERLINE_LOW:.0f}-{BORDERLINE_HIGH:.0f} probability), ML suppresses alerts when `continuation_prob < {SOFT_FILTER_THRESHOLD}`

---

## Full Dataset Results (n={len(test_outcomes)})

| Scenario | Alerts | Precision | Recall | FPR | Missed | Avg MFE | Avg MAE | Sharpe |
|----------|--------|-----------|--------|-----|--------|---------|---------|--------|
{_fmt_scenario(scenarios[0])}
{_fmt_scenario(scenarios[1])}
{_fmt_scenario(scenarios[2])}

**Sharpe-like** = Avg MFE / Avg MAE (higher is better — more upside per unit downside)

---

## Borderline Candidates Focus ({BORDERLINE_LOW:.0f}-{BORDERLINE_HIGH:.0f} prob only, n={len([o for o in test_outcomes if BORDERLINE_LOW <= o.probability <= BORDERLINE_HIGH])})

| Scenario | Alerts | Precision | Recall | FPR | Missed | Avg MFE | Avg MAE | Sharpe |
|----------|--------|-----------|--------|-----|--------|---------|---------|--------|
{_fmt_borderline(borderline[0])}
{_fmt_borderline(borderline[1])}
{_fmt_borderline(borderline[2])}

---

## ML Model Performance

{ml_info}

---

## Probability Calibration

| Bin | N | Avg Predicted | Actual Win Rate | Error |
|-----|---|---------------|-----------------|-------|
{calib_rows}

**Interpretation:** Low calibration error means predicted probabilities match actual frequencies. If predicted 70% and actual is 72%, the model is well-calibrated.

---

## SHAP Feature Consistency

| Feature | Appearance Rate | Avg SHAP | Direction |
|---------|----------------|----------|-----------|
{shap_rows}

**Interpretation:** Features with high appearance rates and consistent direction are reliable drivers. Features with mixed direction (some positive, some negative SHAP values) are context-dependent.

---

## ML Predicted vs Actual Winners

| Metric | Value |
|--------|-------|
| ML predicted winners (≥50% prob) | {scenarios[1].get('ml_predicted_winners', 0)} |
| Actual winners | {scenarios[1].get('actual_winners', 0)} |
| ML winners that were actual winners | {scenarios[1].get('ml_winners_correct', 0)} |
| ML losers that were actual losers | {scenarios[1].get('ml_losers_correct', 0)} |
| Overall accuracy | {scenarios[1].get('ml_accuracy', 0):.1%} |

---

## Statistical Safety

- **Improvement threshold:** {SHARPE_IMPROVEMENT_THRESHOLD:.0%} risk-adjusted return improvement required for promotion
- **Actual improvement:** {improvement:.1%}
- **Result:** {'PASSES threshold' if improvement >= SHARPE_IMPROVEMENT_THRESHOLD else 'BELOW threshold'}

---

## Conclusion

{rec}

ML remains **advisory-only** until validation unequivocally proves improvement.

---

*Report generated by scripts/v19_ml_impact_validation.py*
"""

    report_path.write_text(report, encoding="utf-8")


if __name__ == "__main__":
    main()
