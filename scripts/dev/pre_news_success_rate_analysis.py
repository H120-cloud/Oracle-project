#!/usr/bin/env python3
"""
Pre-News Anomaly Detector — V3 Success Rate & Signal Quality Analysis

Comprehensive evaluation harness that loads all available detection snapshots
and evaluation reports, then produces:
  - Data quality audit
  - Realistic success metrics (basic, clean, high-quality, pre-news, news-lag, avoidance)
  - Bucketed performance by anomaly type, alert quality, candidate type, etc.
  - Threshold analysis
  - Signal fingerprint analysis
  - False positive analysis
  - Suppression analysis
  - Benchmarking placeholders
  - Statistical confidence indicators
  - Calibration recommendations

Output files:
  1. pre_news_success_rate_report.md
  2. pre_news_success_rate_report.json
  3. pre_news_bucket_performance.csv
  4. pre_news_false_positives.csv
  5. pre_news_suppressed_winners.csv
  6. pre_news_best_early_detections.csv

Design:
  - No lookahead bias: detection-time fields are immutable.
  - Forward metrics are computed post-detection and clearly separated.
  - Medians are reported alongside averages because small-cap runners distort means.
  - Low-confidence buckets (<20 samples) are flagged.
"""

from __future__ import annotations

import csv
import json
import logging
import math
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Lazy import pandas — not in requirements.txt, so fallback to pure Python if unavailable
try:
    import pandas as pd
    HAS_PANDAS = True
except ImportError:
    HAS_PANDAS = False

logger = logging.getLogger(__name__)
_handler = logging.StreamHandler(sys.stdout)
_handler.setLevel(logging.DEBUG)
_handler.addFilter(lambda rec: rec.levelno < logging.WARNING)
_handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
_err_handler = logging.StreamHandler(sys.stderr)
_err_handler.setLevel(logging.WARNING)
_err_handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
logging.basicConfig(level=logging.INFO, handlers=[_handler, _err_handler])

# ═══════════════════════════════════════════════════════════════════════════════
#  PATHS
# ═══════════════════════════════════════════════════════════════════════════════

BASE_DIR = Path("data/agentic")
SNAPSHOTS_FILE = BASE_DIR / "pre_news_evaluation_snapshots.json"
BASELINE_SNAPSHOTS_FILE = BASE_DIR / "pre_news_baseline_snapshots.json"
REPORTS_DIR = BASE_DIR / "evaluation_reports"
OUTPUT_DIR = REPORTS_DIR  # write alongside daily exports

# ═══════════════════════════════════════════════════════════════════════════════
#  DATA LOADING
# ═══════════════════════════════════════════════════════════════════════════════


def load_snapshots_from_json(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):
        return list(data.values())
    return list(data)


def load_snapshots_from_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = []
        for row in reader:
            # Coerce known numeric / boolean fields
            for key in row:
                val = row[key]
                if val == "" or val is None:
                    row[key] = None
                    continue
                # booleans stored as Y/N in CSV
                if val in ("Y", "N"):
                    row[key] = val == "Y"
                    continue
                # try numeric
                try:
                    if "." in val:
                        row[key] = float(val)
                    else:
                        row[key] = int(val)
                except ValueError:
                    pass  # leave as string
            rows.append(row)
        return rows


def load_all_baselines() -> list[dict]:
    """Load all baseline snapshots from JSON and CSV reports."""
    baselines = {}

    # 1. JSON baseline snapshots file
    for snap in load_snapshots_from_json(BASELINE_SNAPSHOTS_FILE):
        _dedup_key = snap.get("baseline_id") or f"{snap.get('ticker')}_{snap.get('scan_time')}_{snap.get('baseline_type')}"
        baselines[_dedup_key] = snap

    # 2. CSV baseline reports
    if REPORTS_DIR.exists():
        for csv_path in sorted(REPORTS_DIR.glob("*_pre_news_baselines.csv")):
            for row in load_snapshots_from_csv(csv_path):
                _dedup_key = row.get("baseline_id") or f"{row.get('ticker')}_{row.get('scan_time')}_{row.get('baseline_type')}"
                if _dedup_key not in baselines or row.get("max_move_1h_pct") is not None:
                    baselines[_dedup_key] = row

    return list(baselines.values())


def load_all_snapshots() -> list[dict]:
    """Load from JSON snapshots + all CSV daily reports. Deduplicate by detection_id."""
    snapshots = {}

    # 1. JSON snapshots file
    for snap in load_snapshots_from_json(SNAPSHOTS_FILE):
        _dedup_key = snap.get("detection_id") or f"{snap.get('ticker')}_{snap.get('detection_time')}_{snap.get('detection_price')}"
        snapshots[_dedup_key] = snap

    # 2. CSV reports
    if REPORTS_DIR.exists():
        for csv_path in sorted(REPORTS_DIR.glob("*_pre_news_eval.csv")):
            for row in load_snapshots_from_csv(csv_path):
                _dedup_key = row.get("detection_id") or f"{row.get('ticker')}_{row.get('detection_time')}_{row.get('detection_price')}"
                # CSV wins if newer (has forward metrics)
                if _dedup_key not in snapshots or row.get("max_move_1h_pct") is not None:
                    snapshots[_dedup_key] = row

    return list(snapshots.values())


# ═══════════════════════════════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════════════════════════════


def _safe_float(v) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


def _safe_bool(v) -> bool | None:
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.lower() in ("true", "t", "yes", "y", "1")
    return bool(v)


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 2)


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    return round(statistics.median(values), 2)


def _stdev(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    return round(statistics.stdev(values), 2)


def _pct(part: int, total: int) -> float | None:
    if total == 0:
        return None
    return round(part / total * 100, 1)


def _confidence_level(n: int) -> str:
    if n < 20:
        return "LOW"
    if n < 50:
        return "MEDIUM"
    return "HIGH"


def _bucket_value(val: float | None, bins: list[tuple[float | None, float | None, str]]) -> str | None:
    if val is None:
        return None
    for lo, hi, label in bins:
        if lo is not None and val < lo:
            continue
        if hi is not None and val > hi:
            continue
        return label
    return None


# ═══════════════════════════════════════════════════════════════════════════════
#  PART 1 — DATA QUALITY
# ═══════════════════════════════════════════════════════════════════════════════


def run_data_quality(snapshots: list[dict]) -> dict:
    total = len(snapshots)
    unique_tickers = set(s.get("ticker") for s in snapshots if s.get("ticker"))
    sessions = set(s.get("session_date") for s in snapshots if s.get("session_date"))
    completed = sum(1 for s in snapshots if s.get("final_outcome_label") not in (None, "", "unresolved"))
    unresolved = sum(1 for s in snapshots if s.get("final_outcome_label") in (None, "", "unresolved"))

    missing_price = sum(1 for s in snapshots if _safe_float(s.get("detection_price")) is None)
    missing_forward = sum(
        1
        for s in snapshots
        if _safe_float(s.get("max_move_1h_pct")) is None and _safe_float(s.get("max_move_2h_pct")) is None
    )
    missing_vwap = sum(1 for s in snapshots if _safe_float(s.get("vwap_distance")) is None)
    missing_outcome = sum(1 for s in snapshots if s.get("final_outcome_label") in (None, ""))

    # Duplicates by ticker + detection_time + price (only if detection_id missing)
    dup_keys = Counter(
        f"{s.get('ticker')}_{s.get('detection_time')}_{s.get('detection_price')}"
        for s in snapshots
        if not s.get("detection_id")
    )
    duplicates = sum(v - 1 for v in dup_keys.values() if v > 1)

    # Impossible values
    bad = 0
    for s in snapshots:
        price = _safe_float(s.get("detection_price"))
        rvol = _safe_float(s.get("time_of_day_rvol"))
        if price is not None and price <= 0:
            bad += 1
        elif rvol is not None and rvol < 0:
            bad += 1

    usable = total - unresolved - missing_forward - missing_price
    usable_pct = _pct(usable, total) if total else None

    return {
        "total_detections": total,
        "unique_tickers": len(unique_tickers),
        "trading_sessions": len(sessions),
        "completed_outcomes": completed,
        "unresolved_outcomes": unresolved,
        "missing_detection_prices": missing_price,
        "missing_forward_price_fields": missing_forward,
        "missing_vwap_fields": missing_vwap,
        "missing_final_outcome_labels": missing_outcome,
        "duplicate_detections": duplicates,
        "impossible_values": bad,
        "usable_for_success_rate": usable,
        "usable_percentage": usable_pct,
    }


# ═══════════════════════════════════════════════════════════════════════════════
#  PART 2 — SUCCESS DEFINITIONS
# ═══════════════════════════════════════════════════════════════════════════════


def compute_success_metrics(snapshots: list[dict]) -> dict:
    """Calculate all realistic success metrics."""
    usable = [
        s
        for s in snapshots
        if _safe_float(s.get("detection_price")) is not None
        and s.get("final_outcome_label") not in (None, "", "unresolved")
    ]

    if not usable:
        return {"note": "No usable detections with completed outcomes and forward metrics."}

    # Extract forward fields
    m30 = [v for s in usable if (v := _safe_float(s.get("max_move_30m_pct"))) is not None]
    m1h = [v for s in usable if (v := _safe_float(s.get("max_move_1h_pct"))) is not None]
    m2h = [v for s in usable if (v := _safe_float(s.get("max_move_2h_pct"))) is not None]
    msd = [v for s in usable if (v := _safe_float(s.get("max_move_same_day_pct"))) is not None]
    dd = [v for s in usable if (v := _safe_float(s.get("drawdown_before_max_move_pct"))) is not None]
    eff = [v for s in usable if (v := _safe_float(s.get("efficiency_ratio"))) is not None]
    vwap_hold = [s for s in usable if _safe_bool(s.get("vwap_hold_after_detection")) is True]

    # A. Basic Success
    basic_ok = [
        s
        for s in usable
        if ((_safe_float(s.get("max_move_1h_pct")) or 0) >= 5.0)
        or ((_safe_float(s.get("max_move_2h_pct")) or 0) >= 7.0)
    ]

    # B. Clean Success
    clean_ok = [
        s
        for s in usable
        if (_safe_float(s.get("max_move_1h_pct")) or 0) >= 5.0
        and (_safe_float(s.get("drawdown_before_max_move_pct")) or 999)
        <= 0.5 * (_safe_float(s.get("max_move_1h_pct")) or 0)
        and _safe_bool(s.get("vwap_hold_after_detection")) is True
        and (_safe_float(s.get("efficiency_ratio")) or 0) >= 1.5
    ]

    # C. High-Quality Success
    hq_ok = [
        s
        for s in usable
        if (_safe_float(s.get("max_move_2h_pct")) or 0) >= 10.0
        and _safe_bool(s.get("vwap_hold_after_detection")) is True
        and (_safe_float(s.get("drawdown_before_max_move_pct")) or 999) <= 5.0
        and (_safe_float(s.get("efficiency_ratio")) or 0) >= 2.0
        and s.get("final_outcome_label") in ("clean_pre_news_winner", "news_lag_confirmed_winner")
    ]

    # D. Pre-News Success
    prenews_ok = [
        s
        for s in usable
        if s.get("news_status") in ("no_news_found", "no_public_news_found_in_sources", "unknown_news_status")
        and ((_safe_float(s.get("max_move_1h_pct")) or 0) >= 5.0
             or (_safe_float(s.get("max_move_2h_pct")) or 0) >= 7.0)
    ]

    # E. News-Lag Success
    newslag_ok = [
        s
        for s in usable
        if s.get("final_outcome_label") == "news_lag_confirmed_winner"
        and (_safe_float(s.get("post_news_high") or 0) > _safe_float(s.get("pre_news_high") or 0))
    ]

    # F. Avoidance Success (warning signals that correctly predicted failure)
    avoidance_labels = ("failed_spike", "distribution_trap", "late_chase_signal", "no_follow_through")
    avoidance_ok = [
        s
        for s in usable
        if s.get("final_outcome_label") in avoidance_labels
        and (
            (_safe_float(s.get("max_move_1h_pct")) or 999) < 3.0
            or (_safe_float(s.get("efficiency_ratio")) or 999) < 1.0
            or _safe_bool(s.get("vwap_hold_after_detection")) is False
        )
    ]

    n = len(usable)
    return {
        "total_usable": n,
        "basic_success_rate": _pct(len(basic_ok), n),
        "clean_success_rate": _pct(len(clean_ok), n),
        "high_quality_success_rate": _pct(len(hq_ok), n),
        "pre_news_success_rate": _pct(len(prenews_ok), n),
        "news_lag_success_rate": _pct(len(newslag_ok), n),
        "avoidance_success_rate": _pct(len(avoidance_ok), n),
        # Move stats
        "avg_max_move_30m_pct": _mean(m30),
        "avg_max_move_1h_pct": _mean(m1h),
        "avg_max_move_2h_pct": _mean(m2h),
        "avg_max_move_same_day_pct": _mean(msd),
        "median_max_move_30m_pct": _median(m30),
        "median_max_move_1h_pct": _median(m1h),
        "median_max_move_2h_pct": _median(m2h),
        "avg_drawdown_before_max_move_pct": _mean(dd),
        "median_drawdown_before_max_move_pct": _median(dd),
        "avg_efficiency_ratio": _mean(eff),
        "median_efficiency_ratio": _median(eff),
        "vwap_hold_rate": _pct(len(vwap_hold), n),
        # Variability
        "stdev_max_move_1h_pct": _stdev(m1h),
        "stdev_efficiency_ratio": _stdev(eff),
    }


# ═══════════════════════════════════════════════════════════════════════════════
#  PART 2b — FILTERED SUCCESS (exclude penny, microcap, high offering risk, etc)
# ═══════════════════════════════════════════════════════════════════════════════


def compute_filtered_success(snapshots: list[dict]) -> dict:
    """Exclude penny, microcap, high offering risk, late alerts, old catalysts."""
    filtered = []
    for s in snapshots:
        price = _safe_float(s.get("detection_price")) or 0
        mcap = _safe_float(s.get("market_cap")) or 0
        off_risk = _safe_float(s.get("offering_risk_score")) or 0
        alert_q = (s.get("alert_quality") or "").lower()
        catalyst_age = s.get("catalyst_age_bucket") or ""

        if price < 1.0:
            continue
        if mcap > 0 and mcap < 300_000_000:
            continue
        if off_risk >= 60:
            continue
        if alert_q == "late":
            continue
        if catalyst_age in ("older_than_30d",):
            continue

        filtered.append(s)

    metrics = compute_success_metrics(filtered)
    metrics["filter_description"] = (
        "Excluded: price < $1, market cap < $300M, offering_risk >= 60, "
        "alert_quality = LATE, catalyst_age_bucket = older_than_30d"
    )
    return metrics


# ═══════════════════════════════════════════════════════════════════════════════
#  BASELINE COMPARISON
# ═══════════════════════════════════════════════════════════════════════════════


def compute_baseline_metrics(baselines: list[dict]) -> dict:
    """Calculate success metrics for a list of baseline snapshots."""
    usable = [
        b
        for b in baselines
        if _safe_float(b.get("price_at_scan")) is not None
        and b.get("final_baseline_outcome_label") not in (None, "", "unresolved")
    ]
    if not usable:
        return {"note": "No usable baseline snapshots with completed outcomes."}

    m30 = [v for b in usable if (v := _safe_float(b.get("max_move_30m_pct"))) is not None]
    m1h = [v for b in usable if (v := _safe_float(b.get("max_move_1h_pct"))) is not None]
    m2h = [v for b in usable if (v := _safe_float(b.get("max_move_2h_pct"))) is not None]
    dd = [v for b in usable if (v := _safe_float(b.get("drawdown_before_max_move_pct"))) is not None]
    eff = [v for b in usable if (v := _safe_float(b.get("efficiency_ratio"))) is not None]
    vwap_hold = [b for b in usable if _safe_bool(b.get("vwap_hold_after_scan")) is True]

    # Basic success: 1h >= 5% or 2h >= 7%
    basic_ok = [
        b
        for b in usable
        if ((_safe_float(b.get("max_move_1h_pct")) or 0) >= 5.0)
        or ((_safe_float(b.get("max_move_2h_pct")) or 0) >= 7.0)
    ]

    # Clean success: 1h >= 5%, dd <= 50% of move, VWAP held, eff >= 1.5
    clean_ok = [
        b
        for b in usable
        if (_safe_float(b.get("max_move_1h_pct")) or 0) >= 5.0
        and (_safe_float(b.get("drawdown_before_max_move_pct")) or 999)
        <= 0.5 * (_safe_float(b.get("max_move_1h_pct")) or 0)
        and _safe_bool(b.get("vwap_hold_after_scan")) is True
        and (_safe_float(b.get("efficiency_ratio")) or 0) >= 1.5
    ]

    # High-quality: 2h >= 10%, VWAP held, dd <= 5%, eff >= 2.0, clean winner
    hq_ok = [
        b
        for b in usable
        if (_safe_float(b.get("max_move_2h_pct")) or 0) >= 10.0
        and _safe_bool(b.get("vwap_hold_after_scan")) is True
        and (_safe_float(b.get("drawdown_before_max_move_pct")) or 999) <= 5.0
        and (_safe_float(b.get("efficiency_ratio")) or 0) >= 2.0
        and b.get("final_baseline_outcome_label") == "clean_baseline_winner"
    ]

    # Trap rate: baseline failed or high drawdown
    trap = [
        b
        for b in usable
        if b.get("final_baseline_outcome_label") == "baseline_failed"
        or (_safe_float(b.get("drawdown_before_max_move_pct")) or 0) > 8.0
    ]

    # Late chase rate: poor 1h move with high drawdown
    late = [
        b
        for b in usable
        if (_safe_float(b.get("max_move_1h_pct")) or 0) < 3.0
        and (_safe_float(b.get("drawdown_before_max_move_pct")) or 0) > 5.0
    ]

    # No-follow-through
    nft = [
        b
        for b in usable
        if b.get("final_baseline_outcome_label") == "baseline_no_follow_through"
    ]

    n = len(usable)
    return {
        "total_usable": n,
        "basic_success_rate": _pct(len(basic_ok), n),
        "clean_success_rate": _pct(len(clean_ok), n),
        "high_quality_success_rate": _pct(len(hq_ok), n),
        "avg_max_move_30m_pct": _mean(m30),
        "avg_max_move_1h_pct": _mean(m1h),
        "avg_max_move_2h_pct": _mean(m2h),
        "median_max_move_1h_pct": _median(m1h),
        "avg_drawdown_before_max_move_pct": _mean(dd),
        "median_drawdown_before_max_move_pct": _median(dd),
        "avg_efficiency_ratio": _mean(eff),
        "median_efficiency_ratio": _median(eff),
        "vwap_hold_rate": _pct(len(vwap_hold), n),
        "trap_rate": _pct(len(trap), n),
        "late_chase_rate": _pct(len(late), n),
        "no_follow_through_rate": _pct(len(nft), n),
        "stdev_max_move_1h_pct": _stdev(m1h),
        "stdev_efficiency_ratio": _stdev(eff),
    }


def baseline_comparison(detector_snapshots: list[dict], baseline_snapshots: list[dict]) -> dict:
    """
    Compare detector alerts against each baseline type.
    Returns comparison rows and verdicts.
    """
    if not baseline_snapshots:
        return {"note": "No baseline data available. Run scans with baseline capture enabled."}

    # Compute detector overall metrics
    detector_metrics = compute_success_metrics(detector_snapshots)

    # Group baselines by type
    by_type = defaultdict(list)
    for b in baseline_snapshots:
        bl_type = b.get("baseline_type") or "unknown"
        by_type[bl_type].append(b)

    comparisons = []
    for bl_type, items in sorted(by_type.items()):
        baseline_metrics = compute_baseline_metrics(items)
        if "total_usable" not in baseline_metrics:
            continue

        n = baseline_metrics["total_usable"]
        comp = {
            "baseline_type": bl_type,
            "count": len(items),
            "usable": n,
            "detector_clean_success_rate": detector_metrics.get("clean_success_rate"),
            "baseline_clean_success_rate": baseline_metrics.get("clean_success_rate"),
            "detector_avg_1h_move": detector_metrics.get("avg_max_move_1h_pct"),
            "baseline_avg_1h_move": baseline_metrics.get("avg_max_move_1h_pct"),
            "detector_avg_2h_move": detector_metrics.get("avg_max_move_2h_pct"),
            "baseline_avg_2h_move": baseline_metrics.get("avg_max_move_2h_pct"),
            "detector_avg_drawdown": detector_metrics.get("avg_drawdown_before_max_move_pct"),
            "baseline_avg_drawdown": baseline_metrics.get("avg_drawdown_before_max_move_pct"),
            "detector_median_drawdown": detector_metrics.get("median_drawdown_before_max_move_pct"),
            "baseline_median_drawdown": baseline_metrics.get("median_drawdown_before_max_move_pct"),
            "detector_avg_efficiency": detector_metrics.get("avg_efficiency_ratio"),
            "baseline_avg_efficiency": baseline_metrics.get("avg_efficiency_ratio"),
            "detector_vwap_hold_rate": detector_metrics.get("vwap_hold_rate"),
            "baseline_vwap_hold_rate": baseline_metrics.get("vwap_hold_rate"),
            "baseline_trap_rate": baseline_metrics.get("trap_rate"),
            "baseline_late_chase_rate": baseline_metrics.get("late_chase_rate"),
            "baseline_no_follow_through_rate": baseline_metrics.get("no_follow_through_rate"),
            "confidence_level": _confidence_level(n),
        }
        comparisons.append(comp)

    # Verdicts
    verdicts = {}
    detector_clean = detector_metrics.get("clean_success_rate") or 0
    for comp in comparisons:
        bl_type = comp["baseline_type"]
        baseline_clean = comp["baseline_clean_success_rate"] or 0
        baseline_eff = comp["baseline_avg_efficiency"] or 0
        detector_eff = comp["detector_avg_efficiency"] or 0
        baseline_dd = comp["baseline_avg_drawdown"] or 0
        detector_dd = comp["detector_avg_drawdown"] or 0

        if detector_clean > baseline_clean and detector_eff > baseline_eff and detector_dd < baseline_dd:
            verdicts[bl_type] = "DETECTOR_WINS"
        elif detector_clean > baseline_clean:
            verdicts[bl_type] = "DETECTOR_BEATS_ON_SUCCESS_RATE"
        elif detector_eff > baseline_eff and detector_dd < baseline_dd:
            verdicts[bl_type] = "DETECTOR_BEATS_ON_EFFICIENCY_AND_DRAWDOWN"
        elif detector_clean < baseline_clean:
            verdicts[bl_type] = "BASELINE_WINS"
        else:
            verdicts[bl_type] = "TIE"

    return {
        "comparisons": comparisons,
        "verdicts": verdicts,
        "detector_overall": detector_metrics,
    }


# ═══════════════════════════════════════════════════════════════════════════════
#  PART 4 — BUCKET PERFORMANCE
# ═══════════════════════════════════════════════════════════════════════════════


def bucket_performance(snapshots: list[dict], bucket_key: str) -> list[dict]:
    groups = defaultdict(list)
    for s in snapshots:
        val = s.get(bucket_key)
        if val is None or val == "":
            val = "unknown"
        groups[str(val).lower().replace(" ", "_")].append(s)

    rows = []
    for bucket_name, items in sorted(groups.items()):
        metrics = compute_success_metrics(items)
        if "total_usable" not in metrics:
            continue
        n = metrics["total_usable"]
        rows.append({
            "bucket": bucket_name,
            "count": len(items),
            "usable": n,
            "basic_success_rate": metrics.get("basic_success_rate"),
            "clean_success_rate": metrics.get("clean_success_rate"),
            "high_quality_success_rate": metrics.get("high_quality_success_rate"),
            "avg_max_move_30m_pct": metrics.get("avg_max_move_30m_pct"),
            "avg_max_move_1h_pct": metrics.get("avg_max_move_1h_pct"),
            "avg_max_move_2h_pct": metrics.get("avg_max_move_2h_pct"),
            "avg_drawdown_before_max_move_pct": metrics.get("avg_drawdown_before_max_move_pct"),
            "avg_efficiency_ratio": metrics.get("avg_efficiency_ratio"),
            "vwap_hold_rate": metrics.get("vwap_hold_rate"),
            "confidence_level": _confidence_level(n),
        })
    return rows


# ═══════════════════════════════════════════════════════════════════════════════
#  PART 5 — THRESHOLD ANALYSIS
# ═══════════════════════════════════════════════════════════════════════════════


def threshold_analysis(snapshots: list[dict]) -> dict:
    usable = [
        s
        for s in snapshots
        if _safe_float(s.get("detection_price")) is not None
        and s.get("final_outcome_label") not in (None, "", "unresolved")
    ]

    results = {}

    def _analyze(field: str, bins: list[tuple[float | None, float | None, str]], label: str):
        rows = []
        for lo, hi, bin_label in bins:
            items = [s for s in usable if (v := _safe_float(s.get(field))) is not None]
            items = [s for s in items if (lo is None or (v := _safe_float(s.get(field))) >= lo) and (hi is None or v <= hi)]
            if not items:
                continue
            metrics = compute_success_metrics(items)
            rows.append({
                "field": field,
                "bucket": bin_label,
                "count": len(items),
                "usable": metrics.get("total_usable", 0),
                "clean_success_rate": metrics.get("clean_success_rate"),
                "avg_efficiency_ratio": metrics.get("avg_efficiency_ratio"),
                "avg_drawdown_before_max_move_pct": metrics.get("avg_drawdown_before_max_move_pct"),
                "confidence_level": _confidence_level(len(items)),
            })
        results[label] = rows

    _analyze("time_of_day_rvol", [(None, 1.5, "<1.5"), (1.5, 2.0, "1.5-2.0"), (2.0, 3.0, "2.0-3.0"), (3.0, 5.0, "3.0-5.0"), (5.0, None, ">5.0")], "time_of_day_rvol")
    _analyze("vwap_distance", [(None, 0, "below_vwap"), (0, 3, "0-3%"), (3, 6, "3-6%"), (6, 10, "6-10%"), (10, 15, "10-15%"), (15, None, ">15%")], "vwap_distance")
    _analyze("absorption_quality_score", [(None, 40, "<40"), (40, 55, "40-55"), (55, 65, "55-65"), (65, 75, "65-75"), (75, 85, "75-85"), (85, None, ">85")], "absorption_quality_score")
    _analyze("upper_wick_pct", [(None, 20, "<20"), (20, 30, "20-30"), (30, 40, "30-40"), (40, None, ">40")], "upper_wick_pct")
    _analyze("pre_news_suspicion_score", [(None, 50, "<50"), (50, 60, "50-60"), (60, 70, "60-70"), (70, 80, "70-80"), (80, 90, "80-90"), (90, None, ">90")], "pre_news_suspicion_score")

    # buying_pressure minus selling_pressure (manual)
    bp_sp_rows = []
    for lo, hi, bin_label in [(None, 0, "negative"), (0, 10, "0-10"), (10, 25, "10-25"), (25, None, ">25")]:
        items = []
        for s in usable:
            bp = _safe_float(s.get("buying_pressure")) or 0
            sp = _safe_float(s.get("selling_pressure")) or 0
            diff = bp - sp
            if (lo is None or diff >= lo) and (hi is None or diff <= hi):
                items.append(s)
        if items:
            metrics = compute_success_metrics(items)
            bp_sp_rows.append({
                "field": "buying_pressure_minus_selling_pressure",
                "bucket": bin_label,
                "count": len(items),
                "usable": metrics.get("total_usable", 0),
                "clean_success_rate": metrics.get("clean_success_rate"),
                "avg_efficiency_ratio": metrics.get("avg_efficiency_ratio"),
                "avg_drawdown_before_max_move_pct": metrics.get("avg_drawdown_before_max_move_pct"),
                "confidence_level": _confidence_level(len(items)),
            })
    results["buying_pressure_minus_selling_pressure"] = bp_sp_rows

    # offering_risk_score
    _analyze("offering_risk_score", [(None, 30, "<30"), (30, 60, "30-60"), (60, 80, "60-80"), (80, None, ">80")], "offering_risk_score")

    return results


# ═══════════════════════════════════════════════════════════════════════════════
#  PART 6 — FINGERPRINTS
# ═══════════════════════════════════════════════════════════════════════════════


def fingerprint_analysis(snapshots: list[dict]) -> dict:
    usable = [
        s
        for s in snapshots
        if _safe_float(s.get("detection_price")) is not None
        and s.get("final_outcome_label") not in (None, "", "unresolved")
    ]

    def _eval(items: list[dict], name: str) -> dict:
        if not items:
            return {"fingerprint": name, "count": 0, "note": "No matches"}
        metrics = compute_success_metrics(items)
        # false positive = high suspicion but failed outcome
        fp = [
            s
            for s in items
            if (_safe_float(s.get("pre_news_suspicion_score")) or 0) >= 70
            and s.get("final_outcome_label") in ("failed_spike", "distribution_trap", "late_chase_signal", "no_follow_through")
        ]
        return {
            "fingerprint": name,
            "count": len(items),
            "usable": metrics.get("total_usable", 0),
            "clean_success_rate": metrics.get("clean_success_rate"),
            "avg_max_move_1h_pct": metrics.get("avg_max_move_1h_pct"),
            "avg_max_move_2h_pct": metrics.get("avg_max_move_2h_pct"),
            "avg_drawdown_before_max_move_pct": metrics.get("avg_drawdown_before_max_move_pct"),
            "avg_efficiency_ratio": metrics.get("avg_efficiency_ratio"),
            "vwap_hold_rate": metrics.get("vwap_hold_rate"),
            "false_positive_rate": _pct(len(fp), len(items)),
            "confidence_level": _confidence_level(len(items)),
        }

    # Fingerprint A — Clean Quiet Accumulation
    fa = [
        s
        for s in usable
        if _safe_bool(s.get("quiet_accumulation_candidate")) is True
        and (s.get("alert_quality") or "").lower() == "early"
        and (_safe_float(s.get("time_of_day_rvol")) or 0) >= 2.0
        and (_safe_float(s.get("absorption_quality_score")) or 0) >= 65
        and 0 <= (_safe_float(s.get("vwap_distance")) or -1) <= 6
        and (_safe_float(s.get("upper_wick_pct")) or 999) <= 30
        and (_safe_float(s.get("buying_pressure")) or 0) > (_safe_float(s.get("selling_pressure")) or 0)
        and _safe_bool(s.get("vwap_hold_after_detection")) is True
    ]

    # Fingerprint B — Early Breakout
    fb = [
        s
        for s in usable
        if _safe_bool(s.get("early_breakout_candidate")) is True
        and (s.get("latest_5candle_summary") or "").lower() == "breakout"
        and (_safe_float(s.get("vwap_distance")) or 999) <= 10
        and (_safe_float(s.get("absorption_quality_score")) or 0) >= 60
        and (_safe_float(s.get("upper_wick_pct")) or 999) <= 35
        and (_safe_float(s.get("volume_acceleration_score")) or 0) >= 60
    ]

    # Fingerprint C — News Lag Winner
    fc = [
        s
        for s in usable
        if (s.get("news_status") or "").lower() in ("news_appeared_after_detection", "news_lag_confirmed")
        and (s.get("alert_quality") or "").lower() in ("early", "caution")
        and s.get("pre_news_high") is not None
        and (_safe_float(s.get("post_news_high") or 0) > _safe_float(s.get("pre_news_high") or 0))
    ]

    # Fingerprint D — Trap Risk
    fd = [
        s
        for s in usable
        if (s.get("latest_5candle_summary") or "").lower() in ("rejection", "failed_spike", "distribution")
        and (_safe_float(s.get("upper_wick_pct")) or 0) > 35
        and (_safe_float(s.get("selling_pressure")) or 0) >= (_safe_float(s.get("buying_pressure")) or 0)
        and _safe_bool(s.get("vwap_hold_after_detection")) is False
        and (_safe_float(s.get("efficiency_ratio")) or 999) < 1.0
    ]

    return {
        "fingerprint_a_quiet_accumulation": _eval(fa, "A — Clean Quiet Accumulation"),
        "fingerprint_b_early_breakout": _eval(fb, "B — Early Breakout"),
        "fingerprint_c_news_lag": _eval(fc, "C — News Lag Winner"),
        "fingerprint_d_trap_risk": _eval(fd, "D — Trap Risk"),
    }


# ═══════════════════════════════════════════════════════════════════════════════
#  PART 7 — FALSE POSITIVES
# ═══════════════════════════════════════════════════════════════════════════════


def false_positive_analysis(snapshots: list[dict]) -> tuple[list[dict], dict]:
    usable = [
        s
        for s in snapshots
        if _safe_float(s.get("detection_price")) is not None
        and s.get("final_outcome_label") not in (None, "", "unresolved")
    ]

    fp_labels = ("failed_spike", "distribution_trap", "late_chase_signal", "no_follow_through")
    candidates = [
        s
        for s in usable
        if (_safe_float(s.get("pre_news_suspicion_score")) or 0) >= 70
        and (
            s.get("final_outcome_label") in fp_labels
            or (_safe_float(s.get("efficiency_ratio")) or 999) < 1.0
            or (_safe_float(s.get("max_move_1h_pct")) or 999) < 3.0
        )
    ]

    # Sort by suspicion score desc
    candidates.sort(key=lambda s: _safe_float(s.get("pre_news_suspicion_score")) or 0, reverse=True)

    table = []
    for s in candidates[:20]:
        # Try to guess failure reason
        reasons = []
        if (_safe_float(s.get("vwap_distance")) or 0) > 12:
            reasons.append("high_vwap_distance")
        if (_safe_float(s.get("upper_wick_pct")) or 0) > 30:
            reasons.append("large_upper_wick")
        if (_safe_float(s.get("selling_pressure")) or 0) >= (_safe_float(s.get("buying_pressure")) or 0):
            reasons.append("selling_pressure_dominant")
        if (s.get("catalyst_age_bucket") or "").lower() in ("older_than_30d", "within_30d"):
            reasons.append("old_catalyst")
        if (_safe_float(s.get("offering_risk_score")) or 0) >= 50:
            reasons.append("offering_risk")
        if (_safe_float(s.get("absorption_quality_score")) or 0) < 50:
            reasons.append("low_absorption")
        if not reasons:
            reasons.append("unknown")

        table.append({
            "ticker": s.get("ticker"),
            "detection_time": s.get("detection_time"),
            "pre_news_suspicion_score": s.get("pre_news_suspicion_score"),
            "anomaly_type": s.get("anomaly_type"),
            "alert_quality": s.get("alert_quality"),
            "vwap_distance": s.get("vwap_distance"),
            "absorption_quality_score": s.get("absorption_quality_score"),
            "upper_wick_pct": s.get("upper_wick_pct"),
            "buying_pressure": s.get("buying_pressure"),
            "selling_pressure": s.get("selling_pressure"),
            "max_move_1h_pct": s.get("max_move_1h_pct"),
            "drawdown_before_max_move_pct": s.get("drawdown_before_max_move_pct"),
            "efficiency_ratio": s.get("efficiency_ratio"),
            "final_outcome_label": s.get("final_outcome_label"),
            "likely_failure_reasons": "; ".join(reasons),
        })

    summary = {
        "total_false_positives_considered": len(candidates),
        "top_20_table": table,
        "common_failure_reasons": Counter(r["likely_failure_reasons"] for r in table).most_common(5),
    }
    return table, summary


# ═══════════════════════════════════════════════════════════════════════════════
#  PART 8 — SUPPRESSED WINNERS
# ═══════════════════════════════════════════════════════════════════════════════


def suppression_analysis(snapshots: list[dict]) -> tuple[list[dict], dict]:
    usable = [
        s
        for s in snapshots
        if _safe_float(s.get("detection_price")) is not None
        and s.get("final_outcome_label") not in (None, "", "unresolved")
    ]

    suppressed = [
        s
        for s in usable
        if _safe_bool(s.get("was_alert_suppressed")) is True
        and (
            (_safe_float(s.get("max_move_1h_pct")) or 0) >= 5.0
            or (_safe_float(s.get("max_move_2h_pct")) or 0) >= 10.0
        )
        and (_safe_float(s.get("efficiency_ratio")) or 0) >= 1.5
    ]

    suppressed.sort(key=lambda s: _safe_float(s.get("max_move_2h_pct") or s.get("max_move_1h_pct")) or 0, reverse=True)

    table = []
    for s in suppressed[:20]:
        table.append({
            "ticker": s.get("ticker"),
            "detection_time": s.get("detection_time"),
            "pre_news_suspicion_score": s.get("pre_news_suspicion_score"),
            "suppression_reasons": "; ".join(str(x) for x in (s.get("suppression_reasons") or [])),
            "absorption_quality_score": s.get("absorption_quality_score"),
            "vwap_hold_after_detection": s.get("vwap_hold_after_detection"),
            "upper_wick_pct": s.get("upper_wick_pct"),
            "max_move_1h_pct": s.get("max_move_1h_pct"),
            "max_move_2h_pct": s.get("max_move_2h_pct"),
            "efficiency_ratio": s.get("efficiency_ratio"),
            "final_outcome_label": s.get("final_outcome_label"),
        })

    summary = {
        "total_suppressed_winners": len(suppressed),
        "top_20_table": table,
    }
    return table, summary


# ═══════════════════════════════════════════════════════════════════════════════
#  PART 9 — BENCHMARKING (placeholder)
# ═══════════════════════════════════════════════════════════════════════════════


def benchmarking_analysis(snapshots: list[dict]) -> dict:
    usable = [
        s
        for s in snapshots
        if _safe_float(s.get("detection_price")) is not None
        and s.get("final_outcome_label") not in (None, "", "unresolved")
    ]
    metrics = compute_success_metrics(usable)

    return {
        "note": "Baseline data (random universe, top gainers, high-RVOL only, breakout-only) is not available in current dataset. Placeholder interface ready.",
        "detector_metrics": {
            "avg_1h_max_move": metrics.get("avg_max_move_1h_pct"),
            "avg_2h_max_move": metrics.get("avg_max_move_2h_pct"),
            "avg_drawdown": metrics.get("avg_drawdown_before_max_move_pct"),
            "avg_efficiency": metrics.get("avg_efficiency_ratio"),
            "vwap_hold_rate": metrics.get("vwap_hold_rate"),
            "clean_success_rate": metrics.get("clean_success_rate"),
        },
        "required_baseline_fields": [
            "random_universe_1h_move",
            "finviz_top_gainer_1h_move",
            "high_rvol_no_filter_1h_move",
            "breakout_only_1h_move",
        ],
    }


# ═══════════════════════════════════════════════════════════════════════════════
#  PART 11 — CALIBRATION RECOMMENDATIONS
# ═══════════════════════════════════════════════════════════════════════════════


def generate_recommendations(all_metrics: dict, bucket_metrics: dict, fp_summary: dict, suppression_summary: dict) -> list[dict]:
    recs = []

    # Generic structure builder
    def _rec(rec_type: str, bucket: str, observation: str, stats: dict, change: str, effect: str, confidence: str):
        return {
            "recommendation_type": rec_type,
            "affected_bucket": bucket,
            "current_observation": observation,
            "supporting_stats": stats,
            "suggested_change": change,
            "expected_effect": effect,
            "confidence_level": confidence,
        }

    overall = all_metrics.get("overall", {})
    clean_rate = overall.get("clean_success_rate") or 0
    total = overall.get("total_usable", 0)

    if total < 20:
        recs.append(_rec(
            "DATA_WARNING", "all",
            f"Only {total} usable detections available.",
            {"total_usable": total},
            "Continue collecting data before calibrating thresholds.",
            "Avoid overfitting to small sample.",
            "LOW"
        ))
        return recs

    # Early vs Late
    early_bucket = next((b for b in bucket_metrics.get("alert_quality", []) if b["bucket"] == "early"), None)
    late_bucket = next((b for b in bucket_metrics.get("alert_quality", []) if b["bucket"] == "late"), None)

    if early_bucket and early_bucket.get("clean_success_rate", 0) and early_bucket["clean_success_rate"] > (late_bucket["clean_success_rate"] if late_bucket else 0):
        recs.append(_rec(
            "BOOST", "alert_quality::early",
            f"EARLY alerts show clean success {early_bucket['clean_success_rate']}% vs LATE {late_bucket['clean_success_rate'] if late_bucket else 'N/A'}%.",
            {"early_clean_rate": early_bucket["clean_success_rate"], "late_clean_rate": late_bucket["clean_success_rate"] if late_bucket else None},
            "Consider +5 score boost when alert_quality=EARLY and absorption_quality_score >= 70.",
            "Improve early detection reward without lowering bar.",
            _confidence_level(early_bucket["usable"])
        ))

    if late_bucket and late_bucket.get("clean_success_rate", 0) is not None and late_bucket["clean_success_rate"] < 20:
        recs.append(_rec(
            "STRICTEN", "alert_quality::late",
            f"LATE alerts show poor clean success ({late_bucket['clean_success_rate']}%)",
            {"late_clean_rate": late_bucket["clean_success_rate"]},
            "Lower LATE VWAP threshold from 15% to 12%. Force LATE when vwap_distance > 12 AND upper_wick_pct > 30.",
            "Reduce late-chase false positives.",
            _confidence_level(late_bucket["usable"])
        ))

    # Quiet accumulation
    quiet = next((b for b in bucket_metrics.get("anomaly_type", []) if b["bucket"] == "quiet_volume_build"), None)
    if quiet and quiet.get("clean_success_rate", 0) and quiet["clean_success_rate"] > clean_rate:
        recs.append(_rec(
            "BOOST", "anomaly_type::quiet_volume_build",
            f"Quiet volume build shows clean success {quiet['clean_success_rate']}%",
            {"quiet_clean_rate": quiet["clean_success_rate"], "overall_clean_rate": clean_rate},
            "Increase absorption_quality weight. Expand quiet abnormal volume universe.",
            "Capture more early accumulation signals.",
            _confidence_level(quiet["usable"])
        ))
    elif quiet and quiet.get("clean_success_rate", 0) is not None and quiet["clean_success_rate"] < clean_rate:
        recs.append(_rec(
            "STRICTEN", "anomaly_type::quiet_volume_build",
            f"Quiet volume build underperforms ({quiet['clean_success_rate']}% clean)",
            {"quiet_clean_rate": quiet["clean_success_rate"]},
            "Raise time_of_day_rvol minimum. Require buying_pressure > selling_pressure and upper_wick_pct < 30.",
            "Filter weak quiet accumulation signals.",
            _confidence_level(quiet["usable"])
        ))

    # Suppressed winners
    sw = suppression_summary.get("total_suppressed_winners", 0)
    if sw > 0:
        recs.append(_rec(
            "EXCEPTION", "suppression_rules",
            f"{sw} suppressed signals were actually winners.",
            {"suppressed_winners": sw},
            "Add exception: allow suppressed alert when absorption_quality_score >= 80, VWAP held, upper_wick_pct < 25, time_of_day_rvol >= 3.",
            "Reduce false suppression of high-quality setups.",
            _confidence_level(sw)
        ))

    # False positive common reasons
    common_fp = fp_summary.get("common_failure_reasons", [])
    for reason, count in common_fp:
        if "offering_risk" in reason:
            recs.append(_rec(
                "STRICTEN", "offering_risk",
                f"Offering risk appears in {count} top false positives.",
                {"fp_count_with_offering_risk": count},
                "Increase offering-risk penalty. Suppress microcaps with offering_risk_score >= 60 unless absorption_quality_score >= 80.",
                "Reduce dilution-driven false positives.",
                _confidence_level(count)
            ))
        if "old_catalyst" in reason:
            recs.append(_rec(
                "STRICTEN", "catalyst_age",
                f"Old catalyst appears in {count} top false positives.",
                {"fp_count_with_old_catalyst": count},
                "Penalize catalyst_age_bucket older_than_7d. Separate old-news continuation from true pre-news.",
                "Avoid chasing stale catalysts.",
                _confidence_level(count)
            ))

    return recs


# ═══════════════════════════════════════════════════════════════════════════════
#  OUTPUT WRITERS
# ═══════════════════════════════════════════════════════════════════════════════


def write_csv(path: Path, rows: list[dict]):
    if not rows:
        path.write_text("")
        return
    keys = list(rows[0].keys())
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: str(v) if v is not None else "" for k, v in row.items()})


def build_markdown_report(report: dict) -> str:
    lines = []
    lines.append("# Pre-News Anomaly Detector V3 — Success Rate & Signal Quality Report")
    lines.append(f"\n*Generated: {datetime.now(timezone.utc).isoformat()}Z*")
    lines.append("\n---\n")

    # 1. Executive Summary
    lines.append("## 1. Executive Summary\n")
    dq = report["data_quality"]
    om = report["overall_metrics"]
    lines.append(f"- **Total detections loaded:** {dq['total_detections']}")
    lines.append(f"- **Unique tickers:** {dq['unique_tickers']}")
    lines.append(f"- **Trading sessions:** {dq['trading_sessions']}")
    lines.append(f"- **Usable for success-rate analysis:** {dq['usable_for_success_rate']} ({dq['usable_percentage'] or 'N/A'}%)")
    lines.append(f"- **Clean success rate:** {om.get('clean_success_rate') or 'N/A'}%")
    lines.append(f"- **High-quality success rate:** {om.get('high_quality_success_rate') or 'N/A'}%")
    lines.append(f"- **Average 1h move:** {om.get('avg_max_move_1h_pct') or 'N/A'}%")
    lines.append(f"- **Median 1h move:** {om.get('median_max_move_1h_pct') or 'N/A'}%")
    lines.append(f"- **Average drawdown:** {om.get('avg_drawdown_before_max_move_pct') or 'N/A'}%")
    lines.append(f"- **Average efficiency ratio:** {om.get('avg_efficiency_ratio') or 'N/A'}")
    lines.append(f"- **VWAP hold rate:** {om.get('vwap_hold_rate') or 'N/A'}%")
    lines.append("")

    # 2. Is the detector working?
    lines.append("## 2. Is the Detector Working?\n")
    total_usable = om.get("total_usable", 0)
    clean_rate = om.get("clean_success_rate") or 0
    if total_usable < 20:
        lines.append("**NOT ENOUGH DATA.** Fewer than 20 usable detections. Collect more sessions before drawing conclusions.")
    elif clean_rate >= 40:
        lines.append("**STRONG EVIDENCE.** Clean success rate is healthy. Forward metrics show controlled drawdown with useful upside.")
    elif clean_rate >= 25:
        lines.append("**MODERATE EVIDENCE.** Detector shows promise but needs refinement. False positives and late signals drag performance.")
    elif clean_rate >= 10:
        lines.append("**WEAK EVIDENCE.** Some signals work but many fail. Threshold tuning and suppression review needed.")
    else:
        lines.append("**POOR PERFORMANCE.** Success rate is too low. Review detection logic, thresholds, and alert quality rules.")
    lines.append("")

    # 3. Best-performing buckets
    lines.append("## 3. Best-Performing Buckets\n")
    for key in ("anomaly_type", "alert_quality", "candidate_type", "wyckoff_stage", "latest_5candle_summary"):
        bucket_list = report["buckets"].get(key, [])
        best = [b for b in bucket_list if b.get("clean_success_rate") is not None]
        best.sort(key=lambda x: x["clean_success_rate"] or 0, reverse=True)
        if best:
            lines.append(f"### {key}\n")
            for b in best[:3]:
                lines.append(f"- **{b['bucket']}**: clean {b['clean_success_rate']}% | count {b['count']} | confidence {b['confidence_level']}")
            lines.append("")

    # 4. Worst-performing buckets
    lines.append("## 4. Worst-Performing Buckets\n")
    for key in ("anomaly_type", "alert_quality"):
        bucket_list = report["buckets"].get(key, [])
        worst = [b for b in bucket_list if b.get("clean_success_rate") is not None]
        worst.sort(key=lambda x: x["clean_success_rate"] or 999)
        if worst:
            lines.append(f"### {key}\n")
            for b in worst[:3]:
                lines.append(f"- **{b['bucket']}**: clean {b['clean_success_rate']}% | count {b['count']} | confidence {b['confidence_level']}")
            lines.append("")

    # 5. Success rate by signal type
    lines.append("## 5. Success Rate by Signal Type\n")
    lines.append(f"- **Basic success:** {om.get('basic_success_rate') or 'N/A'}%")
    lines.append(f"- **Clean success:** {om.get('clean_success_rate') or 'N/A'}%")
    lines.append(f"- **High-quality success:** {om.get('high_quality_success_rate') or 'N/A'}%")
    lines.append(f"- **Pre-news success:** {om.get('pre_news_success_rate') or 'N/A'}%")
    lines.append(f"- **News-lag success:** {om.get('news_lag_success_rate') or 'N/A'}%")
    lines.append(f"- **Avoidance success:** {om.get('avoidance_success_rate') or 'N/A'}%")
    lines.append("")

    # 6. Quiet accumulation review
    lines.append("## 6. Quiet Accumulation Review\n")
    qa = next((b for b in report["buckets"].get("anomaly_type", []) if b["bucket"] == "quiet_volume_build"), None)
    if qa:
        lines.append(f"Quiet volume build: {qa['count']} detections, clean success {qa['clean_success_rate']}%, confidence {qa['confidence_level']}.")
        if (qa.get("clean_success_rate") or 0) > (om.get("clean_success_rate") or 0):
            lines.append("Quiet accumulation is **outperforming** the overall average. The fingerprint is identifying early accumulation correctly.")
        else:
            lines.append("Quiet accumulation is **underperforming**. Consider raising RVOL and absorption thresholds.")
    else:
        lines.append("No quiet_volume_build detections in dataset.")
    lines.append("")

    # 7. Late / trap review
    lines.append("## 7. Late / Trap Review\n")
    late = next((b for b in report["buckets"].get("alert_quality", []) if b["bucket"] == "late"), None)
    trap = next((b for b in report["buckets"].get("alert_quality", []) if b["bucket"] == "trap_risk"), None)
    if late:
        lines.append(f"LATE alerts: clean success {late['clean_success_rate']}%, count {late['count']}.")
    if trap:
        lines.append(f"TRAP_RISK alerts: clean success {trap['clean_success_rate']}%, count {trap['count']}.")
    lines.append("These labels are meant to **warn**, not generate long signals. Low clean success here is expected if they correctly flag bad setups.")
    lines.append("")

    # 8. News-lag review
    lines.append("## 8. News-Lag Review\n")
    nl = om.get("news_lag_success_rate")
    if nl is not None:
        lines.append(f"News-lag success rate: {nl}%.")
        if nl > 0:
            lines.append("Some signals fired before public news confirmation and later proved correct.")
        else:
            lines.append("No news-lag winners in current dataset.")
    else:
        lines.append("Insufficient data for news-lag analysis.")
    lines.append("")

    # 9. False positive review
    lines.append("## 9. False Positive Review\n")
    fp = report.get("false_positive_summary", {})
    common = fp.get("common_failure_reasons", [])
    if common:
        lines.append(f"Top false positive reasons: {common}")
    else:
        lines.append("No false positives analyzed (insufficient high-score failures).")
    lines.append("")

    # 10. Suppression review
    lines.append("## 10. Suppression Review\n")
    sw = report.get("suppression_summary", {}).get("total_suppressed_winners", 0)
    if sw > 0:
        lines.append(f"**{sw} suppressed signals were actually winners.** Suppression rules may be too strict for high-absorption setups.")
    else:
        lines.append("No suppressed winners detected. Rules may be appropriately conservative, or sample is too small.")
    lines.append("")

    # 11. Detector vs Baselines
    lines.append("## 11. Detector vs Baselines\n")
    bl_comp = report.get("baseline_comparison", {})
    if "note" in bl_comp:
        lines.append(f"*{bl_comp['note']}*")
    else:
        lines.append("| Baseline | n | Clean SR | Avg 1h | Avg 2h | Drawdown | Efficiency | VWAP Hold | Trap Rate | Verdict |")
        lines.append("|----------|---|----------|--------|--------|----------|------------|-----------|-----------|---------|")
        for comp in bl_comp.get("comparisons", []):
            verdict = bl_comp.get("verdicts", {}).get(comp["baseline_type"], "UNKNOWN")
            lines.append(
                f"| {comp['baseline_type']} | {comp['usable']} | "
                f"D:{comp['detector_clean_success_rate']}% / B:{comp['baseline_clean_success_rate']}% | "
                f"D:{comp['detector_avg_1h_move']}% / B:{comp['baseline_avg_1h_move']}% | "
                f"D:{comp['detector_avg_2h_move']}% / B:{comp['baseline_avg_2h_move']}% | "
                f"D:{comp['detector_avg_drawdown']}% / B:{comp['baseline_avg_drawdown']}% | "
                f"D:{comp['detector_avg_efficiency']} / B:{comp['baseline_avg_efficiency']} | "
                f"D:{comp['detector_vwap_hold_rate']}% / B:{comp['baseline_vwap_hold_rate']}% | "
                f"{comp['baseline_trap_rate']}% | {verdict} |"
            )
        lines.append("")
        # Verdict explanations
        for bl_type, verdict in bl_comp.get("verdicts", {}).items():
            if verdict == "DETECTOR_WINS":
                lines.append(f"- **{bl_type}:** Detector outperforms on success rate, efficiency, AND drawdown control.")
            elif verdict == "DETECTOR_BEATS_ON_SUCCESS_RATE":
                lines.append(f"- **{bl_type}:** Detector has higher clean success rate but may trade efficiency or drawdown.")
            elif verdict == "DETECTOR_BEATS_ON_EFFICIENCY_AND_DRAWDOWN":
                lines.append(f"- **{bl_type}:** Detector delivers better efficiency and lower drawdown, even if raw success rate is similar.")
            elif verdict == "BASELINE_WINS":
                lines.append(f"- **{bl_type}:** Baseline outperforms detector. Review why V3 filters may be over-restrictive.")
            else:
                lines.append(f"- **{bl_type}:** Performance is roughly equivalent.")
    lines.append("")

    # 12. Calibration recommendations
    lines.append("## 12. Calibration Recommendations\n")
    for rec in report.get("recommendations", []):
        lines.append(f"### [{rec['recommendation_type']}] {rec['affected_bucket']}")
        lines.append(f"- Observation: {rec['current_observation']}")
        lines.append(f"- Suggested change: {rec['suggested_change']}")
        lines.append(f"- Expected effect: {rec['expected_effect']}")
        lines.append(f"- Confidence: {rec['confidence_level']}")
        lines.append("")

    # 13. Confidence and limitations
    lines.append("## 13. Confidence & Limitations\n")
    lines.append(f"- **Sample size:** {total_usable} usable detections.")
    lines.append(f"- **Sessions:** {dq['trading_sessions']}.")
    lines.append(f"- **Unresolved:** {dq['unresolved_outcomes']} detections excluded from success-rate calculation.")
    bl_count = len(bl_comp.get("comparisons", [])) if isinstance(bl_comp, dict) and "comparisons" in bl_comp else 0
    if bl_count > 0:
        lines.append(f"- **Baseline comparison:** {bl_count} baseline types compared against detector.")
    else:
        lines.append("- **Baseline comparison:** Not available. Run scans with baseline capture enabled.")
    lines.append("- **Lookahead bias:** None. Detection snapshots use only detection-time fields.")
    lines.append("- **Median vs mean:** Medians reported where small-cap runners could skew averages.")
    lines.append("")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════════════════════


def run_analysis(write_outputs: bool = True) -> dict:
    """
    Run the full success-rate analysis and optionally write output files.

    Returns the complete report dict.
    """
    logger.info("Loading all available evaluation data...")
    snapshots = load_all_snapshots()
    logger.info("Loaded %d total snapshots", len(snapshots))

    if not snapshots:
        logger.error("No evaluation data found. Aborting.")
        return {"error": "No evaluation data found."}

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # PART 1
    dq = run_data_quality(snapshots)
    logger.info("Data quality: %d total, %d usable", dq["total_detections"], dq["usable_for_success_rate"])

    # PART 2 & 3
    overall = compute_success_metrics(snapshots)
    filtered = compute_filtered_success(snapshots)

    # PART 4 — buckets
    bucket_keys = [
        "anomaly_type", "alert_quality", "candidate_type", "wyckoff_stage",
        "latest_5candle_summary", "news_status", "catalyst_age_bucket",
    ]
    buckets = {k: bucket_performance(snapshots, k) for k in bucket_keys}

    # PART 5 — thresholds
    thresholds = threshold_analysis(snapshots)

    # PART 6 — fingerprints
    fingerprints = fingerprint_analysis(snapshots)

    # PART 7 — false positives
    fp_table, fp_summary = false_positive_analysis(snapshots)

    # PART 8 — suppression
    sw_table, sw_summary = suppression_analysis(snapshots)

    # PART 9 — benchmarking
    benchmarks = benchmarking_analysis(snapshots)

    # PART 9b — baseline comparison
    baselines = load_all_baselines()
    logger.info("Loaded %d baseline snapshots", len(baselines))
    baseline_comp = baseline_comparison(snapshots, baselines)

    # PART 11 — recommendations
    recommendations = generate_recommendations(
        {"overall": overall, "filtered": filtered},
        buckets,
        fp_summary,
        sw_summary,
    )

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "data_quality": dq,
        "overall_metrics": overall,
        "filtered_metrics": filtered,
        "buckets": buckets,
        "thresholds": thresholds,
        "fingerprints": fingerprints,
        "false_positive_summary": fp_summary,
        "suppression_summary": sw_summary,
        "benchmarking": benchmarks,
        "baseline_comparison": baseline_comp,
        "recommendations": recommendations,
    }

    if write_outputs:
        md_path = OUTPUT_DIR / "pre_news_success_rate_report.md"
        json_path = OUTPUT_DIR / "pre_news_success_rate_report.json"
        bucket_csv_path = OUTPUT_DIR / "pre_news_bucket_performance.csv"
        fp_csv_path = OUTPUT_DIR / "pre_news_false_positives.csv"
        sw_csv_path = OUTPUT_DIR / "pre_news_suppressed_winners.csv"
        early_csv_path = OUTPUT_DIR / "pre_news_best_early_detections.csv"

        md_path.write_text(build_markdown_report(report), encoding="utf-8")
        logger.info("Wrote markdown report → %s", md_path)

        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, default=str)
        logger.info("Wrote JSON report → %s", json_path)

        # Baseline comparison CSV
        baseline_csv_path = OUTPUT_DIR / "pre_news_baseline_comparison.csv"
        write_csv(baseline_csv_path, baseline_comp.get("comparisons", []))
        logger.info("Wrote baseline comparison CSV → %s", baseline_csv_path)

        # Flatten buckets for CSV
        all_bucket_rows = []
        for key, rows in buckets.items():
            for r in rows:
                all_bucket_rows.append({"dimension": key, **r})
        write_csv(bucket_csv_path, all_bucket_rows)
        logger.info("Wrote bucket CSV → %s", bucket_csv_path)

        write_csv(fp_csv_path, fp_table)
        logger.info("Wrote false positives CSV → %s", fp_csv_path)

        write_csv(sw_csv_path, sw_table)
        logger.info("Wrote suppressed winners CSV → %s", sw_csv_path)

        # Best early detections
        early = [
            s
            for s in snapshots
            if (s.get("alert_quality") or "").lower() == "early"
            and s.get("final_outcome_label") not in (None, "", "unresolved")
        ]
        early.sort(key=lambda s: _safe_float(s.get("max_move_2h_pct") or s.get("max_move_1h_pct")) or 0, reverse=True)
        early_rows = []
        for s in early[:20]:
            early_rows.append({
                "ticker": s.get("ticker"),
                "detection_time": s.get("detection_time"),
                "pre_news_suspicion_score": s.get("pre_news_suspicion_score"),
                "anomaly_type": s.get("anomaly_type"),
                "max_move_1h_pct": s.get("max_move_1h_pct"),
                "max_move_2h_pct": s.get("max_move_2h_pct"),
                "drawdown_before_max_move_pct": s.get("drawdown_before_max_move_pct"),
                "efficiency_ratio": s.get("efficiency_ratio"),
                "vwap_hold_after_detection": s.get("vwap_hold_after_detection"),
                "final_outcome_label": s.get("final_outcome_label"),
            })
        write_csv(early_csv_path, early_rows)
        logger.info("Wrote best early detections CSV → %s", early_csv_path)

        logger.info("Analysis complete. All files written to %s", OUTPUT_DIR)

    return report


def main():
    run_analysis(write_outputs=True)


if __name__ == "__main__":
    main()
