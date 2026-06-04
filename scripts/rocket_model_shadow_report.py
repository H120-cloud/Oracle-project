from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Iterable, Optional

import pandas as pd

DEFAULT_INPUT = Path("data/agentic/rocket_model_shadow_predictions.jsonl")
DEFAULT_OUTPUT = Path("docs/rocket_model_shadow_report.md")
DEFAULT_OUTCOME_PATHS = [
    Path("data/agentic/news_momentum_telegram_alerts.json"),
    Path("data/agentic/pre_news_outcomes.json"),
    Path("data/agentic/news_impact_outcomes.json"),
]

MAJOR_PLUS = {"MAJOR_RUNNER", "MONSTER_RUNNER", "LEGENDARY_RUNNER"}
MONSTER_PLUS = {"MONSTER_RUNNER", "LEGENDARY_RUNNER"}


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def _parse_dt(value: Any) -> Optional[pd.Timestamp]:
    if value is None:
        return None
    ts = pd.to_datetime(value, utc=True, errors="coerce")
    if pd.isna(ts):
        return None
    return ts


def _load_outcome_rows(paths: Iterable[Path]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in paths:
        if not path.exists():
            continue
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(raw, dict):
            for key in ("outcomes", "alerts", "records"):
                values = raw.get(key)
                if isinstance(values, list):
                    rows.extend(row for row in values if isinstance(row, dict))
        elif isinstance(raw, list):
            rows.extend(row for row in raw if isinstance(row, dict))
    return rows


def _event_time(row: dict[str, Any]) -> Optional[pd.Timestamp]:
    for key in ("detected_at", "sent_at", "alert_time", "recorded_at", "logged_at", "published_at"):
        ts = _parse_dt(row.get(key))
        if ts is not None:
            return ts
    return None


def _merge_outcomes(
    predictions: list[dict[str, Any]],
    *,
    outcome_paths: Optional[Iterable[Path]] = None,
) -> list[dict[str, Any]]:
    outcomes = _load_outcome_rows(outcome_paths or DEFAULT_OUTCOME_PATHS)
    by_ticker: dict[str, list[dict[str, Any]]] = {}
    for outcome in outcomes:
        ticker = str(outcome.get("ticker") or "").upper().strip()
        if not ticker:
            continue
        outcome["_event_time"] = _event_time(outcome)
        by_ticker.setdefault(ticker, []).append(outcome)

    merged = []
    copy_fields = {
        "runner_tier",
        "training_runner_tier",
        "outcome",
        "return_next_day_high_pct",
        "return_two_day_high_pct",
        "return_five_day_high_pct",
        "mfe_pct",
        "mae_pct",
        "max_favorable_excursion_pct",
        "max_adverse_excursion_pct",
        "was_real_move",
        "was_pump",
        "was_false_alarm",
        "resolved_at",
        "recorded_at",
    }
    for prediction in predictions:
        row = dict(prediction)
        if _runner_tier(row) is not None:
            merged.append(row)
            continue
        ticker = str(row.get("ticker") or "").upper().strip()
        candidates = by_ticker.get(ticker) or []
        if not candidates:
            merged.append(row)
            continue
        pred_time = _event_time(row)
        best = None
        if pred_time is not None:
            viable = []
            for outcome in candidates:
                out_time = outcome.get("_event_time")
                if out_time is None:
                    continue
                delta_hours = abs((out_time - pred_time).total_seconds()) / 3600
                if delta_hours <= 36:
                    viable.append((delta_hours, outcome))
            if viable:
                best = sorted(viable, key=lambda item: item[0])[0][1]
        if best is None and candidates:
            best = candidates[-1]
        if best is not None:
            for field in copy_fields:
                if row.get(field) is None and best.get(field) is not None:
                    row[field] = best.get(field)
            row["outcome_joined"] = True
        merged.append(row)
    return merged


def _runner_tier(row: dict[str, Any]) -> Optional[str]:
    tier = row.get("runner_tier") or row.get("training_runner_tier")
    if tier and str(tier) != "UNKNOWN":
        return str(tier)
    five_day = pd.to_numeric(pd.Series([row.get("return_five_day_high_pct")]), errors="coerce").iloc[0]
    two_day = pd.to_numeric(pd.Series([row.get("return_two_day_high_pct")]), errors="coerce").iloc[0]
    next_day = pd.to_numeric(pd.Series([row.get("return_next_day_high_pct")]), errors="coerce").iloc[0]
    if pd.notna(five_day) and five_day >= 300:
        return "LEGENDARY_RUNNER"
    if pd.notna(five_day) and five_day >= 100:
        return "MONSTER_RUNNER"
    if pd.notna(two_day) and two_day >= 30:
        return "MAJOR_RUNNER"
    if pd.notna(next_day) and next_day >= 10:
        return "STANDARD_WIN"
    if any(pd.notna(v) for v in (five_day, two_day, next_day)):
        return "NON_RUNNER"
    mfe = pd.to_numeric(pd.Series([row.get("mfe_pct") or row.get("max_favorable_excursion_pct")]), errors="coerce").iloc[0]
    if pd.notna(mfe):
        if mfe >= 300:
            return "LEGENDARY_RUNNER"
        if mfe >= 100:
            return "MONSTER_RUNNER"
        if mfe >= 30:
            return "MAJOR_RUNNER"
        if mfe >= 10:
            return "STANDARD_WIN"
        return "NON_RUNNER"
    return None


def _hit_rate(tiers: Iterable[Optional[str]], positives: set[str]) -> Optional[float]:
    resolved = [tier for tier in tiers if tier is not None]
    if not resolved:
        return None
    return sum(1 for tier in resolved if tier in positives) / len(resolved)


def _bucket_calibration(df: pd.DataFrame, probability_column: str, label_column: str) -> list[dict[str, Any]]:
    rows = []
    if df.empty or probability_column not in df:
        return rows
    proba = pd.to_numeric(df[probability_column], errors="coerce")
    labels = pd.to_numeric(df[label_column], errors="coerce")
    for bucket in range(10):
        lo = bucket / 10
        hi = (bucket + 1) / 10
        mask = (proba >= lo) & (proba <= hi if bucket == 9 else proba < hi) & labels.notna()
        count = int(mask.sum())
        rows.append(
            {
                "bucket": f"{lo:.1f}-{hi:.1f}",
                "rows": count,
                "avg_predicted": float(proba[mask].mean()) if count else None,
                "actual_rate": float(labels[mask].mean()) if count else None,
            }
        )
    return rows


def _top_decile(df: pd.DataFrame, score_column: str) -> pd.DataFrame:
    if df.empty or score_column not in df:
        return df.iloc[0:0]
    scores = pd.to_numeric(df[score_column], errors="coerce")
    if scores.notna().sum() == 0:
        return df.iloc[0:0]
    cutoff = scores.quantile(0.90)
    return df.loc[scores >= cutoff].copy()


def summarize_predictions(
    path: Path | str = DEFAULT_INPUT,
    *,
    outcome_paths: Optional[Iterable[Path]] = None,
) -> dict[str, Any]:
    path = Path(path)
    rows = _merge_outcomes(_load_jsonl(path), outcome_paths=outcome_paths)
    if not rows:
        return {
            "prediction_count": 0,
            "resolved_count": 0,
            "top_decile_candidates": [],
            "major_plus_hit_rate": None,
            "monster_plus_hit_rate": None,
            "calibration_major_plus": [],
            "calibration_monster_plus": [],
            "catboost_high_rules_low": [],
            "rules_high_catboost_low": [],
        }

    tiers = [_runner_tier(row) for row in rows]
    df = pd.DataFrame(rows)
    df["_runner_tier_resolved"] = tiers
    df["_major_plus_actual"] = df["_runner_tier_resolved"].map(lambda tier: int(tier in MAJOR_PLUS) if tier else None)
    df["_monster_plus_actual"] = df["_runner_tier_resolved"].map(lambda tier: int(tier in MONSTER_PLUS) if tier else None)

    top_model = _top_decile(df, "rocket_rank_score").sort_values("rocket_rank_score", ascending=False)
    top_rules = _top_decile(df, "expected_return_score").sort_values("expected_return_score", ascending=False)
    rules_scores = pd.to_numeric(df.get("expected_return_score"), errors="coerce") if "expected_return_score" in df else pd.Series(dtype=float)
    model_scores = pd.to_numeric(df.get("rocket_rank_score"), errors="coerce") if "rocket_rank_score" in df else pd.Series(dtype=float)
    rules_low_cutoff = rules_scores.quantile(0.50) if rules_scores.notna().any() else None
    model_low_cutoff = model_scores.quantile(0.50) if model_scores.notna().any() else None

    catboost_high_rules_low = top_model
    if rules_low_cutoff is not None:
        catboost_high_rules_low = catboost_high_rules_low.loc[
            pd.to_numeric(catboost_high_rules_low.get("expected_return_score"), errors="coerce") <= rules_low_cutoff
        ]

    rules_high_catboost_low = top_rules
    if model_low_cutoff is not None:
        rules_high_catboost_low = rules_high_catboost_low.loc[
            pd.to_numeric(rules_high_catboost_low.get("rocket_rank_score"), errors="coerce") <= model_low_cutoff
        ]

    resolved = [tier for tier in tiers if tier is not None]
    return {
        "prediction_count": len(rows),
        "resolved_count": len(resolved),
        "top_decile_candidates": top_model.head(25).to_dict("records"),
        "major_plus_hit_rate": _hit_rate(tiers, MAJOR_PLUS),
        "monster_plus_hit_rate": _hit_rate(tiers, MONSTER_PLUS),
        "calibration_major_plus": _bucket_calibration(df, "binary_major_plus_probability", "_major_plus_actual"),
        "calibration_monster_plus": _bucket_calibration(df, "binary_monster_plus_probability", "_monster_plus_actual"),
        "catboost_high_rules_low": catboost_high_rules_low.head(15).to_dict("records"),
        "rules_high_catboost_low": rules_high_catboost_low.head(15).to_dict("records"),
    }


def _fmt_pct(value: Optional[float]) -> str:
    return "n/a" if value is None else f"{value * 100:.2f}%"


def render_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# Rocket Model Shadow Report",
        "",
        f"- Predictions: {summary['prediction_count']:,}",
        f"- Resolved outcomes: {summary['resolved_count']:,}",
        f"- Major-plus hit rate: {_fmt_pct(summary['major_plus_hit_rate'])}",
        f"- Monster-plus hit rate: {_fmt_pct(summary['monster_plus_hit_rate'])}",
        "",
        "## Top-Decile Candidates",
    ]
    for row in summary["top_decile_candidates"][:20]:
        lines.append(
            f"- {row.get('ticker')} rank={row.get('rocket_rank_score')} "
            f"major={row.get('binary_major_plus_probability')} "
            f"monster={row.get('binary_monster_plus_probability')} "
            f"rules={row.get('expected_return_score')}"
        )

    lines.extend(["", "## Calibration: Major Plus"])
    for row in summary["calibration_major_plus"]:
        lines.append(f"- {row['bucket']}: rows={row['rows']} predicted={_fmt_pct(row['avg_predicted'])} actual={_fmt_pct(row['actual_rate'])}")

    lines.extend(["", "## Calibration: Monster Plus"])
    for row in summary["calibration_monster_plus"]:
        lines.append(f"- {row['bucket']}: rows={row['rows']} predicted={_fmt_pct(row['avg_predicted'])} actual={_fmt_pct(row['actual_rate'])}")

    lines.extend(["", "## CatBoost High, Rules Low"])
    for row in summary["catboost_high_rules_low"]:
        lines.append(f"- {row.get('ticker')} rank={row.get('rocket_rank_score')} rules={row.get('expected_return_score')} headline={row.get('headline')}")

    lines.extend(["", "## Rules High, CatBoost Low"])
    for row in summary["rules_high_catboost_low"]:
        lines.append(f"- {row.get('ticker')} rank={row.get('rocket_rank_score')} rules={row.get('expected_return_score')} headline={row.get('headline')}")

    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize Rocket shadow model predictions.")
    parser.add_argument("--input", default=str(DEFAULT_INPUT))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument(
        "--outcomes",
        nargs="*",
        default=[str(path) for path in DEFAULT_OUTCOME_PATHS],
        help="Optional outcome JSON files to join by ticker/time.",
    )
    args = parser.parse_args()

    summary = summarize_predictions(Path(args.input), outcome_paths=[Path(path) for path in args.outcomes])
    markdown = render_markdown(summary)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(markdown, encoding="utf-8")
    print(markdown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
