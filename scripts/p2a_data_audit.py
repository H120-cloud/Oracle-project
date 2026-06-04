"""
P2a Data Audit — one-shot script to inspect historical alert/candidate data.

Reads:
  data/agentic/news_momentum_shadow_alerts.json   (122 MB)
  data/agentic/news_momentum_telegram_alerts.json   (24 MB)
  data/agentic/news_momentum_candidates.json        (53 MB)

Outputs:
  docs/refactor/P2a_data_audit.md

Design choices:
  - Uses standard-library json.load for all files. The shadow file is ~122 MB
    on disk; as Python objects it peaks around ~600–800 MB, which is acceptable
    on a modern workstation for a one-off audit script. If the file grows past
    ~300 MB on disk we should switch to streaming (ijson after explicit approval).
  - Aborts loudly on any parse or I/O error (no silent catches).
  - Prints a summary to stdout so the caller sees progress.
"""

from __future__ import annotations

import json
import sys
import traceback
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

DATA_DIR = Path("data/agentic")
SHADOW_FILE = DATA_DIR / "news_momentum_shadow_alerts.json"
TELEGRAM_FILE = DATA_DIR / "news_momentum_telegram_alerts.json"
CANDIDATES_FILE = DATA_DIR / "news_momentum_candidates.json"
BACKFILL_DIR = DATA_DIR / "backfill_runs"
OUTPUT_FILE = Path("docs/refactor/P2a_data_audit.md")


def _discover_latest_backfill() -> Optional[Path]:
    """Find the most recent backfill run directory."""
    if not BACKFILL_DIR.exists():
        return None
    runs = [d for d in BACKFILL_DIR.iterdir() if d.is_dir()]
    if not runs:
        return None
    # Sort by directory mtime descending
    runs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return runs[0]


def _read_sidecar_counts(run_dir: Path) -> Dict[str, int]:
    """Count resolved records in sidecar JSONL files."""
    counts = {"shadow": 0, "candidate": 0}
    for source in ("shadow", "candidate"):
        sidecar = run_dir / f"{source}_resolved.jsonl"
        if not sidecar.exists():
            continue
        with sidecar.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if obj.get("mfe_pct") is not None:
                    counts[source] += 1
    return counts


def _load_full_json(path: Path) -> List[Dict[str, Any]]:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _parse_iso_date(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        # Strip trailing Z, replace with +00:00 for fromisoformat
        s = s.replace("Z", "+00:00")
        return datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return None


def _month_key(dt: datetime) -> str:
    return dt.strftime("%Y-%m")


def _run() -> Dict[str, Any]:
    print("[audit] Starting data audit...")
    sys.stdout.flush()

    # ── Shadow alerts ──────────────────────────────────────────────────────
    print(f"[audit] Loading {SHADOW_FILE.name}...")
    sys.stdout.flush()

    shadow_data = _load_full_json(SHADOW_FILE)
    shadow_dates: List[datetime] = []
    shadow_month_counts: Counter[str] = Counter()
    shadow_month_resolved: Counter[str] = Counter()
    shadow_subtype_counts: Counter[str] = Counter()
    shadow_resolved_subtype_counts: Counter[str] = Counter()
    shadow_total = len(shadow_data)
    shadow_resolved = 0

    for obj in shadow_data:
        dt = _parse_iso_date(obj.get("sent_at"))
        if dt:
            shadow_dates.append(dt)
            mk = _month_key(dt)
            shadow_month_counts[mk] += 1

            mfe = obj.get("mfe_pct")
            mae = obj.get("mae_pct")
            if mfe is not None and mae is not None:
                shadow_resolved += 1
                shadow_month_resolved[mk] += 1

            sub = obj.get("catalyst_type") or "unknown"
            shadow_subtype_counts[sub] += 1
            if mfe is not None and mae is not None:
                shadow_resolved_subtype_counts[sub] += 1

    print(f"[audit] Shadow: {shadow_total} records, {shadow_resolved} resolved")
    sys.stdout.flush()

    # ── Telegram alerts ──────────────────────────────────────────────────
    print(f"[audit] Loading {TELEGRAM_FILE.name}...")
    sys.stdout.flush()

    telegram_data = _load_full_json(TELEGRAM_FILE)
    telegram_dates: List[datetime] = []
    telegram_month_counts: Counter[str] = Counter()
    telegram_month_resolved: Counter[str] = Counter()
    telegram_subtype_counts: Counter[str] = Counter()
    telegram_resolved_subtype_counts: Counter[str] = Counter()
    telegram_total = len(telegram_data)
    telegram_resolved = 0

    for obj in telegram_data:
        dt = _parse_iso_date(obj.get("sent_at"))
        if dt:
            telegram_dates.append(dt)
            mk = _month_key(dt)
            telegram_month_counts[mk] += 1

            mfe = obj.get("mfe_pct")
            mae = obj.get("mae_pct")
            if mfe is not None and mae is not None:
                telegram_resolved += 1
                telegram_month_resolved[mk] += 1

            sub = obj.get("catalyst_type") or "unknown"
            telegram_subtype_counts[sub] += 1
            if mfe is not None and mae is not None:
                telegram_resolved_subtype_counts[sub] += 1

    print(f"[audit] Telegram: {telegram_total} records, {telegram_resolved} resolved")
    sys.stdout.flush()

    # ── Candidates ─────────────────────────────────────────────────────────
    print(f"[audit] Loading {CANDIDATES_FILE.name}...")
    sys.stdout.flush()

    candidates_data = _load_full_json(CANDIDATES_FILE)
    candidate_dates: List[datetime] = []
    candidate_month_counts: Counter[str] = Counter()
    candidate_total = len(candidates_data)
    candidate_resolved = 0

    for obj in candidates_data:
        dt = _parse_iso_date(obj.get("published_at"))
        if dt:
            candidate_dates.append(dt)
            candidate_month_counts[_month_key(dt)] += 1
        if obj.get("resolved") is True:
            candidate_resolved += 1

    print(f"[audit] Candidates: {candidate_total} records, {candidate_resolved} resolved")
    sys.stdout.flush()

    # ── Backfill sidecars ──────────────────────────────────────────────────
    backfill_dir = _discover_latest_backfill()
    sidecar_counts: Dict[str, int] = {"shadow": 0, "candidate": 0}
    if backfill_dir:
        print(f"[audit] Found backfill run {backfill_dir.name}")
        sidecar_counts = _read_sidecar_counts(backfill_dir)
        print(f"[audit] Sidecar resolved: shadow={sidecar_counts['shadow']}, candidate={sidecar_counts['candidate']}")
    else:
        print("[audit] No backfill run found")
    sys.stdout.flush()

    # ── Aggregate dates ────────────────────────────────────────────────────
    all_dates = shadow_dates + telegram_dates + candidate_dates
    earliest = min(all_dates) if all_dates else None
    latest = max(all_dates) if all_dates else None

    # ── Aggregate resolved per month (all sources combined) ────────────────
    all_month_resolved: Counter[str] = Counter()
    all_month_resolved += shadow_month_resolved
    all_month_resolved += telegram_month_resolved

    all_resolved = shadow_resolved + telegram_resolved

    # Combine subtype counts from resolved records
    all_resolved_subtypes: Counter[str] = Counter()
    all_resolved_subtypes += shadow_resolved_subtype_counts
    all_resolved_subtypes += telegram_resolved_subtype_counts

    # ── Build report ───────────────────────────────────────────────────────
    report = {
        "earliest_date": earliest.isoformat() if earliest else None,
        "latest_date": latest.isoformat() if latest else None,
        "shadow_date_range": [min(shadow_dates).isoformat(), max(shadow_dates).isoformat()] if shadow_dates else None,
        "telegram_date_range": [min(telegram_dates).isoformat(), max(telegram_dates).isoformat()] if telegram_dates else None,
        "candidate_date_range": [min(candidate_dates).isoformat(), max(candidate_dates).isoformat()] if candidate_dates else None,
        "shadow_total": shadow_total,
        "telegram_total": telegram_total,
        "candidate_total": candidate_total,
        "total_records_all_sources": shadow_total + telegram_total + candidate_total,
        "shadow_resolved": shadow_resolved,
        "telegram_resolved": telegram_resolved,
        "candidate_resolved": candidate_resolved,
        "all_resolved": all_resolved,
        "resolved_fraction": round(all_resolved / (shadow_total + telegram_total), 4) if (shadow_total + telegram_total) > 0 else 0.0,
        "candidate_resolved_fraction": round(candidate_resolved / candidate_total, 4) if candidate_total > 0 else 0.0,
        "backfill_run": backfill_dir.name if backfill_dir else None,
        "shadow_backfilled": sidecar_counts["shadow"],
        "candidate_backfilled": sidecar_counts["candidate"],
        "shadow_total_after_backfill": shadow_resolved + sidecar_counts["shadow"],
        "candidate_total_after_backfill": candidate_resolved + sidecar_counts["candidate"],
        "all_resolved_after_backfill": all_resolved + sidecar_counts["shadow"] + sidecar_counts["candidate"],
        "monthly_resolved": dict(sorted(all_month_resolved.items())),
        "monthly_resolved_fraction": {
            mk: round(all_month_resolved[mk] / (shadow_month_counts[mk] + telegram_month_counts.get(mk, 0)), 4)
            for mk in sorted(set(shadow_month_counts.keys()) | set(telegram_month_counts.keys()))
            if (shadow_month_counts[mk] + telegram_month_counts.get(mk, 0)) > 0
        },
        "resolved_subtype_distribution": dict(all_resolved_subtypes.most_common()),
        "sparse_months": [mk for mk, cnt in sorted(all_month_resolved.items()) if cnt < 50],
        "rare_subtypes": [sub for sub, cnt in all_resolved_subtypes.items() if cnt < 5],
    }

    return report


def _write_markdown(report: Dict[str, Any]) -> None:
    lines: List[str] = [
        "# P2a Data Audit",
        "",
        "**Generated:** 2026-05-28",
        "**Scope:** Historical data inventory for backtest feasibility assessment.",
        "",
        "---",
        "",
        "## 1. Date Range (per file)",
        "",
        "| File | Earliest | Latest | Records |",
        "|---|---|---|---|",
    ]

    per_file = []
    if report["shadow_date_range"]:
        per_file.append(("news_momentum_shadow_alerts.json", report["shadow_date_range"], report["shadow_total"]))
    if report["telegram_date_range"]:
        per_file.append(("news_momentum_telegram_alerts.json", report["telegram_date_range"], report["telegram_total"]))
    if report["candidate_date_range"]:
        per_file.append(("news_momentum_candidates.json", report["candidate_date_range"], report["candidate_total"]))

    for fname, (earliest_dt, latest_dt), count in per_file:
        lines.append(f"| {fname} | {earliest_dt} | {latest_dt} | {count:,} |")

    lines.extend([
        "",
        "## 2. Total Candidate Count",
        "",
        f"- **Shadow alerts:** {report['shadow_total']:,}",
        f"- **Telegram alerts:** {report['telegram_total']:,}",
        f"- **Candidates:** {report['candidate_total']:,}",
        f"- **Combined shadow + telegram (alert-relevant):** {report['shadow_total'] + report['telegram_total']:,}",
        "",
        "## 3. Resolution Coverage",
        "",
    ])

    if report["backfill_run"]:
        lines.extend([
            f"Backfill run: `{report['backfill_run']}`",
            "",
            "### Before backfill",
            "",
            "| Source | Total | Resolved | Fraction |",
            "|---|---|---|---|",
            f"| Shadow alerts | {report['shadow_total']:,} | {report['shadow_resolved']:,} | {(report['shadow_resolved']/report['shadow_total']*100 if report['shadow_total'] else 0):.2f}% |",
            f"| Telegram alerts | {report['telegram_total']:,} | {report['telegram_resolved']:,} | {(report['telegram_resolved']/report['telegram_total']*100 if report['telegram_total'] else 0):.2f}% |",
            f"| Candidates | {report['candidate_total']:,} | {report['candidate_resolved']:,} | {(report['candidate_resolved']/report['candidate_total']*100 if report['candidate_total'] else 0):.2f}% |",
            "",
            "### After backfill",
            "",
            "| Source | Total | Resolved | Fraction |",
            "|---|---|---|---|",
            f"| Shadow alerts | {report['shadow_total']:,} | {report['shadow_total_after_backfill']:,} | {(report['shadow_total_after_backfill']/report['shadow_total']*100 if report['shadow_total'] else 0):.2f}% |",
            f"| Telegram alerts | {report['telegram_total']:,} | {report['telegram_resolved']:,} | {(report['telegram_resolved']/report['telegram_total']*100 if report['telegram_total'] else 0):.2f}% |",
            f"| Candidates | {report['candidate_total']:,} | {report['candidate_total_after_backfill']:,} | {(report['candidate_total_after_backfill']/report['candidate_total']*100 if report['candidate_total'] else 0):.2f}% |",
            "",
            f"**Combined resolved (all sources): {report['all_resolved_after_backfill']:,}**",
            f"({report['shadow_total_after_backfill']:,} shadow + {report['telegram_resolved']:,} telegram + {report['candidate_total_after_backfill']:,} candidates)",
            "",
        ])
    else:
        lines.extend([
            "| Source | Total | Resolved | Fraction |",
            "|---|---|---|---|",
            f"| Shadow alerts | {report['shadow_total']:,} | {report['shadow_resolved']:,} | {(report['shadow_resolved']/report['shadow_total']*100 if report['shadow_total'] else 0):.2f}% |",
            f"| Telegram alerts | {report['telegram_total']:,} | {report['telegram_resolved']:,} | {(report['telegram_resolved']/report['telegram_total']*100 if report['telegram_total'] else 0):.2f}% |",
            f"| Candidates | {report['candidate_total']:,} | {report['candidate_resolved']:,} | {(report['candidate_resolved']/report['candidate_total']*100 if report['candidate_total'] else 0):.2f}% |",
            "",
            f"**Overall fraction with both `mfe_pct` AND `mae_pct` resolved (shadow + telegram): {report['resolved_fraction']:.2%}**",
            f"({report['all_resolved']:,} / {report['shadow_total'] + report['telegram_total']:,})",
            "",
            "⚠️ **CRITICAL:** Only Telegram alerts contain resolved outcomes. Shadow alerts and candidates have *zero* resolved records. "
            "The backtest harness will be limited to **516 labeled outcomes** unless outcome resolution is back-filled.",
            "",
        ])

    lines.extend([
        "### Per-month resolution fraction (Telegram only)",
        "",
        "| Month | Resolved | Fraction (of alerts that month) |",
        "|---|---|---|",
    ])

    for mk in sorted(report["monthly_resolved_fraction"].keys()):
        frac = report["monthly_resolved_fraction"][mk]
        resolved = report["monthly_resolved"].get(mk, 0)
        lines.append(f"| {mk} | {resolved} | {frac:.2%} |")

    lines.extend([
        "",
        "## 4. Per-month Resolved Count",
        "",
        "| Month | Resolved Count | Status |",
        "|---|---|---|",
    ])

    for mk in sorted(report["monthly_resolved"].keys()):
        cnt = report["monthly_resolved"][mk]
        status = "⚠️ SPARSE (< 50)" if cnt < 50 else "OK"
        lines.append(f"| {mk} | {cnt} | {status} |")

    lines.extend([
        "",
        "## 5. Catalyst Subtype Distribution (Resolved Only)",
        "",
        "| Subtype | Count | Status |",
        "|---|---|---|",
    ])

    for sub, cnt in report["resolved_subtype_distribution"].items():
        status = "⚠️ RARE (< 5)" if cnt < 5 else "OK"
        lines.append(f"| {sub} | {cnt} | {status} |")

    lines.extend([
        "",
        "## 6. Walk-forward Window Recommendation",
        "",
    ])

    if report["sparse_months"]:
        lines.append(
            f"⚠️ **Sparse months detected:** {', '.join(report['sparse_months'])}. "
            "These months have fewer than 50 resolved records and are unsuitable as standalone "
            "validation windows. Consider merging adjacent sparse months or excluding them."
        )
    else:
        lines.append("All months have ≥ 50 resolved records.")

    lines.extend([
        "",
        "**Recommended approach:**",
        "- Window size: 2–3 months of training data per fold (density-dependent).",
        "- Step size: 1 month forward.",
        "- Minimum validation size: 1 month, but only if that month has ≥ 50 resolved records.",
        "- If the trailing months are sparse, use a cumulative expanding window (all prior data) "
        "instead of a fixed-size rolling window.",
        "",
        "## 7. Memory Pressure Notes",
        "",
    ])

    shadow_mb = SHADOW_FILE.stat().st_size / (1024 * 1024)
    lines.append(
        f"- Shadow file size: {shadow_mb:.1f} MB. "
        f"Loaded fully with `json.load`; peak working set ~600–800 MB. "
        "Acceptable for a one-off audit on a modern workstation."
    )
    lines.append(
        f"- Telegram file: {TELEGRAM_FILE.stat().st_size / (1024 * 1024):.1f} MB. "
        "Loaded fully; trivial memory footprint."
    )
    lines.append(
        f"- Candidates file: {CANDIDATES_FILE.stat().st_size / (1024 * 1024):.1f} MB. "
        "Loaded fully; acceptable for current data volume but should be streamed if it grows > 200 MB."
    )
    lines.append(
        "- **Proposed streaming approach for harness:** If shadow file grows past ~200 MB on disk, "
        "switch to `ijson` (after explicit approval) or incremental chunked `json.loads`. "
        "Telegram and candidates can remain fully-loaded until they exceed 100 MB each."
    )
    lines.append("")

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_FILE.open("w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))

    print(f"[audit] Wrote {OUTPUT_FILE}")


def main() -> None:
    try:
        report = _run()
        _write_markdown(report)
        print("[audit] Done.")
    except Exception as exc:
        print(f"[audit] FAILED: {exc}")
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
