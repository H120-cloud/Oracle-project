"""
Deterministic, no-fetch reconstruction of historical Rocket runner labels.

This module intentionally depends only on local tabular data. It does not
fetch bars, call alerting services, or train models.
"""
from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from pathlib import Path
from src.utils.data_paths import agentic_data_dir, agentic_path
from typing import Any, Dict, Iterable, Optional, Sequence, Tuple

import pandas as pd

RECONSTRUCTION_VERSION = "rocket_labels_v1_no_fetch"
AUDIT_REFERENCE = "docs/rocket_label_coverage_audit.md"

EXISTING_RUNNER_TIERS = {
    "STANDARD_WIN",
    "MAJOR_RUNNER",
    "MONSTER_RUNNER",
    "LEGENDARY_RUNNER",
}

WINDOW_ALIASES: Dict[str, Tuple[str, ...]] = {
    "next_day": (
        "return_next_day_high_pct",
        "next_day_high_pct",
        "mfe_1d",
    ),
    "two_day": (
        "return_two_day_high_pct",
        "two_day_high_pct",
        "mfe_2d",
    ),
    "five_day": (
        "return_five_day_high_pct",
        "five_day_high_pct",
        "mfe_5d",
    ),
}

OUTPUT_COLUMNS = (
    "reconstructed_runner_tier",
    "training_runner_tier",
    "label_source",
    "label_confidence",
    "label_reason_code",
    "label_reason",
    "label_provenance",
    "label_reconstruction_version",
)


def _as_finite_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _window_value(
    row: pd.Series, aliases: Sequence[str]
) -> Tuple[Optional[float], Dict[str, float], bool]:
    source_values: Dict[str, float] = {}
    for column in aliases:
        if column not in row.index:
            continue
        number = _as_finite_float(row[column])
        if number is not None:
            source_values[column] = number

    unique_values = {round(value, 10) for value in source_values.values()}
    if len(unique_values) > 1:
        return None, source_values, True
    if not source_values:
        return None, {}, False
    return next(iter(source_values.values())), source_values, False


def _provenance(
    rule_id: str,
    source_values: Dict[str, float],
    *,
    note: str,
) -> str:
    payload = {
        "audit_reference": AUDIT_REFERENCE,
        "mapping_rule_id": rule_id,
        "note": note,
        "reconstruction_version": RECONSTRUCTION_VERSION,
        "source_columns": sorted(source_values),
        "source_values": dict(sorted(source_values.items())),
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _result(
    tier: str,
    source: str,
    confidence: str,
    reason_code: str,
    reason: str,
    rule_id: str,
    source_values: Dict[str, float],
) -> Dict[str, str]:
    return {
        "reconstructed_runner_tier": tier,
        "training_runner_tier": tier,
        "label_source": source,
        "label_confidence": confidence,
        "label_reason_code": reason_code,
        "label_reason": reason,
        "label_provenance": _provenance(rule_id, source_values, note=reason),
        "label_reconstruction_version": RECONSTRUCTION_VERSION,
    }


def _unknown(reason_code: str, reason: str, source_values: Dict[str, float]) -> Dict[str, str]:
    return _result(
        "UNKNOWN",
        "insufficient_evidence",
        "LOW",
        reason_code,
        reason,
        "RLR_UNKNOWN_V1",
        source_values,
    )


def _classify_row(row: pd.Series, include_provisional: bool) -> Dict[str, str]:
    existing = str(row.get("runner_tier", "") or "").strip()
    if existing in EXISTING_RUNNER_TIERS:
        return _result(
            existing,
            "existing_runner_tier",
            "HIGH",
            "existing_trusted_runner_tier",
            f"Preserved trusted existing runner_tier={existing}.",
            "RLR_EXISTING_TRUSTED_V1",
            {"runner_tier": existing},
        )

    values: Dict[str, Optional[float]] = {}
    source_values: Dict[str, float] = {}
    ambiguous = False
    for window, aliases in WINDOW_ALIASES.items():
        value, sources, conflict = _window_value(row, aliases)
        values[window] = value
        source_values.update(sources)
        ambiguous = ambiguous or conflict

    if ambiguous:
        return _unknown(
            "ambiguous_historical_values",
            "Historical aliases disagree for at least one outcome window.",
            source_values,
        )

    complete = all(values[window] is not None for window in WINDOW_ALIASES)
    if complete:
        five_day = values["five_day"]
        two_day = values["two_day"]
        next_day = values["next_day"]
        assert five_day is not None and two_day is not None and next_day is not None
        if five_day >= 300.0:
            return _result(
                "LEGENDARY_RUNNER", "reconstructed_exact", "HIGH",
                "exact_five_day_move_at_least_300",
                "Complete audited windows; five-day move reached at least 300%.",
                "RLR_EXACT_LEGENDARY_V1", source_values,
            )
        if five_day >= 100.0:
            return _result(
                "MONSTER_RUNNER", "reconstructed_exact", "HIGH",
                "exact_five_day_move_at_least_100",
                "Complete audited windows; five-day move reached at least 100%.",
                "RLR_EXACT_MONSTER_V1", source_values,
            )
        if two_day >= 30.0:
            return _result(
                "MAJOR_RUNNER", "reconstructed_exact", "HIGH",
                "exact_two_day_move_at_least_30",
                "Complete audited windows; two-day move reached at least 30%.",
                "RLR_EXACT_MAJOR_V1", source_values,
            )
        if next_day >= 10.0:
            return _result(
                "STANDARD_WIN", "reconstructed_exact", "HIGH",
                "exact_next_day_move_at_least_10",
                "Complete audited windows; next-day move reached at least 10%.",
                "RLR_EXACT_STANDARD_V1", source_values,
            )
        return _result(
            "NON_RUNNER", "reconstructed_exact", "HIGH",
            "exact_complete_windows_below_thresholds",
            "Complete audited windows; no runner threshold was reached.",
            "RLR_EXACT_NON_RUNNER_V1", source_values,
        )

    if not include_provisional:
        return _unknown(
            "partial_windows_provisional_disabled" if source_values else "no_audited_outcome_fields",
            "Partial outcome windows are not labeled unless provisional recovery is enabled."
            if source_values
            else "No audited historical outcome fields are available.",
            source_values,
        )

    five_day = values["five_day"]
    two_day = values["two_day"]
    next_day = values["next_day"]
    if five_day is not None and five_day >= 100.0:
        return _result(
            "PROVISIONAL_MONSTER_RUNNER", "reconstructed_provisional", "MEDIUM",
            "provisional_five_day_move_at_least_100",
            "Partial windows; observed five-day move proves at least monster-runner performance.",
            "RLR_PROVISIONAL_MONSTER_V1", source_values,
        )
    if two_day is not None and two_day >= 30.0:
        return _result(
            "PROVISIONAL_MAJOR_RUNNER", "reconstructed_provisional", "MEDIUM",
            "provisional_two_day_move_at_least_30",
            "Partial windows; observed two-day move proves at least major-runner performance.",
            "RLR_PROVISIONAL_MAJOR_V1", source_values,
        )
    if next_day is not None and next_day >= 10.0:
        return _result(
            "PROVISIONAL_STANDARD_WIN", "reconstructed_provisional", "MEDIUM",
            "provisional_next_day_move_at_least_10",
            "Partial windows; observed next-day move proves at least standard-win performance.",
            "RLR_PROVISIONAL_STANDARD_V1", source_values,
        )
    return _unknown(
        "partial_windows_below_observed_thresholds" if source_values else "no_audited_outcome_fields",
        "Partial outcome windows do not prove a runner threshold."
        if source_values
        else "No audited historical outcome fields are available.",
        source_values,
    )


def reconstruct_labels(df: pd.DataFrame, *, include_provisional: bool = False) -> pd.DataFrame:
    """Return a copy of *df* with deterministic no-fetch reconstruction columns."""
    result = df.copy(deep=True)
    labels = result.apply(
        lambda row: _classify_row(row, include_provisional=include_provisional),
        axis=1,
        result_type="expand",
    )
    for column in OUTPUT_COLUMNS:
        result[column] = labels[column]
    return result


def reconstruct_file(path: Path | str, *, include_provisional: bool = False) -> pd.DataFrame:
    """Load CSV or Parquet data from *path* and return reconstructed labels."""
    input_path = Path(path)
    suffix = input_path.suffix.lower()
    if suffix == ".csv":
        df = pd.read_csv(input_path, low_memory=False)
    elif suffix in {".parquet", ".pq"}:
        df = pd.read_parquet(input_path)
    else:
        raise ValueError(f"Unsupported dataset format: {input_path.suffix}")
    return reconstruct_labels(df, include_provisional=include_provisional)


def generate_label_coverage_report(df: pd.DataFrame) -> Dict[str, Any]:
    """Summarize reconstructed label coverage for an already reconstructed frame."""
    required = {"runner_tier", "training_runner_tier", "label_source", "label_confidence"}
    missing = sorted(required - set(df.columns))
    if missing:
        raise ValueError(f"Missing reconstruction columns: {missing}")

    total = len(df)
    source_counts = Counter(df["label_source"].fillna("missing").astype(str))
    reason_counts = Counter(df["label_reason_code"].fillna("missing").astype(str))
    confidence_counts = Counter(df["label_confidence"].fillna("missing").astype(str))
    distribution = Counter(df["training_runner_tier"].fillna("UNKNOWN").astype(str))
    existing = int(df["runner_tier"].notna().sum())
    exact = int(
        df["label_source"].isin({"existing_runner_tier", "reconstructed_exact"}).sum()
    )
    provisional = int((df["label_source"] == "reconstructed_provisional").sum())
    unknown = int((df["training_runner_tier"] == "UNKNOWN").sum())
    exact_positive = int(
        df["training_runner_tier"].isin(EXISTING_RUNNER_TIERS).sum()
    )
    exact_non_runner = int(
        (
            (df["training_runner_tier"] == "NON_RUNNER")
            & df["label_source"].isin({"existing_runner_tier", "reconstructed_exact"})
        ).sum()
    )

    return {
        "total_rows": total,
        "existing_runner_tier_count": existing,
        "exact_label_count": exact,
        "exact_labels_added": int((df["label_source"] == "reconstructed_exact").sum()),
        "exact_positive_count": exact_positive,
        "exact_non_runner_count": exact_non_runner,
        "provisional_label_count": provisional,
        "unknown_count": unknown,
        "exact_training_rows": exact,
        "exact_training_percent": round((exact / total * 100.0) if total else 0.0, 2),
        "max_positive_with_provisional": exact_positive + provisional,
        "source_breakdown": dict(sorted(source_counts.items())),
        "reason_code_breakdown": dict(sorted(reason_counts.items())),
        "confidence_breakdown": dict(sorted(confidence_counts.items())),
        "final_runner_distribution": dict(sorted(distribution.items())),
        "warnings": [
            "Drawdown quality is not reconstructed because aggregate returns do not preserve price paths.",
            "Provisional labels are lower bounds and must remain separate from exact training labels.",
        ],
        "limitations": [
            "Rows without complete audited windows cannot receive exact NON_RUNNER labels.",
            "No external market data was fetched.",
            "No ML models were trained or introduced.",
        ],
    }


def render_markdown_report(report: Dict[str, Any]) -> str:
    """Render a human-readable reconstruction report."""
    total = report["total_rows"]

    def pct(count: int) -> str:
        return f"{(count / total * 100.0) if total else 0.0:.2f}%"

    lines = [
        "# Rocket Label Reconstruction Report",
        "",
        "## Scope",
        "",
        "Deterministic no-fetch reconstruction from existing historical outcome fields.",
        "The original exports were not overwritten. No market data was fetched and no ML models were built.",
        "",
        "## Coverage Summary",
        "",
        "| Metric | Rows | % of Examined Rows |",
        "|---|---:|---:|",
        f"| Rows examined | {total:,} | 100.00% |",
        f"| Existing runner labels | {report['existing_runner_tier_count']:,} | {pct(report['existing_runner_tier_count'])} |",
        f"| Exact labels available after reconstruction | {report['exact_label_count']:,} | {pct(report['exact_label_count'])} |",
        f"| Exact labels added | {report['exact_labels_added']:,} | {pct(report['exact_labels_added'])} |",
        f"| Exact positive runners | {report['exact_positive_count']:,} | {pct(report['exact_positive_count'])} |",
        f"| Exact non-runners | {report['exact_non_runner_count']:,} | {pct(report['exact_non_runner_count'])} |",
        f"| Provisional positive labels | {report['provisional_label_count']:,} | {pct(report['provisional_label_count'])} |",
        f"| Remaining unlabeled rows | {report['unknown_count']:,} | {pct(report['unknown_count'])} |",
        f"| Maximum positives with provisional labels | {report['max_positive_with_provisional']:,} | {pct(report['max_positive_with_provisional'])} |",
        "",
        f"Coverage improved from **{report['existing_runner_tier_count']:,}** existing runner labels to **{report['exact_training_rows']:,}** exact training-ready rows.",
        "",
        "## Final Runner Distribution",
        "",
        "| Label | Rows |",
        "|---|---:|",
    ]
    lines.extend(
        f"| `{label}` | {count:,} |"
        for label, count in report["final_runner_distribution"].items()
    )
    lines.extend(["", "## Confidence Breakdown", "", "| Confidence | Rows |", "|---|---:|"])
    lines.extend(
        f"| `{confidence}` | {count:,} |"
        for confidence, count in report["confidence_breakdown"].items()
    )
    lines.extend(["", "## Label Source Breakdown", "", "| Source | Rows |", "|---|---:|"])
    lines.extend(
        f"| `{source}` | {count:,} |"
        for source, count in report["source_breakdown"].items()
    )
    lines.extend(["", "## Rule IDs", ""])
    for reason, count in report["reason_code_breakdown"].items():
        lines.append(f"- `{reason}`: {count:,}")
    lines.extend(["", "## Limitations", ""])
    lines.extend(f"- {item}" for item in report["warnings"] + report["limitations"])
    lines.extend(
        [
            "",
            "## Next Recommended Step",
            "",
            "Repair forward-pricing enrichment for rows that remain unknown, preserve path data for drawdown labels, and rerun the coverage audit before any ML training.",
            "",
        ]
    )
    return "\n".join(lines)


def write_reconstructed_exports(
    df: pd.DataFrame,
    *,
    data_dir: Path | str = agentic_data_dir(),
    docs_dir: Path | str = Path("docs"),
) -> Dict[str, str]:
    """Write separate reconstructed exports and their Markdown coverage report."""
    output_dir = Path(data_dir)
    report_dir = Path(docs_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    report_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "rocket_training_dataset_reconstructed.csv"
    parquet_path = output_dir / "rocket_training_dataset_reconstructed.parquet"
    report_path = report_dir / "rocket_label_reconstruction_report.md"
    df.to_csv(csv_path, index=False, encoding="utf-8")
    df.to_parquet(parquet_path, index=False, compression="snappy")
    report = generate_label_coverage_report(df)
    report_path.write_text(render_markdown_report(report), encoding="utf-8")
    return {
        "csv": str(csv_path),
        "parquet": str(parquet_path),
        "report": str(report_path),
    }


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        default=str(agentic_path("rocket_training_dataset.parquet")),
        help="Existing Rocket CSV or Parquet export.",
    )
    parser.add_argument(
        "--include-provisional",
        action="store_true",
        help="Label lower-bound positives from partial windows separately.",
    )
    parser.add_argument("--data-dir", default=str(agentic_data_dir()))
    parser.add_argument("--docs-dir", default="docs")
    args = parser.parse_args(list(argv) if argv is not None else None)

    reconstructed = reconstruct_file(
        args.input,
        include_provisional=args.include_provisional,
    )
    paths = write_reconstructed_exports(
        reconstructed,
        data_dir=args.data_dir,
        docs_dir=args.docs_dir,
    )
    report = generate_label_coverage_report(reconstructed)
    print(json.dumps({"outputs": paths, "coverage": report}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
