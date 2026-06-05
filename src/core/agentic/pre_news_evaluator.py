"""
Pre-News Anomaly Detector — V3 Evaluation Harness

Records every detection as an immutable snapshot, tracks forward performance,
labels outcomes, compares anomaly buckets, and suggests calibration improvements.

Design principles:
- Detection snapshots are immutable (only forward-outcome fields mutate).
- No lookahead bias: snapshots capture only info available at detection time.
- Forward tracking updates at 30m, 1h, 2h, and EOD intervals.
- Thresholds are configurable in one place (OutcomeThresholds).
"""

from __future__ import annotations

import csv
import json
import logging
import math
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Optional

from src.utils.atomic_json import save_json_file, load_json_file

from src.core.agentic.pre_news_models import (
    AlertQuality,
    AnomalyType,
    CandidateType,
    FinalOutcomeLabel,
    NewsStatus,
    PreNewsAnomaly,
    PreNewsDetectionSnapshot,
    PreNewsState,
    PriceBehaviour,
    WyckoffStage,
)

logger = logging.getLogger(__name__)

from src.utils.data_paths import AGENTIC_DATA_DIR as DATA_DIR
SNAPSHOTS_FILE = DATA_DIR / "pre_news_evaluation_snapshots.json"
REPORTS_DIR = DATA_DIR / "evaluation_reports"


# ═══════════════════════════════════════════════════════════════════════════════
#  CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class OutcomeThresholds:
    """Configurable thresholds for outcome labeling."""
    meaningful_move_pct: float = 5.0
    controlled_drawdown_ratio: float = 0.5
    max_drawdown_pct: float = 3.0
    vwap_loss_consecutive_closes: int = 2
    late_chase_vwap_distance: float = 15.0
    late_chase_price_from_open: float = 15.0
    efficiency_safe_denominator: float = 0.25
    old_catalyst_max_age_hours: float = 168.0  # 7 days
    trap_upper_wick_threshold: float = 30.0
    trap_selling_pressure_dominance: float = 60.0


DEFAULT_THRESHOLDS = OutcomeThresholds()


# ═══════════════════════════════════════════════════════════════════════════════
#  SNAPSHOT CREATION
# ═══════════════════════════════════════════════════════════════════════════════


def create_detection_snapshot(
    anomaly: PreNewsAnomaly,
    detection_source: str = "scan",
) -> PreNewsDetectionSnapshot:
    """Create an immutable snapshot from a PreNewsAnomaly at detection time."""

    vm = anomaly.volume_metrics
    pb = anomaly.price_behaviour

    # Compute session date from detection time
    dt = anomaly.detected_at.astimezone(timezone.utc)
    session_date = dt.strftime("%Y-%m-%d")

    # Compute price change from open
    open_price = None
    price_change_from_open_pct = 0.0
    if anomaly.price and anomaly.detection_price:
        open_price = anomaly.price  # best approximation; caller can refine
        price_change_from_open_pct = pb.distance_from_open_pct

    # Build data quality score (0-100)
    dq_score = 100.0
    if anomaly.data_quality_state.value == "partial":
        dq_score = 60.0
    elif anomaly.data_quality_state.value == "degraded":
        dq_score = 30.0
    elif anomaly.data_quality_state.value == "stale":
        dq_score = 10.0

    # Determine dilution risk tag
    dilution_tag = ""
    if anomaly.offering_risk_score >= 60:
        dilution_tag = "severe"
    elif anomaly.offering_risk_score >= 40:
        dilution_tag = "elevated"
    elif anomaly.offering_risk_score >= 20:
        dilution_tag = "moderate"
    else:
        dilution_tag = "low"

    # Compute float rotation approximation
    float_rot = None
    if vm.current_volume and anomaly.float_shares and anomaly.float_shares > 0:
        float_rot = round(vm.current_volume / anomaly.float_shares, 4)

    # Determine if alert was suppressed
    was_suppressed = (
        anomaly.alert_quality == AlertQuality.SUPPRESSED
        or len(anomaly.alert_suppression_reasons) > 0
    )

    snapshot = PreNewsDetectionSnapshot(
        ticker=anomaly.ticker,
        detection_id=anomaly.id,
        detection_time=anomaly.detected_at,
        session_date=session_date,
        detection_source=detection_source,
        discovery_bucket=anomaly.discovery_source,

        detection_price=anomaly.detection_price or anomaly.price,
        open_price=open_price,
        previous_close=None,  # caller can backfill if available
        day_high_at_detection=None,
        day_low_at_detection=None,
        vwap_at_detection=None,
        vwap_distance=pb.vwap_distance_pct,
        price_change_pct=pb.price_change_pct,
        price_change_from_open_pct=price_change_from_open_pct,

        current_volume=vm.current_volume,
        average_volume=vm.avg_volume,
        relative_volume=vm.rvol_current,
        time_of_day_rvol=vm.time_of_day_rvol,
        intraday_volume_curve_deviation=vm.intraday_volume_curve_deviation,
        current_5m_volume_zscore=vm.current_5m_volume_zscore,
        session_progress_adjusted_volume_score=vm.session_progress_adjusted_volume_score,
        volume_acceleration_score=vm.volume_acceleration_score,
        abnormal_volume_score=vm.abnormal_volume_score,
        float_rotation=float_rot,
        float_pressure=anomaly.float_pressure_score,

        pre_news_suspicion_score=anomaly.pre_news_suspicion_score,
        anomaly_type=anomaly.anomaly_type.value,
        price_behaviour=pb.behaviour.value,
        wyckoff_stage=anomaly.wyckoff_stage.value,
        alert_quality=anomaly.alert_quality.value,
        candidate_type=anomaly.candidate_type.value,
        quiet_accumulation_candidate=anomaly.candidate_type == CandidateType.QUIET_ACCUMULATION,
        early_breakout_candidate=anomaly.candidate_type == CandidateType.EARLY_BREAKOUT,

        latest_5candle_summary=pb.latest_5candle_summary,
        buying_pressure=pb.latest_5candle_buying_pressure,
        selling_pressure=pb.latest_5candle_selling_pressure,
        wick_dominance=pb.latest_5candle_wick_dominance,
        upper_wick_pct=pb.upper_wick_pct,
        lower_wick_pct=pb.lower_wick_pct,
        absorption_quality_score=pb.absorption_quality_score,
        absorption_score=pb.score,
        supply_rejection_score=max(0, pb.upper_wick_pct - pb.lower_wick_pct),
        vwap_hold_count=0,
        vwap_loss_count=0,

        news_status=anomaly.news_status.value,
        catalyst_age_bucket=anomaly.catalyst_age_bucket.value,
        catalyst_relevance_score=anomaly.catalyst_relevance_score,
        catalyst_source=anomaly.catalyst_source,
        matched_headline=anomaly.matched_headline,
        matched_headline_time=anomaly.matched_headline_time,
        catalyst_age_minutes=anomaly.catalyst_age_minutes,

        offering_risk_score=anomaly.offering_risk_score,
        dilution_risk_tag=dilution_tag,
        market_cap=anomaly.market_cap,
        float_shares=anomaly.float_shares,
        liquidity_score=None,
        data_quality_score=dq_score,
        suppression_reasons=list(anomaly.alert_suppression_reasons),
        was_alert_suppressed=was_suppressed,
        alert_sent=anomaly.alert_sent,

        # Forward placeholders
        final_outcome_label="unresolved",
        recorded_at=datetime.now(timezone.utc),
        last_updated_at=datetime.now(timezone.utc),
    )
    return snapshot


# ═══════════════════════════════════════════════════════════════════════════════
#  FORWARD TRACKING
# ═══════════════════════════════════════════════════════════════════════════════


def update_forward_prices(
    snapshot: PreNewsDetectionSnapshot,
    current_price: float,
    current_time: datetime,
    vwap: Optional[float] = None,
) -> bool:
    """
    Update max prices at 30m, 1h, 2h, and same-day intervals.
    Also track min price after detection and VWAP outcomes.
    Returns True if any forward field was updated.
    """
    if current_price <= 0 or snapshot.detection_price <= 0:
        return False

    elapsed = (current_time - snapshot.detection_time).total_seconds()
    updated = False

    # Track min price after detection
    if snapshot.min_price_after_detection is None or current_price < snapshot.min_price_after_detection:
        snapshot.min_price_after_detection = round(current_price, 4)
        updated = True

    # Max price buckets
    def _maybe_update(field: str, seconds: float):
        nonlocal updated
        if elapsed >= seconds:
            existing = getattr(snapshot, field)
            if existing is None or current_price > existing:
                setattr(snapshot, field, round(current_price, 4))
                updated = True

    _maybe_update("max_price_30m", 30 * 60)
    _maybe_update("max_price_1h", 60 * 60)
    _maybe_update("max_price_2h", 2 * 60 * 60)
    _maybe_update("max_price_same_day", 6.5 * 60 * 60)  # ~full session

    # VWAP tracking
    if vwap is not None and current_price > 0:
        if current_price < vwap:
            snapshot.vwap_closes_below_count += 1
        else:
            if snapshot.vwap_closes_below_count > 0:
                snapshot.vwap_reclaimed = True
            snapshot.vwap_closes_below_count = 0

        if snapshot.first_vwap_loss_time is None and current_price < vwap:
            snapshot.first_vwap_loss_time = current_time

        if snapshot.vwap_hold_after_detection is None:
            snapshot.vwap_hold_after_detection = current_price >= vwap

    if updated:
        snapshot.last_updated_at = current_time

    return updated


def _pct_move(entry: float, exit_: Optional[float]) -> Optional[float]:
    if entry <= 0 or exit_ is None:
        return None
    return round(((exit_ - entry) / entry) * 100, 2)


def calculate_max_move_percentages(snapshot: PreNewsDetectionSnapshot) -> bool:
    """Populate max_move_*_pct fields from max_price_* fields."""
    entry = snapshot.detection_price
    if entry <= 0:
        return False

    updated = False
    for field in ("max_price_30m", "max_price_1h", "max_price_2h", "max_price_same_day"):
        price = getattr(snapshot, field)
        pct_field = field.replace("max_price_", "max_move_") + "_pct"
        if price is not None:
            setattr(snapshot, pct_field, _pct_move(entry, price))
            updated = True

    return updated


def calculate_drawdown_before_max(snapshot: PreNewsDetectionSnapshot) -> bool:
    """
    Find the lowest price BEFORE the max favorable move price was achieved.
    If max move hasn't happened yet, use current min.
    """
    entry = snapshot.detection_price
    if entry <= 0:
        return False

    # Determine which max price bucket is populated (furthest out)
    max_price = None
    for field in ("max_price_same_day", "max_price_2h", "max_price_1h", "max_price_30m"):
        if getattr(snapshot, field) is not None:
            max_price = getattr(snapshot, field)
            break

    if max_price is None:
        return False

    # Without a full bar history we approximate:
    # drawdown = max(entry, max_price) - entry for long bias
    # Actually for a bullish detector, favorable move = up
    # Drawdown = lowest price after detection, before max was reached
    # Approximation: use min_price_after_detection if it occurred before max
    min_p = snapshot.min_price_after_detection
    if min_p is not None and min_p < entry and entry > 0:
        dd = entry - min_p
        snapshot.drawdown_before_max_move = round(dd, 4)
        snapshot.drawdown_before_max_move_pct = round((dd / entry) * 100, 2)
        snapshot.lowest_price_before_max = round(min_p, 4)
    else:
        snapshot.drawdown_before_max_move = 0.0
        snapshot.drawdown_before_max_move_pct = 0.0
        snapshot.lowest_price_before_max = entry

    return True


def calculate_efficiency_ratio(
    snapshot: PreNewsDetectionSnapshot,
    thresholds: OutcomeThresholds = DEFAULT_THRESHOLDS,
) -> bool:
    """
    Efficiency = max_favorable_move / max_drawdown_before_move.
    Safe denominator prevents divide-by-zero.
    """
    entry = snapshot.detection_price
    if entry <= 0:
        return False

    # Use best available max move
    max_move_pct = None
    for field in ("max_move_same_day_pct", "max_move_2h_pct", "max_move_1h_pct", "max_move_30m_pct"):
        max_move_pct = getattr(snapshot, field)
        if max_move_pct is not None:
            break

    if max_move_pct is None or max_move_pct <= 0:
        snapshot.efficiency_ratio = 0.0
        return True

    dd_pct = snapshot.drawdown_before_max_move_pct or 0.0
    safe_dd = max(dd_pct, thresholds.efficiency_safe_denominator)
    snapshot.efficiency_ratio = round(max_move_pct / safe_dd, 2)

    # Label clean vs choppy
    if max_move_pct >= thresholds.meaningful_move_pct and dd_pct <= max_move_pct * thresholds.controlled_drawdown_ratio:
        snapshot.clean_or_choppy = "clean"
    elif dd_pct > max_move_pct * 0.75:
        snapshot.clean_or_choppy = "choppy"
    else:
        snapshot.clean_or_choppy = "moderate"

    return True


# ═══════════════════════════════════════════════════════════════════════════════
#  FINAL OUTCOME LABELING
# ═══════════════════════════════════════════════════════════════════════════════


def finalize_outcome_label(
    snapshot: PreNewsDetectionSnapshot,
    thresholds: OutcomeThresholds = DEFAULT_THRESHOLDS,
    force: bool = False,
) -> str:
    """
    Apply final outcome label based on forward data.
    Returns the label string. Only overwrites 'unresolved' unless force=True.
    """
    if snapshot.final_outcome_label != "unresolved" and not force:
        return snapshot.final_outcome_label

    entry = snapshot.detection_price
    if entry <= 0:
        snapshot.final_outcome_label = "unresolved"
        return snapshot.final_outcome_label

    # Determine best available max move
    max_move_pct = None
    for field in ("max_move_same_day_pct", "max_move_2h_pct", "max_move_1h_pct", "max_move_30m_pct"):
        max_move_pct = getattr(snapshot, field)
        if max_move_pct is not None:
            break

    dd_pct = snapshot.drawdown_before_max_move_pct or 0.0
    vwap_held = snapshot.vwap_hold_after_detection
    vwap_lost = snapshot.first_vwap_loss_time is not None
    eff = snapshot.efficiency_ratio or 0.0

    # News appeared after detection?
    news_after = snapshot.time_gap_detection_to_news is not None and snapshot.time_gap_detection_to_news > 0
    old_catalyst = snapshot.news_status in ("old_catalyst_present",)
    no_fresh_news = snapshot.news_status in (
        "no_news_found",
        "no_public_news_found_in_sources",
        "unknown_news_status",
    )

    label = "unresolved"
    notes: list[str] = []

    # ── LATE_CHASE_SIGNAL ────────────────────────────────────────────────
    if (
        snapshot.alert_quality == "late"
        or snapshot.vwap_distance > thresholds.late_chase_vwap_distance
        or snapshot.price_change_from_open_pct > thresholds.late_chase_price_from_open
    ):
        if max_move_pct is not None and max_move_pct < thresholds.meaningful_move_pct:
            label = "late_chase_signal"
            notes.append(f"Late chase: VWAP dist {snapshot.vwap_distance:.1f}%, max move {max_move_pct:.1f}%")

    # ── DISTRIBUTION_TRAP ────────────────────────────────────────────────
    if (
        snapshot.price_behaviour in ("rejection", "distribution", "failed_spike")
        or snapshot.upper_wick_pct > thresholds.trap_upper_wick_threshold
        or snapshot.selling_pressure > thresholds.trap_selling_pressure_dominance
    ):
        if vwap_lost or (max_move_pct is not None and max_move_pct < 2.0):
            label = "distribution_trap"
            notes.append(f"Trap: upper wick {snapshot.upper_wick_pct:.1f}%, selling pressure {snapshot.selling_pressure:.0f}")

    # ── FAILED_SPIKE ──────────────────────────────────────────────────────
    if (
        snapshot.price_behaviour in ("failed_spike", "rejection")
        and max_move_pct is not None
        and max_move_pct < 3.0
        and dd_pct > 2.0
    ):
        label = "failed_spike"
        notes.append(f"Failed spike: max move {max_move_pct:.1f}%, drawdown {dd_pct:.1f}%")

    # ── NO_FOLLOW_THROUGH ────────────────────────────────────────────────
    if label == "unresolved" and max_move_pct is not None:
        if max_move_pct < thresholds.meaningful_move_pct:
            label = "no_follow_through"
            notes.append(f"No follow-through: max move {max_move_pct:.1f}% < threshold {thresholds.meaningful_move_pct}%")

    # ── CLEAN_PRE_NEWS_WINNER ────────────────────────────────────────────
    if label == "unresolved":
        if (
            no_fresh_news
            and snapshot.alert_quality in ("early", "caution")
            and (vwap_held is not False)
            and max_move_pct is not None
            and max_move_pct >= thresholds.meaningful_move_pct
            and dd_pct <= max_move_pct * thresholds.controlled_drawdown_ratio
            and snapshot.latest_5candle_summary in ("accumulation", "breakout", "neutral", "")
        ):
            label = "clean_pre_news_winner"
            notes.append(f"Clean winner: +{max_move_pct:.1f}% with {dd_pct:.1f}% drawdown, VWAP held")

    # ── NEWS_LAG_CONFIRMED_WINNER ────────────────────────────────────────
    if label == "unresolved":
        if (
            news_after
            and max_move_pct is not None
            and max_move_pct >= thresholds.meaningful_move_pct
        ):
            label = "news_lag_confirmed_winner"
            if snapshot.pre_news_high and snapshot.post_news_high:
                notes.append(
                    f"News lag confirmed: pre-news high ${snapshot.pre_news_high:.2f}, "
                    f"post-news high ${snapshot.post_news_high:.2f}"
                )
            else:
                notes.append(f"News lag confirmed: +{max_move_pct:.1f}% after detection")

    # ── OLD_NEWS_CONTINUATION ────────────────────────────────────────────
    if label == "unresolved" and old_catalyst:
        if max_move_pct is not None and max_move_pct >= thresholds.meaningful_move_pct:
            label = "old_news_continuation"
            notes.append(f"Old catalyst continuation: +{max_move_pct:.1f}%")
        else:
            label = "no_follow_through"
            notes.append("Old catalyst, no follow-through")

    # Default fallback
    if label == "unresolved":
        if max_move_pct is not None and max_move_pct >= thresholds.meaningful_move_pct:
            label = "clean_pre_news_winner"
            notes.append(f"Default winner: +{max_move_pct:.1f}%")
        else:
            label = "no_follow_through"
            notes.append("Default: insufficient forward data")

    snapshot.final_outcome_label = label
    snapshot.outcome_notes = notes
    snapshot.last_updated_at = datetime.now(timezone.utc)
    return label


# ═══════════════════════════════════════════════════════════════════════════════
#  GROUPED PERFORMANCE STATISTICS
# ═══════════════════════════════════════════════════════════════════════════════


def _safe_mean(values: list[float]) -> Optional[float]:
    if not values:
        return None
    return round(sum(values) / len(values), 2)


def _safe_median(values: list[float]) -> Optional[float]:
    if not values:
        return None
    return round(statistics.median(values), 2)


def _bucket_stats(snapshots: list[PreNewsDetectionSnapshot]) -> dict[str, Any]:
    """Compute standard stats for a list of snapshots."""
    total = len(snapshots)
    if total == 0:
        return {
            "total": 0, "clean_winner_rate": None, "trap_rate": None,
            "late_chase_rate": None, "no_follow_through_rate": None,
            "news_lag_rate": None, "avg_max_move_30m": None,
            "avg_max_move_1h": None, "avg_max_move_2h": None,
            "avg_max_move_same_day": None, "avg_drawdown": None,
            "vwap_hold_rate": None, "avg_efficiency": None,
            "avg_suspicion_score": None, "avg_absorption_quality": None,
            "avg_tod_rvol": None,
        }

    def _rate(label: str) -> Optional[float]:
        c = sum(1 for s in snapshots if s.final_outcome_label == label)
        return round(c / total * 100, 1)

    def _avg(field: str) -> Optional[float]:
        vals = [getattr(s, field) for s in snapshots if getattr(s, field) is not None]
        return _safe_mean(vals)

    vwap_holds = [s for s in snapshots if s.vwap_hold_after_detection is not None]
    vwap_hold_rate = None
    if vwap_holds:
        vwap_hold_rate = round(sum(1 for s in vwap_holds if s.vwap_hold_after_detection) / len(vwap_holds) * 100, 1)

    return {
        "total": total,
        "clean_winner_rate": _rate("clean_pre_news_winner"),
        "trap_rate": _rate("distribution_trap"),
        "late_chase_rate": _rate("late_chase_signal"),
        "no_follow_through_rate": _rate("no_follow_through"),
        "news_lag_rate": _rate("news_lag_confirmed_winner"),
        "avg_max_move_30m": _avg("max_move_30m_pct"),
        "avg_max_move_1h": _avg("max_move_1h_pct"),
        "avg_max_move_2h": _avg("max_move_2h_pct"),
        "avg_max_move_same_day": _avg("max_move_same_day_pct"),
        "avg_drawdown": _avg("drawdown_before_max_move_pct"),
        "vwap_hold_rate": vwap_hold_rate,
        "avg_efficiency": _avg("efficiency_ratio"),
        "avg_suspicion_score": _avg("pre_news_suspicion_score"),
        "avg_absorption_quality": _avg("absorption_quality_score"),
        "avg_tod_rvol": _avg("time_of_day_rvol"),
    }


def get_evaluation_summary(
    snapshots: list[PreNewsDetectionSnapshot],
) -> dict[str, Any]:
    """Compute overall and grouped performance statistics."""
    completed = [s for s in snapshots if s.final_outcome_label != "unresolved"]
    unresolved = [s for s in snapshots if s.final_outcome_label == "unresolved"]

    summary = {
        "total_detections": len(snapshots),
        "active_unresolved": len(unresolved),
        "completed_detections": len(completed),
    }
    summary.update(_bucket_stats(snapshots))

    # Grouped by anomaly type
    by_anomaly_type: dict[str, Any] = {}
    for atype in set(s.anomaly_type for s in snapshots if s.anomaly_type):
        by_anomaly_type[atype] = _bucket_stats([s for s in snapshots if s.anomaly_type == atype])
    summary["by_anomaly_type"] = by_anomaly_type

    # Grouped by alert quality
    by_alert_quality: dict[str, Any] = {}
    for aq in set(s.alert_quality for s in snapshots if s.alert_quality):
        by_alert_quality[aq] = _bucket_stats([s for s in snapshots if s.alert_quality == aq])
    summary["by_alert_quality"] = by_alert_quality

    # Grouped by candidate type
    by_candidate_type: dict[str, Any] = {}
    for ct in set(s.candidate_type for s in snapshots if s.candidate_type):
        by_candidate_type[ct] = _bucket_stats([s for s in snapshots if s.candidate_type == ct])
    summary["by_candidate_type"] = by_candidate_type

    # Grouped by Wyckoff stage
    by_wyckoff: dict[str, Any] = {}
    for ws in set(s.wyckoff_stage for s in snapshots if s.wyckoff_stage):
        by_wyckoff[ws] = _bucket_stats([s for s in snapshots if s.wyckoff_stage == ws])
    summary["by_wyckoff_stage"] = by_wyckoff

    # Grouped by catalyst status
    by_catalyst: dict[str, Any] = {}
    for cs in set(s.news_status for s in snapshots if s.news_status):
        by_catalyst[cs] = _bucket_stats([s for s in snapshots if s.news_status == cs])
    summary["by_catalyst_status"] = by_catalyst

    return summary


# ═══════════════════════════════════════════════════════════════════════════════
#  BEST / WORST RANKED LISTS
# ═══════════════════════════════════════════════════════════════════════════════


def _snapshot_sort_key(
    s: PreNewsDetectionSnapshot,
    primary: str,
    secondary: str = "detection_time",
    reverse: bool = True,
) -> tuple:
    """Helper for ranked lists."""
    p = getattr(s, primary)
    if p is None:
        p = -999999.0 if reverse else 999999.0
    sec = getattr(s, secondary)
    if isinstance(sec, datetime):
        sec = sec.isoformat()
    if sec is None:
        sec = ""
    return (p, sec)


def get_best_early_detections(
    snapshots: list[PreNewsDetectionSnapshot],
    top_n: int = 10,
) -> list[dict]:
    """Best EARLY alerts with high efficiency, strong move, VWAP held."""
    candidates = [
        s for s in snapshots
        if s.alert_quality == "early"
        and (s.efficiency_ratio or 0) > 0
        and (s.vwap_hold_after_detection is not False)
        and s.news_status in (
            "no_news_found",
            "no_public_news_found_in_sources",
            "unknown_news_status",
        )
    ]
    candidates.sort(
        key=lambda s: (
            s.efficiency_ratio or 0,
            s.max_move_1h_pct or 0,
            -(s.drawdown_before_max_move_pct or 0),
            s.absorption_quality_score,
        ),
        reverse=True,
    )
    return [_snapshot_summary_dict(s) for s in candidates[:top_n]]


def get_worst_false_positives(
    snapshots: list[PreNewsDetectionSnapshot],
    top_n: int = 10,
) -> list[dict]:
    """High suspicion, poor move, large drawdown, trap/failed outcomes."""
    candidates = [
        s for s in snapshots
        if s.pre_news_suspicion_score >= 70
        and s.final_outcome_label in (
            "failed_spike", "distribution_trap", "late_chase_signal", "no_follow_through",
        )
    ]
    candidates.sort(
        key=lambda s: (
            s.pre_news_suspicion_score,
            -(s.efficiency_ratio or 0),
            s.drawdown_before_max_move_pct or 0,
        ),
        reverse=True,
    )
    return [_snapshot_summary_dict(s) for s in candidates[:top_n]]


def get_best_quiet_accumulation_winners(
    snapshots: list[PreNewsDetectionSnapshot],
    top_n: int = 10,
) -> list[dict]:
    """Quiet accumulation candidates that won cleanly."""
    candidates = [
        s for s in snapshots
        if s.quiet_accumulation_candidate
        and s.final_outcome_label in ("clean_pre_news_winner", "news_lag_confirmed_winner")
    ]
    candidates.sort(
        key=lambda s: (
            s.absorption_quality_score,
            s.efficiency_ratio or 0,
            -(s.drawdown_before_max_move_pct or 0),
        ),
        reverse=True,
    )
    return [_snapshot_summary_dict(s) for s in candidates[:top_n]]


def get_worst_late_chase_signals(
    snapshots: list[PreNewsDetectionSnapshot],
    top_n: int = 10,
) -> list[dict]:
    """LATE alerts with high VWAP distance and poor upside."""
    candidates = [
        s for s in snapshots
        if s.alert_quality == "late"
        and s.vwap_distance > 10
    ]
    candidates.sort(
        key=lambda s: (
            s.vwap_distance,
            -(s.max_move_1h_pct or 0),
            s.drawdown_before_max_move_pct or 0,
        ),
        reverse=True,
    )
    return [_snapshot_summary_dict(s) for s in candidates[:top_n]]


def get_best_news_lag_confirmed(
    snapshots: list[PreNewsDetectionSnapshot],
    top_n: int = 10,
) -> list[dict]:
    """News appeared after detection and price moved before public headline."""
    candidates = [
        s for s in snapshots
        if s.time_gap_detection_to_news is not None
        and s.time_gap_detection_to_news > 0
        and (s.max_move_1h_pct or 0) >= 3.0
    ]
    candidates.sort(
        key=lambda s: (
            s.max_move_1h_pct or 0,
            s.time_gap_detection_to_news or 0,
            s.efficiency_ratio or 0,
        ),
        reverse=True,
    )
    return [_snapshot_summary_dict(s) for s in candidates[:top_n]]


def get_suppressed_that_worked(
    snapshots: list[PreNewsDetectionSnapshot],
    top_n: int = 10,
) -> list[dict]:
    """Suppressed alerts where price still moved strongly."""
    candidates = [
        s for s in snapshots
        if s.was_alert_suppressed
        and (s.max_move_1h_pct or 0) >= 3.0
    ]
    candidates.sort(
        key=lambda s: (
            s.max_move_1h_pct or 0,
            s.efficiency_ratio or 0,
            s.absorption_quality_score,
        ),
        reverse=True,
    )
    return [_snapshot_summary_dict(s) for s in candidates[:top_n]]


def get_allowed_that_failed(
    snapshots: list[PreNewsDetectionSnapshot],
    top_n: int = 10,
) -> list[dict]:
    """Allowed (non-suppressed) alerts that became traps/failed spikes/late chase."""
    candidates = [
        s for s in snapshots
        if not s.was_alert_suppressed
        and s.final_outcome_label in (
            "failed_spike", "distribution_trap", "late_chase_signal",
        )
    ]
    candidates.sort(
        key=lambda s: (
            s.pre_news_suspicion_score,
            -(s.efficiency_ratio or 0),
            s.drawdown_before_max_move_pct or 0,
        ),
        reverse=True,
    )
    return [_snapshot_summary_dict(s) for s in candidates[:top_n]]


def _snapshot_summary_dict(s: PreNewsDetectionSnapshot) -> dict:
    """Lightweight dict for ranked lists."""
    return {
        "ticker": s.ticker,
        "detection_time": s.detection_time.isoformat() if s.detection_time else None,
        "detection_price": s.detection_price,
        "suspicion_score": s.pre_news_suspicion_score,
        "anomaly_type": s.anomaly_type,
        "alert_quality": s.alert_quality,
        "wyckoff_stage": s.wyckoff_stage,
        "time_of_day_rvol": s.time_of_day_rvol,
        "vwap_distance": s.vwap_distance,
        "absorption_quality_score": s.absorption_quality_score,
        "latest_5candle_summary": s.latest_5candle_summary,
        "max_move_1h_pct": s.max_move_1h_pct,
        "drawdown_before_max_move_pct": s.drawdown_before_max_move_pct,
        "efficiency_ratio": s.efficiency_ratio,
        "final_outcome_label": s.final_outcome_label,
    }


# ═══════════════════════════════════════════════════════════════════════════════
#  CALIBRATION RECOMMENDATIONS
# ═══════════════════════════════════════════════════════════════════════════════


def generate_calibration_recommendations(
    summary: dict[str, Any],
    thresholds: OutcomeThresholds = DEFAULT_THRESHOLDS,
) -> list[dict]:
    """Inspect grouped stats and output practical calibration recommendations."""
    recommendations: list[dict] = []

    by_alert = summary.get("by_alert_quality", {})
    by_type = summary.get("by_anomaly_type", {})
    by_candidate = summary.get("by_candidate_type", {})
    by_catalyst = summary.get("by_catalyst_status", {})

    def _add(rec_type: str, bucket: str, observation: str, suggestion: str, confidence: str, stats: dict):
        recommendations.append({
            "recommendation_type": rec_type,
            "affected_bucket": bucket,
            "current_observation": observation,
            "suggested_change": suggestion,
            "confidence_level": confidence,
            "supporting_stats": stats,
        })

    # 1. LATE alerts with high trap rate
    late_stats = by_alert.get("late", {})
    if late_stats and late_stats.get("trap_rate", 0) is not None:
        trap_rate = late_stats.get("trap_rate", 0) or 0
        if trap_rate > 25:
            _add(
                "threshold_adjustment",
                "late_alerts",
                f"LATE alerts have {trap_rate:.1f}% trap rate",
                f"Lower VWAP late threshold from {thresholds.late_chase_vwap_distance:.0f}% to 12%",
                "medium",
                late_stats,
            )
            _add(
                "suppression_rule",
                "late_alerts",
                f"LATE alerts have {trap_rate:.1f}% trap rate",
                "Suppress alerts when upper_wick_pct > 35 and vwap_distance > 8%",
                "medium",
                late_stats,
            )

    # 2. QUIET_VOLUME_BUILD strong performance
    quiet_stats = by_type.get("quiet_volume_build", {})
    if quiet_stats and quiet_stats.get("clean_winner_rate", 0) is not None:
        cw_rate = quiet_stats.get("clean_winner_rate", 0) or 0
        if cw_rate > 40:
            _add(
                "score_boost",
                "quiet_volume_build",
                f"QUIET_VOLUME_BUILD has {cw_rate:.1f}% clean winner rate",
                "Increase score boost for quiet accumulation candidates by +5-10 points",
                "high",
                quiet_stats,
            )
            _add(
                "universe_expansion",
                "quiet_volume_build",
                f"QUIET_VOLUME_BUILD has {cw_rate:.1f}% clean winner rate",
                "Expand quiet abnormal volume discovery universe (lower ToD RVOL threshold)",
                "medium",
                quiet_stats,
            )

    # 3. Quiet candidates with low follow-through
    quiet_cand = by_candidate.get("quiet_accumulation", {})
    if quiet_cand and quiet_cand.get("no_follow_through_rate", 0) is not None:
        nft = quiet_cand.get("no_follow_through_rate", 0) or 0
        if nft > 40:
            _add(
                "threshold_increase",
                "quiet_accumulation",
                f"Quiet accumulation has {nft:.1f}% no-follow-through rate",
                "Increase time_of_day_rvol threshold from 1.5 to 2.0",
                "medium",
                quiet_cand,
            )
            _add(
                "filter_tightening",
                "quiet_accumulation",
                f"Quiet accumulation has {nft:.1f}% no-follow-through rate",
                "Require absorption_quality_score >= 65 and buying_pressure > selling_pressure",
                "medium",
                quiet_cand,
            )

    # 4. REJECTION / FAILED_SPIKE allowed
    rej_stats = by_type.get("rejection", {})
    if rej_stats and rej_stats.get("trap_rate", 0) is not None:
        if (rej_stats.get("trap_rate", 0) or 0) > 30:
            _add(
                "quality_override",
                "rejection",
                f"REJECTION signals have {rej_stats.get('trap_rate', 0):.1f}% trap rate",
                "Force alert_quality to TRAP_RISK for rejection/failed_spike patterns",
                "high",
                rej_stats,
            )

    # 5. Old catalysts producing poor signals
    old_stats = by_catalyst.get("old_catalyst_present", {})
    if old_stats and old_stats.get("clean_winner_rate", 0) is not None:
        if (old_stats.get("clean_winner_rate", 0) or 0) < 20:
            _add(
                "catalyst_penalty",
                "old_catalyst_present",
                f"Old catalyst signals have {old_stats.get('clean_winner_rate', 0):.1f}% clean winner rate",
                "Reduce catalyst relevance score for headlines older than 7 days",
                "medium",
                old_stats,
            )
            _add(
                "classification_separation",
                "old_catalyst_present",
                "Old catalyst continuation signals are mixed with true pre-news",
                "Separate old catalyst continuation from true pre-news in anomaly classification",
                "medium",
                old_stats,
            )

    # 6. Suppressed signals that worked
    suppressed = summary.get("suppressed_that_worked", [])
    if len(suppressed) > 3:
        _add(
            "suppression_review",
            "suppressed_alerts",
            f"{len(suppressed)} suppressed signals still produced strong moves",
            "Allow exceptions when absorption_quality_score >= 80 and VWAP holds",
            "medium",
            {"count": len(suppressed)},
        )

    # 7. Offering-risk names with poor performance
    severe_offering = [s for s in summary.get("all_snapshots", []) if s.offering_risk_score >= 60]
    if severe_offering:
        # This would need all_snapshots passed in; skip for now
        pass

    return recommendations


# ═══════════════════════════════════════════════════════════════════════════════
#  EVALUATOR ENGINE (persistence + batch operations)
# ═══════════════════════════════════════════════════════════════════════════════


class PreNewsEvaluator:
    """Manages detection snapshots, forward tracking, and evaluation reports."""

    def __init__(self):
        self._snapshots: dict[str, PreNewsDetectionSnapshot] = {}  # key = detection_id
        self._ticker_index: dict[str, list[str]] = {}  # ticker -> list of detection_ids
        self.thresholds = DEFAULT_THRESHOLDS
        _ensure_dir()
        self._load_state()

    # ── Persistence ───────────────────────────────────────────────────────

    def _load_state(self):
        raw = load_json_file(SNAPSHOTS_FILE, default=None)
        if raw is None:
            return
        for sid, d in raw.items():
            try:
                for key in ("detection_time", "first_vwap_loss_time", "matched_headline_time",
                            "recorded_at", "last_updated_at"):
                    if d.get(key):
                        try:
                            d[key] = datetime.fromisoformat(d[key])
                        except Exception:
                            pass
                snapshot = PreNewsDetectionSnapshot(**d)
                self._snapshots[sid] = snapshot
                self._ticker_index.setdefault(snapshot.ticker, []).append(sid)
            except Exception:
                pass
        logger.info("PreNewsEvaluator: loaded %d snapshots", len(self._snapshots))

    def _persist_state(self):
        data = {sid: s.model_dump(mode="json") for sid, s in self._snapshots.items()}
        save_json_file(SNAPSHOTS_FILE, data)

    # ── Public API ────────────────────────────────────────────────────────

    def record_detection(self, anomaly: PreNewsAnomaly) -> PreNewsDetectionSnapshot:
        """Create and store a new detection snapshot."""
        snapshot = create_detection_snapshot(anomaly)
        sid = snapshot.detection_id

        # Avoid duplicate for same anomaly id
        if sid in self._snapshots:
            return self._snapshots[sid]

        self._snapshots[sid] = snapshot
        self._ticker_index.setdefault(snapshot.ticker, []).append(sid)
        self._persist_state()
        logger.debug("PreNewsEvaluator: recorded snapshot %s for %s", sid, snapshot.ticker)
        return snapshot

    def update_forward_for_ticker(self, ticker: str, current_price: float, current_time: datetime, vwap: Optional[float] = None):
        """Update all active (unresolved) snapshots for this ticker."""
        updated = 0
        for sid in self._ticker_index.get(ticker.upper(), []):
            snap = self._snapshots.get(sid)
            if not snap or snap.final_outcome_label != "unresolved":
                continue
            if update_forward_prices(snap, current_price, current_time, vwap):
                calculate_max_move_percentages(snap)
                calculate_drawdown_before_max(snap)
                calculate_efficiency_ratio(snap, self.thresholds)
                updated += 1
        if updated:
            self._persist_state()

    def finalize_all_eod(self, force: bool = False):
        """Finalize outcome labels for all snapshots. Call at EOD."""
        finalized = 0
        for snap in self._snapshots.values():
            if snap.final_outcome_label == "unresolved" or force:
                calculate_max_move_percentages(snap)
                calculate_drawdown_before_max(snap)
                calculate_efficiency_ratio(snap, self.thresholds)
                finalize_outcome_label(snap, self.thresholds, force=force)
                finalized += 1
        if finalized:
            self._persist_state()
            logger.info("PreNewsEvaluator: finalized %d snapshots", finalized)

    def update_news_confirmation(self, anomaly: PreNewsAnomaly):
        """Update time_gap_detection_to_news when news is confirmed."""
        sid = anomaly.id
        snap = self._snapshots.get(sid)
        if not snap:
            return
        if anomaly.news_confirmed_at and snap.detection_time:
            gap = (anomaly.news_confirmed_at - snap.detection_time).total_seconds() / 60.0
            snap.time_gap_detection_to_news = round(gap, 1)
            snap.last_updated_at = datetime.now(timezone.utc)
            self._persist_state()

    def get_summary(self) -> dict[str, Any]:
        """Full evaluation summary."""
        snapshots = list(self._snapshots.values())
        summary = get_evaluation_summary(snapshots)
        summary["best_early_detections"] = get_best_early_detections(snapshots)
        summary["worst_false_positives"] = get_worst_false_positives(snapshots)
        summary["best_quiet_accumulation_winners"] = get_best_quiet_accumulation_winners(snapshots)
        summary["worst_late_chase_signals"] = get_worst_late_chase_signals(snapshots)
        summary["best_news_lag_confirmed"] = get_best_news_lag_confirmed(snapshots)
        summary["suppressed_that_worked"] = get_suppressed_that_worked(snapshots)
        summary["allowed_that_failed"] = get_allowed_that_failed(snapshots)
        summary["calibration_recommendations"] = generate_calibration_recommendations(summary)
        return summary

    def get_filtered_snapshots(
        self,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        ticker: Optional[str] = None,
        anomaly_type: Optional[str] = None,
        alert_quality: Optional[str] = None,
        min_score: Optional[float] = None,
        outcome_label: Optional[str] = None,
        include_unresolved: bool = True,
    ) -> list[PreNewsDetectionSnapshot]:
        """Filter snapshots by criteria."""
        results = list(self._snapshots.values())

        if ticker:
            results = [s for s in results if s.ticker.upper() == ticker.upper()]
        if date_from:
            results = [s for s in results if s.session_date >= date_from]
        if date_to:
            results = [s for s in results if s.session_date <= date_to]
        if anomaly_type:
            results = [s for s in results if s.anomaly_type == anomaly_type]
        if alert_quality:
            results = [s for s in results if s.alert_quality == alert_quality]
        if min_score is not None:
            results = [s for s in results if s.pre_news_suspicion_score >= min_score]
        if outcome_label:
            results = [s for s in results if s.final_outcome_label == outcome_label]
        if not include_unresolved:
            results = [s for s in results if s.final_outcome_label != "unresolved"]

        return sorted(results, key=lambda s: s.detection_time, reverse=True)

    def get_snapshot_by_id(self, detection_id: str) -> Optional[PreNewsDetectionSnapshot]:
        return self._snapshots.get(detection_id)

    def export_daily_report(self, session_date: Optional[str] = None) -> dict[str, Path]:
        """Export JSON and CSV daily evaluation reports for the given session_date."""
        if session_date is None:
            session_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        snapshots = self.get_filtered_snapshots(date_from=session_date, date_to=session_date)
        paths = export_daily_evaluation_report(snapshots, session_date)
        clean_old_reports(retention_days=30)
        return paths

    def cleanup_old_reports(self, retention_days: int = 30) -> int:
        """Manually trigger cleanup of reports older than retention_days."""
        return clean_old_reports(retention_days=retention_days)

    def list_available_report_dates(self) -> list[str]:
        """Return sorted list of session dates that have exported reports."""
        if not REPORTS_DIR.exists():
            return []
        dates = set()
        for p in REPORTS_DIR.iterdir():
            if p.suffix in (".json", ".csv"):
                stem = p.stem
                # YYYY-MM-DD_pre_news_eval
                parts = stem.split("_")
                if len(parts) >= 4 and parts[0].count("-") == 2:
                    dates.add(parts[0])
        return sorted(dates, reverse=True)


# ═══════════════════════════════════════════════════════════════════════════════
#  Helpers
# ═══════════════════════════════════════════════════════════════════════════════


EVALUATION_CSV_COLUMNS = [
    "ticker",
    "detection_id",
    "detection_time",
    "session_date",
    "detection_price",
    "pre_news_suspicion_score",
    "anomaly_type",
    "price_behaviour",
    "wyckoff_stage",
    "alert_quality",
    "candidate_type",
    "quiet_accumulation_candidate",
    "early_breakout_candidate",
    "time_of_day_rvol",
    "intraday_volume_curve_deviation",
    "current_5m_volume_zscore",
    "session_progress_adjusted_volume_score",
    "volume_acceleration_score",
    "abnormal_volume_score",
    "float_rotation",
    "vwap_distance",
    "absorption_quality_score",
    "latest_5candle_summary",
    "buying_pressure",
    "selling_pressure",
    "wick_dominance",
    "upper_wick_pct",
    "lower_wick_pct",
    "vwap_hold_count",
    "vwap_loss_count",
    "news_status",
    "catalyst_age_bucket",
    "catalyst_relevance_score",
    "catalyst_source",
    "matched_headline",
    "matched_headline_time",
    "offering_risk_score",
    "dilution_risk_tag",
    "suppression_reasons",
    "was_alert_suppressed",
    "alert_sent",
    "max_price_30m",
    "max_price_1h",
    "max_price_2h",
    "max_price_same_day",
    "max_move_30m_pct",
    "max_move_1h_pct",
    "max_move_2h_pct",
    "max_move_same_day_pct",
    "drawdown_before_max_move_pct",
    "efficiency_ratio",
    "first_vwap_loss_time",
    "vwap_hold_after_detection",
    "time_gap_detection_to_news",
    "pre_news_high",
    "post_news_high",
    "final_outcome_label",
    "outcome_notes",
]


def _ensure_dir():
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def _ensure_reports_dir():
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)


def _fmt_value(val: Any) -> str:
    """Format a snapshot field for CSV output."""
    if val is None:
        return ""
    if isinstance(val, bool):
        return "Y" if val else "N"
    if isinstance(val, (list, tuple)):
        return "; ".join(str(v) for v in val)
    if isinstance(val, datetime):
        return val.isoformat()
    return str(val)


def _snapshot_to_csv_row(snap: PreNewsDetectionSnapshot) -> dict[str, str]:
    """Convert a snapshot to a flat dict of CSV-safe strings."""
    return {col: _fmt_value(getattr(snap, col, None)) for col in EVALUATION_CSV_COLUMNS}


def export_daily_evaluation_report(
    snapshots: list[PreNewsDetectionSnapshot],
    session_date: str,
) -> dict[str, Path]:
    """
    Export all snapshots for a given session_date to JSON and CSV.

    Returns {"json": path, "csv": path}.
    """
    _ensure_reports_dir()
    base_name = f"{session_date}_pre_news_eval"
    json_path = REPORTS_DIR / f"{base_name}.json"
    csv_path = REPORTS_DIR / f"{base_name}.csv"

    # ── JSON export ─────────────────────────────────────────────────────────
    json_data = {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "session_date": session_date,
        "total_snapshots": len(snapshots),
        "snapshots": [s.model_dump(mode="json") for s in snapshots],
    }
    save_json_file(json_path, json_data)

    # ── CSV export ──────────────────────────────────────────────────────────
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=EVALUATION_CSV_COLUMNS)
        writer.writeheader()
        for snap in snapshots:
            writer.writerow(_snapshot_to_csv_row(snap))

    logger.info(
        "PreNews evaluation report exported: %d rows → %s, %s",
        len(snapshots),
        json_path.name,
        csv_path.name,
    )
    return {"json": json_path, "csv": csv_path}


def clean_old_reports(retention_days: int = 30) -> int:
    """
    Delete evaluation report files older than retention_days.

    Returns the number of files removed.
    """
    if not REPORTS_DIR.exists():
        return 0
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    removed = 0
    for p in REPORTS_DIR.iterdir():
        if p.suffix not in (".json", ".csv"):
            continue
        try:
            mtime = datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)
            if mtime < cutoff:
                p.unlink()
                removed += 1
                logger.info("Removed old evaluation report: %s", p.name)
        except OSError:
            continue
    if removed:
        logger.info("Cleaned %d evaluation reports older than %d days", removed, retention_days)
    return removed
