"""
V19.1 Real Historical Validation — Run on actual AgenticOutcome records

Loads real outcomes from data/agentic/outcomes.json (or learning.json),
trains the V19.1 ML model, and evaluates the same 3 scenarios.

Usage:
    python scripts/v19_1_real_validation.py

Output:
    docs/v19_1_real_validation_report.md
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.core.agentic.ml_advisory import MLAdvisoryEngine
from src.core.agentic.models import AgenticOutcome, OutcomeClass

# ── Load real outcomes ────────────────────────────────────────────────

DATA_PATHS = [
    project_root / "data" / "agentic" / "outcomes.json",
    project_root / "data" / "agentic" / "learning.json",
    project_root / "data" / "agentic" / "agentic_outcomes.json",
]


def load_outcomes() -> list[AgenticOutcome]:
    """Load historical outcomes from any available data file."""
    for p in DATA_PATHS:
        if not p.exists():
            continue
        try:
            with open(p) as f:
                data = json.load(f)
            # Handle list of dicts
            if isinstance(data, list):
                outcomes = [AgenticOutcome(**d) for d in data if isinstance(d, dict)]
            elif isinstance(data, dict) and "outcomes" in data:
                outcomes = [AgenticOutcome(**d) for d in data["outcomes"]]
            else:
                continue
            print(f"Loaded {len(outcomes)} outcomes from {p}")
            return outcomes
        except Exception as exc:
            print(f"Failed to load {p}: {exc}")
            continue
    return []


# ── Scenario Evaluators ─────────────────────────────────────────────

def scenario_rule_only(outcomes: list[AgenticOutcome]) -> dict:
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
        "precision": precision,
        "recall": recall,
        "fpr": fpr,
        "missed_runner_rate": missed_rate,
        "avg_mfe": avg_mfe,
        "avg_mae": avg_mae,
        "sharpe_like": sharpe,
    }


def scenario_ml_soft_filter(outcomes: list[AgenticOutcome], ml_engine: MLAdvisoryEngine) -> dict:
    """Use ML optimal threshold to filter borderline candidates."""
    from scripts.v19_ml_impact_validation import _predict_from_outcome

    threshold = getattr(ml_engine, "optimal_threshold", 0.5)
    alerts = []
    for o in outcomes:
        pred = _predict_from_outcome(ml_engine, o)
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
        "scenario": f"Rule + ML Soft Filter (threshold={threshold:.2f})",
        "total_alerted": total_alerted,
        "precision": precision,
        "recall": recall,
        "fpr": fpr,
        "missed_runner_rate": missed_rate,
        "avg_mfe": avg_mfe,
        "avg_mae": avg_mae,
        "sharpe_like": sharpe,
    }


# ── Main ────────────────────────────────────────────────────────────

def main():
    print("=" * 70)
    print("V19.1 Real Historical Validation")
    print("=" * 70)

    outcomes = load_outcomes()
    if len(outcomes) < 100:
        print(f"\nINSUFFICIENT DATA: {len(outcomes)} outcomes (need ≥100)")
        print("Run the Agentic system longer to accumulate outcomes.")
        return

    # Chronological split: first 30% train, last 70% test
    split_idx = int(len(outcomes) * 0.3)
    train_outcomes = outcomes[:split_idx]
    test_outcomes = outcomes[split_idx:]

    print(f"\nTrain: {len(train_outcomes)} | Test: {len(test_outcomes)}")

    # Train ML
    print("\nTraining V19.1 ML model on real outcomes...")
    ml_engine = MLAdvisoryEngine()
    try:
        version = ml_engine.train(train_outcomes)
    except Exception as exc:
        print(f"Training failed: {exc}")
        print("This usually means all outcomes have the same class label (no variance).")
        print("Continue running Agentic to accumulate diverse outcomes.")
        return
    if version is None:
        print("Training returned None — insufficient samples or quality.")
        return

    print(f"Trained version: {version.version}")
    print(f"AUC: {version.metrics.auc_roc:.3f} | F-beta: {version.metrics.fbeta:.3f}")
    print(f"Optimal threshold: {version.optimal_threshold:.3f}")

    # Evaluate
    s1 = scenario_rule_only(test_outcomes)
    s3 = scenario_ml_soft_filter(test_outcomes, ml_engine)

    print("\n" + "=" * 70)
    print("RESULTS (Real Data)")
    print("=" * 70)
    for s in [s1, s3]:
        print(f"\n{s['scenario']}")
        print(f"  Alerts: {s['total_alerted']} | Precision: {s['precision']:.1%} | Recall: {s['recall']:.1%}")
        print(f"  FPR: {s['fpr']:.1%} | Missed: {s['missed_runner_rate']:.1%}")
        print(f"  Avg MFE: {s['avg_mfe']:.2f}% | Avg MAE: {s['avg_mae']:.2f}% | Sharpe: {s['sharpe_like']:.2f}")

    # Improvement
    baseline = s1["sharpe_like"]
    soft = s3["sharpe_like"]
    improvement = (soft - baseline) / baseline if baseline > 0 else 0.0
    print(f"\nImprovement: {improvement:+.1%}")

    # Generate report
    report_path = project_root / "docs" / "v19_1_real_validation_report.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    report = f"""# V19.1 Real Historical Validation Report

**Generated:** {now}
**Data source:** Actual AgenticOutcome records
**Train samples:** {len(train_outcomes)} | **Test samples:** {len(test_outcomes)}

---

## Results

| Scenario | Alerts | Precision | Recall | FPR | Missed | Avg MFE | Avg MAE | Sharpe |
|----------|--------|-----------|--------|-----|--------|---------|---------|--------|
| {s1['scenario']} | {s1['total_alerted']} | {s1['precision']:.1%} | {s1['recall']:.1%} | {s1['fpr']:.1%} | {s1['missed_runner_rate']:.1%} | {s1['avg_mfe']:.1f}% | {s1['avg_mae']:.1f}% | {s1['sharpe_like']:.2f} |
| {s3['scenario']} | {s3['total_alerted']} | {s3['precision']:.1%} | {s3['recall']:.1%} | {s3['fpr']:.1%} | {s3['missed_runner_rate']:.1%} | {s3['avg_mfe']:.1f}% | {s3['avg_mae']:.1f}% | {s3['sharpe_like']:.2f} |

## Improvement

- **Baseline Sharpe:** {baseline:.2f}
- **Soft Filter Sharpe:** {soft:.2f}
- **Improvement:** {improvement:+.1%}

## Model Info

- **Version:** {version.version}
- **AUC:** {version.metrics.auc_roc:.3f}
- **F-beta:** {version.metrics.fbeta:.3f}
- **Brier:** {version.metrics.brier_score:.3f}
- **Optimal threshold:** {version.optimal_threshold:.3f}

---

*Generated by scripts/v19_1_real_validation.py*
"""
    report_path.write_text(report, encoding="utf-8")
    print(f"\nReport saved to {report_path}")


if __name__ == "__main__":
    main()
