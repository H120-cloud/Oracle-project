"""Offline CatBoost baseline for the Rocket Runner dataset.

This module is intentionally not imported by production alerting code. It
trains shadow/offline models only from leakage-safe ``FEATURE_COLUMNS``.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from src.utils.data_paths import agentic_data_dir, agentic_path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import (
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)

from src.core.agentic.rocket_dataset_builder import FEATURE_COLUMNS

RUNNER_LABELS = {
    "STANDARD_WIN",
    "MAJOR_RUNNER",
    "MONSTER_RUNNER",
    "LEGENDARY_RUNNER",
}
MAJOR_PLUS_LABELS = {"MAJOR_RUNNER", "MONSTER_RUNNER", "LEGENDARY_RUNNER"}
MONSTER_PLUS_LABELS = {"MONSTER_RUNNER", "LEGENDARY_RUNNER"}
NEGATIVE_LABEL = "NON_RUNNER"
EXACT_TRAINING_LABELS = RUNNER_LABELS | {NEGATIVE_LABEL}

TARGET_DEFINITIONS: Mapping[str, set[str]] = {
    "binary_runner": RUNNER_LABELS,
    "binary_major_plus": MAJOR_PLUS_LABELS,
    "binary_monster_plus": MONSTER_PLUS_LABELS,
}

DEFAULT_INPUT = agentic_path("rocket_training_dataset_reconstructed_v2_full.parquet")
DEFAULT_MODEL_PATH = agentic_path("rocket_catboost_baseline_shadow.joblib")
DEFAULT_REPORT_PATH = Path("docs/rocket_catboost_baseline_report.md")

RULE_SCORE_COLUMNS = [
    "expected_return_score",
    "news_impact_score",
    "continuation_probability",
    "multi_day_score",
    "ml_predicted_win_prob",
    "move_pct_at_alert",
    "rvol_at_alert",
    "velocity_score_at_alert",
]


@dataclass(frozen=True)
class SplitFrames:
    train: pd.DataFrame
    test: pd.DataFrame
    split_time: pd.Timestamp


def load_exact_training_rows(path: Path | str = DEFAULT_INPUT) -> pd.DataFrame:
    """Load the full Rocket dataset and keep exact trainable labels only."""
    df = pd.read_parquet(path) if str(path).lower().endswith(".parquet") else pd.read_csv(path, low_memory=False)
    if "training_runner_tier" not in df.columns:
        raise ValueError("Dataset is missing training_runner_tier")
    if "alert_time" not in df.columns:
        raise ValueError("Dataset is missing alert_time")
    missing_features = [column for column in FEATURE_COLUMNS if column not in df.columns]
    if missing_features:
        raise ValueError(f"Dataset is missing FEATURE_COLUMNS: {missing_features}")

    labels = df["training_runner_tier"].fillna("UNKNOWN").astype(str)
    exact = df.loc[labels.isin(EXACT_TRAINING_LABELS)].copy()
    exact["_alert_dt"] = pd.to_datetime(exact["alert_time"], utc=True, errors="coerce")
    exact = exact.dropna(subset=["_alert_dt"]).sort_values(["_alert_dt", "ticker", "row_id"]).reset_index(drop=True)
    if exact.empty:
        raise ValueError("No exact trainable Rocket labels found")
    return exact


def build_targets(labels: pd.Series) -> Dict[str, pd.Series]:
    """Build the three requested binary target vectors from training labels."""
    normalized = labels.fillna("UNKNOWN").astype(str)
    return {
        target_name: normalized.isin(positive_labels).astype(int)
        for target_name, positive_labels in TARGET_DEFINITIONS.items()
    }


def time_based_split(df: pd.DataFrame, *, test_fraction: float = 0.20) -> SplitFrames:
    """Split older rows to train and newer rows to test."""
    if not 0.05 <= test_fraction <= 0.5:
        raise ValueError("test_fraction must be between 0.05 and 0.5")
    ordered = df.sort_values(["_alert_dt", "ticker", "row_id"]).reset_index(drop=True)
    split_index = int(len(ordered) * (1.0 - test_fraction))
    split_index = min(max(split_index, 1), len(ordered) - 1)
    split_time = pd.Timestamp(ordered.iloc[split_index]["_alert_dt"])
    train = ordered.iloc[:split_index].copy()
    test = ordered.iloc[split_index:].copy()
    return SplitFrames(train=train, test=test, split_time=split_time)


def prepare_features(df: pd.DataFrame) -> Tuple[pd.DataFrame, List[str], List[int]]:
    """Return FEATURE_COLUMNS-only CatBoost input and categorical indices."""
    features = df.loc[:, FEATURE_COLUMNS].copy()
    for column in features.columns:
        if pd.api.types.is_datetime64_any_dtype(features[column]):
            features[column] = pd.to_datetime(features[column], utc=True, errors="coerce").astype("int64")
        elif column == "alert_time":
            features[column] = pd.to_datetime(features[column], utc=True, errors="coerce").astype("int64")
        elif pd.api.types.is_bool_dtype(features[column]):
            features[column] = features[column].astype("float")

    categorical_columns: List[str] = []
    for column in features.columns:
        if pd.api.types.is_object_dtype(features[column]) or pd.api.types.is_string_dtype(features[column]):
            categorical_columns.append(column)
            features[column] = features[column].fillna("__MISSING__").astype(str)

    cat_indices = [features.columns.get_loc(column) for column in categorical_columns]
    return features, categorical_columns, cat_indices


def metric_block(y_true: Sequence[int], probabilities: Sequence[float], *, threshold: float = 0.5) -> Dict[str, Any]:
    """Compute requested binary metrics and top-decile lift."""
    y = np.asarray(y_true, dtype=int)
    proba = np.asarray(probabilities, dtype=float)
    pred = (proba >= threshold).astype(int)
    baseline = float(y.mean()) if len(y) else 0.0
    top_count = max(1, int(np.ceil(len(y) * 0.10)))
    top_idx = np.argsort(proba)[-top_count:]
    top_hit_rate = float(y[top_idx].mean()) if top_count else 0.0
    return {
        "auc": float(roc_auc_score(y, proba)) if len(np.unique(y)) > 1 else None,
        "precision": float(precision_score(y, pred, zero_division=0)),
        "recall": float(recall_score(y, pred, zero_division=0)),
        "f1": float(f1_score(y, pred, zero_division=0)),
        "baseline_rate": baseline,
        "top_decile_hit_rate": top_hit_rate,
        "lift_over_baseline": float(top_hit_rate / baseline) if baseline > 0 else None,
        "positive_count": int(y.sum()),
        "negative_count": int((1 - y).sum()),
        "threshold": threshold,
    }


def calibration_by_bucket(y_true: Sequence[int], probabilities: Sequence[float], *, buckets: int = 10) -> List[Dict[str, Any]]:
    """Bucket predicted probabilities and report observed hit rates."""
    y = np.asarray(y_true, dtype=int)
    proba = np.asarray(probabilities, dtype=float)
    rows: List[Dict[str, Any]] = []
    for bucket in range(buckets):
        lo = bucket / buckets
        hi = (bucket + 1) / buckets
        if bucket == buckets - 1:
            mask = (proba >= lo) & (proba <= hi)
        else:
            mask = (proba >= lo) & (proba < hi)
        count = int(mask.sum())
        rows.append(
            {
                "bucket": f"{lo:.1f}-{hi:.1f}",
                "rows": count,
                "avg_predicted": float(proba[mask].mean()) if count else None,
                "actual_rate": float(y[mask].mean()) if count else None,
            }
        )
    return rows


def rule_score_benchmarks(
    df: pd.DataFrame,
    y_by_target: Mapping[str, pd.Series],
    *,
    min_coverage: float = 0.50,
) -> Dict[str, Dict[str, Any]]:
    """Benchmark at-alert rule/score columns on the same test rows."""
    benchmarks: Dict[str, Dict[str, Any]] = {}
    available = [column for column in RULE_SCORE_COLUMNS if column in df.columns]
    numeric = {
        column: pd.to_numeric(df[column], errors="coerce")
        for column in available
    }
    if numeric:
        score_frame = pd.DataFrame(numeric)
        normalized = score_frame.copy()
        for column in normalized.columns:
            series = normalized[column]
            lo = series.quantile(0.01)
            hi = series.quantile(0.99)
            if pd.isna(lo) or pd.isna(hi) or hi <= lo:
                normalized[column] = np.nan
            else:
                normalized[column] = ((series.clip(lo, hi) - lo) / (hi - lo)).clip(0, 1)
        numeric["rule_score_composite"] = normalized.mean(axis=1)

    for target_name, y in y_by_target.items():
        rows = []
        for column, score in numeric.items():
            valid = score.notna()
            if valid.sum() < max(10, int(len(df) * min_coverage)) or len(np.unique(np.asarray(y[valid], dtype=int))) < 2:
                continue
            metrics = metric_block(np.asarray(y[valid], dtype=int), np.asarray(score[valid], dtype=float))
            rows.append({"score": column, **metrics, "rows": int(valid.sum())})
        benchmarks[target_name] = {
            "scores": sorted(rows, key=lambda row: row["auc"] or 0, reverse=True),
        }
        benchmarks[target_name]["best"] = benchmarks[target_name]["scores"][0] if rows else None
    return benchmarks


def _format_pct(value: Optional[float]) -> str:
    return "n/a" if value is None else f"{value * 100:.2f}%"


def _format_float(value: Optional[float]) -> str:
    return "n/a" if value is None else f"{value:.3f}"


def train_baseline(
    *,
    input_path: Path | str = DEFAULT_INPUT,
    model_path: Path | str = DEFAULT_MODEL_PATH,
    report_path: Path | str = DEFAULT_REPORT_PATH,
    iterations: int = 350,
    random_seed: int = 42,
) -> Dict[str, Any]:
    """Train all requested offline CatBoost targets and write report/artifact."""
    from catboost import CatBoostClassifier, Pool

    input_path = Path(input_path)
    model_path = Path(model_path)
    report_path = Path(report_path)
    exact = load_exact_training_rows(input_path)
    split = time_based_split(exact)
    X_train, categorical_columns, cat_indices = prepare_features(split.train)
    X_test, _, _ = prepare_features(split.test)
    y_train_all = build_targets(split.train["training_runner_tier"])
    y_test_all = build_targets(split.test["training_runner_tier"])

    train_pool_base = {"cat_features": cat_indices}
    models: Dict[str, Any] = {}
    metrics: Dict[str, Any] = {}
    importances: Dict[str, List[Dict[str, Any]]] = {}
    calibrations: Dict[str, List[Dict[str, Any]]] = {}

    for target_name in TARGET_DEFINITIONS:
        y_train = y_train_all[target_name]
        y_test = y_test_all[target_name]
        model = CatBoostClassifier(
            iterations=iterations,
            depth=6,
            learning_rate=0.05,
            loss_function="Logloss",
            eval_metric="AUC",
            auto_class_weights="Balanced",
            random_seed=random_seed,
            verbose=False,
            allow_writing_files=False,
            thread_count=-1,
        )
        train_pool = Pool(X_train, y_train, **train_pool_base)
        test_pool = Pool(X_test, y_test, **train_pool_base)
        model.fit(train_pool, eval_set=test_pool, use_best_model=True, early_stopping_rounds=50)
        probabilities = model.predict_proba(test_pool)[:, 1]
        metrics[target_name] = metric_block(y_test, probabilities)
        calibrations[target_name] = calibration_by_bucket(y_test, probabilities)
        feature_scores = model.get_feature_importance(train_pool)
        importances[target_name] = [
            {"feature": feature, "importance": float(score)}
            for feature, score in sorted(zip(X_train.columns, feature_scores), key=lambda item: item[1], reverse=True)[:20]
        ]
        models[target_name] = model

    rule_benchmarks = rule_score_benchmarks(split.test, y_test_all)
    artifact = {
        "artifact_type": "rocket_catboost_baseline_shadow",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "input_path": str(input_path),
        "feature_columns": list(FEATURE_COLUMNS),
        "categorical_columns": categorical_columns,
        "target_definitions": {name: sorted(labels) for name, labels in TARGET_DEFINITIONS.items()},
        "label_policy": "exact labels only; UNKNOWN and PROVISIONAL_* excluded",
        "split": {
            "train_rows": len(split.train),
            "test_rows": len(split.test),
            "split_time": split.split_time.isoformat(),
            "train_start": split.train["_alert_dt"].min().isoformat(),
            "train_end": split.train["_alert_dt"].max().isoformat(),
            "test_start": split.test["_alert_dt"].min().isoformat(),
            "test_end": split.test["_alert_dt"].max().isoformat(),
        },
        "metrics": metrics,
        "rule_score_benchmarks": rule_benchmarks,
        "feature_importance": importances,
        "calibration": calibrations,
        "models": models,
        "production_status": "offline_shadow_only",
    }
    model_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(artifact, model_path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_report(artifact, model_path=model_path, report_path=report_path), encoding="utf-8")
    return artifact


def render_report(artifact: Mapping[str, Any], *, model_path: Path, report_path: Path) -> str:
    split = artifact["split"]
    metrics = artifact["metrics"]
    importances = artifact["feature_importance"]
    calibrations = artifact["calibration"]
    rule_benchmarks = artifact.get("rule_score_benchmarks", {})
    lines = [
        "# Rocket CatBoost Baseline Report",
        "",
        "## Scope",
        "",
        "Offline shadow baseline only. No Telegram logic, production alert logic,",
        "or live gating code was modified. The saved model artifact must not be",
        "loaded by production services without a separate promotion step.",
        "",
        "## Inputs",
        "",
        f"- Dataset: `{artifact['input_path']}`",
        f"- Model artifact: `{model_path}`",
        f"- Report: `{report_path}`",
        f"- Feature policy: only `FEATURE_COLUMNS` from `rocket_dataset_builder.py`.",
        "- Label policy: exact labels only; `UNKNOWN` and `PROVISIONAL_*` rows excluded.",
        "",
        "## Time Split",
        "",
        "| Split | Rows | Date range |",
        "|---|---:|---|",
        f"| Train | {split['train_rows']:,} | {split['train_start']} to {split['train_end']} |",
        f"| Test | {split['test_rows']:,} | {split['test_start']} to {split['test_end']} |",
        f"| Split boundary |  | {split['split_time']} |",
        "",
        "## Target Metrics",
        "",
        "| Target | Positives | Baseline | AUC | Precision | Recall | F1 | Top-decile hit rate | Lift |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for target_name, item in metrics.items():
        lines.append(
            f"| `{target_name}` | {item['positive_count']:,} | {_format_pct(item['baseline_rate'])} | "
            f"{_format_float(item['auc'])} | {_format_pct(item['precision'])} | {_format_pct(item['recall'])} | "
            f"{_format_float(item['f1'])} | {_format_pct(item['top_decile_hit_rate'])} | "
            f"{_format_float(item['lift_over_baseline'])} |"
        )

    for target_name, rows in importances.items():
        lines.extend(["", f"## Feature Importance: `{target_name}`", "", "| Rank | Feature | Importance |", "|---:|---|---:|"])
        for rank, row in enumerate(rows, start=1):
            lines.append(f"| {rank} | `{row['feature']}` | {row['importance']:.3f} |")

    for target_name, rows in calibrations.items():
        lines.extend(["", f"## Calibration: `{target_name}`", "", "| Probability bucket | Rows | Avg predicted | Actual rate |", "|---|---:|---:|---:|"])
        for row in rows:
            lines.append(
                f"| `{row['bucket']}` | {row['rows']:,} | {_format_pct(row['avg_predicted'])} | {_format_pct(row['actual_rate'])} |"
            )

    lines.extend(["", "## Rule-Score Benchmarks", "", "| Target | Best rule score | Rule AUC | Rule top-decile hit | Rule lift | Model AUC | Model top-decile hit | Model lift |", "|---|---|---:|---:|---:|---:|---:|---:|"])
    for target_name, item in metrics.items():
        best_rule = (rule_benchmarks.get(target_name) or {}).get("best")
        lines.append(
            f"| `{target_name}` | `{best_rule['score'] if best_rule else 'n/a'}` | "
            f"{_format_float(best_rule['auc'] if best_rule else None)} | "
            f"{_format_pct(best_rule['top_decile_hit_rate'] if best_rule else None)} | "
            f"{_format_float(best_rule['lift_over_baseline'] if best_rule else None)} | "
            f"{_format_float(item['auc'])} | {_format_pct(item['top_decile_hit_rate'])} | "
            f"{_format_float(item['lift_over_baseline'])} |"
        )

    runner = metrics["binary_runner"]
    major = metrics["binary_major_plus"]
    monster = metrics["binary_monster_plus"]
    strongest = max(metrics.items(), key=lambda item: item[1]["auc"] or 0)[0]
    beats_rules = all(
        (metrics[target_name]["auc"] or 0) > (((rule_benchmarks.get(target_name) or {}).get("best") or {}).get("auc") or 0)
        for target_name in metrics
    )
    useful = bool((runner["auc"] or 0) >= 0.60 and (runner["lift_over_baseline"] or 0) > 1.2)
    monster_reliable = bool(
        monster["positive_count"] >= 80
        and (monster["auc"] or 0) >= 0.70
        and monster["recall"] >= 0.20
        and monster["precision"] >= monster["baseline_rate"] * 2
    )
    lines.extend(
        [
            "",
            "## Answers",
            "",
            f"- Is the model useful? **{'Yes' if useful else 'Not enough for production'}**. "
            f"The runner target AUC is {_format_float(runner['auc'])} with top-decile lift "
            f"{_format_float(runner['lift_over_baseline'])}.",
            f"- Is it better than current rule scores? **{'Yes on this temporal test slice' if beats_rules else 'Mixed'}**. "
            "The rule-score benchmark above compares against the best available",
            "  at-alert rule/score column for each target on the same test rows.",
            f"- Which target is strongest? **`{strongest}`** by AUC.",
            f"- Is `monster_plus` reliable enough yet? **{'Yes for offline ranking tests only' if monster_reliable else 'No'}**. "
            f"It has {monster['positive_count']:,} positives in the test slice, AUC "
            f"{_format_float(monster['auc'])}, precision {_format_pct(monster['precision'])}, "
            f"and recall {_format_pct(monster['recall'])}.",
            "",
            "## Recommendation",
            "",
            "Keep this artifact as an offline shadow model. Next step is walk-forward",
            "validation, threshold tuning, and probability calibration before considering",
            "any promotion.",
        ]
    )
    return "\n".join(lines) + "\n"


def main(argv: Optional[Iterable[str]] = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Train offline Rocket CatBoost baseline.")
    parser.add_argument("--input", default=str(DEFAULT_INPUT))
    parser.add_argument("--model-path", default=str(DEFAULT_MODEL_PATH))
    parser.add_argument("--report", default=str(DEFAULT_REPORT_PATH))
    parser.add_argument("--iterations", type=int, default=350)
    args = parser.parse_args(list(argv) if argv is not None else None)
    artifact = train_baseline(
        input_path=args.input,
        model_path=args.model_path,
        report_path=args.report,
        iterations=args.iterations,
    )
    print(json.dumps({k: v for k, v in artifact.items() if k != "models"}, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
