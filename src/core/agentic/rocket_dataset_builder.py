"""
rocket_dataset_builder.py
=========================
Rocket Dataset Builder — skeleton (Task 1A).

Builds a leakage-safe, labelled CSV/Parquet dataset from Oracle alert sources
for training the Rocket model.

Architecture
------------
* Constants & manifests  — column lists, set constants, trading-session params
* Pydantic models        — PeakMetrics, MFEMAEProfiles, RocketRecord, BuildSummary
* Bar access helpers     — _bget, _bar_ts, _bar_high, _bar_low, _bar_close,
                           _aware, _trading_minutes_between
* Private utility helpers — _parse_dt, _to_float, _to_int, _anchor_check,
                            _minute_bucket, _count_values, _null_rates

NOT in this module (implemented in later subtasks):
* Label functions (compute_peak_metrics, compute_runner_tier, …)
* RocketDatasetBuilder class
"""
from __future__ import annotations

import logging
import math
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

try:
    from zoneinfo import ZoneInfo
except ImportError:  # Python < 3.9
    from backports.zoneinfo import ZoneInfo  # type: ignore

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Version constants
# ---------------------------------------------------------------------------

DATASET_VERSION: str = "rocket_v1"
BUILDER_VERSION: str = "1.0.0"

# ---------------------------------------------------------------------------
# String-set constants
# ---------------------------------------------------------------------------

RUNNER_TIERS: set[str] = {
    "no_move",
    "minor_move",
    "moderate_move",
    "strong_move",
    "runner",
    "mega_runner",
}

DRAWDOWN_QUAL: set[str] = {
    "clean_breakout",
    "shallow_pullback",
    "moderate_pullback",
    "deep_pullback",
    "reversal",
    "insufficient_data",
}

DRAWDOWN_DQ: set[str] = {
    "ok",
    "partial_bars",
    "no_intraday_bars",
    "no_daily_bars",
    "price_zero",
    "insufficient_window",
}

OUTCOME_SOURCE: set[str] = {
    "intraday_bars",
    "daily_bars",
    "stored_fields",
    "none",
}

SOURCE_TYPES: set[str] = {
    "news_momentum",
    "prenews",
    "manual",
    "backfill",
}

DEDUP_PRIORITY = ["telegram", "missed", "prenews", "shadow", "backfill"]

# ---------------------------------------------------------------------------
# Trading-session constants
# ---------------------------------------------------------------------------

_ET = ZoneInfo("America/New_York")
_MARKET_OPEN: time = time(9, 30)
_MARKET_CLOSE: time = time(16, 0)
_FETCH_DELAY: float = 0.25  # seconds between external API calls

# ---------------------------------------------------------------------------
# Default path constants
# ---------------------------------------------------------------------------

_DEFAULT_DATA_DIR: Path = Path(__file__).resolve().parents[3] / "data" / "rocket"
_DEFAULT_DOCS_DIR: Path = Path(__file__).resolve().parents[3] / "docs" / "rocket"

# ---------------------------------------------------------------------------
# Leakage manifests
# ---------------------------------------------------------------------------

FEATURE_COLUMNS: List[str] = [
    "row_id", "source_type", "ticker", "alert_time", "price_at_alert",
    "catalyst_type", "catalyst_subtype", "catalyst_category", "session_type",
    "float_category", "market_cap_category", "move_pct_at_alert", "rvol_at_alert",
    "volume_at_alert", "spread_pct_at_alert", "trap_risk_at_alert",
    "dilution_risk_at_alert", "velocity_score_at_alert", "sources_seen_count",
    "is_negative", "is_vague", "is_delayed_reaction", "prenews_anomaly_score",
    "ml_predicted_win_prob", "news_impact_score", "expected_return_score",
    "continuation_probability", "multi_day_score",
    "sec_dilution_probability", "sec_toxic_financing_score",
    "sec_warrant_overhang_score", "sec_cash_runway_score",
    "sec_survival_risk_score", "sec_balance_sheet_quality_score",
    "sec_offering_risk_score", "sec_reverse_split_risk_score",
    "sec_structural_trap_risk_score", "sec_historical_dilution_behavior_score",
    "sec_dilution_behavior", "sec_oracle_action",
    "sec_atm_active", "sec_going_concern_active",
    "dataset_version", "builder_version",
]

LABEL_COLUMNS: List[str] = [
    "outcome_window_start", "peak_move_pct", "peak_timestamp",
    "calendar_time_to_peak_minutes", "trading_time_to_peak_minutes",
    "mfe_15m", "mfe_60m", "mfe_1d", "mfe_2d", "mfe_5d",
    "mae_15m", "mae_60m", "mae_1d", "mae_2d", "mae_5d",
    "runner_tier", "drawdown_quality", "drawdown_data_quality",
    "outcome_source", "data_quality_score",
]

_EXPORT_COLUMNS: List[str] = FEATURE_COLUMNS + LABEL_COLUMNS

# ---------------------------------------------------------------------------
# Pydantic data models
# ---------------------------------------------------------------------------


class PeakMetrics(BaseModel):
    """Intraday peak statistics relative to price_at_alert."""

    peak_move_pct: Optional[float] = None
    peak_timestamp: Optional[datetime] = None
    calendar_time_to_peak_minutes: Optional[float] = None
    trading_time_to_peak_minutes: Optional[float] = None
    outcome_window_start: Optional[datetime] = None
    outcome_source: Optional[str] = None


class MFEMAEProfiles(BaseModel):
    """Maximum favourable / adverse excursion profiles across time windows."""

    mfe_15m: Optional[float] = None
    mfe_60m: Optional[float] = None
    mfe_1d: Optional[float] = None
    mfe_2d: Optional[float] = None
    mfe_5d: Optional[float] = None
    mae_15m: Optional[float] = None
    mae_60m: Optional[float] = None
    mae_1d: Optional[float] = None
    mae_2d: Optional[float] = None
    mae_5d: Optional[float] = None


class RocketRecord(BaseModel):
    """
    One alert row destined for the Rocket dataset.

    Three zones (CRITICAL for anti-leakage):
    1. Identity fields
    2. At-alert features  — computed from information available at alert time
    3. Forward labels     — computed post-hoc from price data

    Internal-only fields (excluded from the column manifest) are marked with
    ``Field(exclude=True)`` so they never appear in the exported CSV/Parquet.
    """

    model_config = {"arbitrary_types_allowed": True}

    # ── Identity ────────────────────────────────────────────────────────────
    row_id: str
    source_type: str
    rejection_reason: Optional[str] = None
    dataset_version: str = DATASET_VERSION
    builder_version: str = BUILDER_VERSION

    # ── AT-ALERT FEATURES ───────────────────────────────────────────────────
    ticker: str
    alert_time: datetime
    price_at_alert: float
    catalyst_type: Optional[str] = None
    catalyst_subtype: Optional[str] = None
    catalyst_category: Optional[str] = None
    session_type: Optional[str] = None
    float_category: Optional[str] = None
    market_cap_category: Optional[str] = None
    move_pct_at_alert: Optional[float] = None
    rvol_at_alert: Optional[float] = None
    volume_at_alert: Optional[int] = None
    spread_pct_at_alert: Optional[float] = None
    trap_risk_at_alert: Optional[float] = None
    dilution_risk_at_alert: Optional[float] = None
    velocity_score_at_alert: Optional[float] = None
    sources_seen_count: Optional[int] = None
    is_negative: Optional[bool] = None
    is_vague: Optional[bool] = None
    is_delayed_reaction: Optional[bool] = None
    prenews_anomaly_score: Optional[float] = None
    ml_predicted_win_prob: Optional[float] = None
    news_impact_score: Optional[float] = None
    expected_return_score: Optional[float] = None
    continuation_probability: Optional[float] = None
    multi_day_score: Optional[float] = None
    sec_dilution_probability: Optional[float] = None
    sec_toxic_financing_score: Optional[float] = None
    sec_warrant_overhang_score: Optional[float] = None
    sec_cash_runway_score: Optional[float] = None
    sec_survival_risk_score: Optional[float] = None
    sec_balance_sheet_quality_score: Optional[float] = None
    sec_offering_risk_score: Optional[float] = None
    sec_reverse_split_risk_score: Optional[float] = None
    sec_structural_trap_risk_score: Optional[float] = None
    sec_historical_dilution_behavior_score: Optional[float] = None
    sec_dilution_behavior: Optional[str] = None
    sec_oracle_action: Optional[str] = None
    sec_atm_active: Optional[bool] = None
    sec_going_concern_active: Optional[bool] = None

    # ── FORWARD PRICING (internal only — excluded from manifest) ────────────
    intraday_bars: Optional[List[Any]] = Field(default=None, exclude=True)
    daily_bars: Optional[List[Any]] = Field(default=None, exclude=True)
    stored_mfe_pct: Optional[float] = Field(default=None, exclude=True)
    stored_mae_pct: Optional[float] = Field(default=None, exclude=True)
    stored_return_next_day_high_pct: Optional[float] = Field(default=None, exclude=True)
    stored_return_two_day_high_pct: Optional[float] = Field(default=None, exclude=True)
    stored_return_five_day_high_pct: Optional[float] = Field(default=None, exclude=True)

    # Dedup tracking (internal only — excluded from manifest)
    duplicate_of: Optional[str] = Field(default=None, exclude=True)
    dropped_source_type: Optional[str] = Field(default=None, exclude=True)
    kept_source_type: Optional[str] = Field(default=None, exclude=True)
    dedup_reason: Optional[str] = Field(default=None, exclude=True)

    # ── LABELS ──────────────────────────────────────────────────────────────
    outcome_window_start: Optional[datetime] = None
    peak_move_pct: Optional[float] = None
    peak_timestamp: Optional[datetime] = None
    calendar_time_to_peak_minutes: Optional[float] = None
    trading_time_to_peak_minutes: Optional[float] = None
    mfe_15m: Optional[float] = None
    mfe_60m: Optional[float] = None
    mfe_1d: Optional[float] = None
    mfe_2d: Optional[float] = None
    mfe_5d: Optional[float] = None
    mae_15m: Optional[float] = None
    mae_60m: Optional[float] = None
    mae_1d: Optional[float] = None
    mae_2d: Optional[float] = None
    mae_5d: Optional[float] = None
    runner_tier: Optional[str] = None
    drawdown_quality: Optional[str] = None
    drawdown_data_quality: Optional[str] = None
    outcome_source: Optional[str] = None
    data_quality_score: Optional[float] = None


class BuildSummary(BaseModel):
    """Top-level statistics produced after a full dataset build run."""

    total_ingested: int
    total_rejected: int
    total_exported: int
    runner_tier_counts: Dict[str, int]
    drawdown_quality_counts: Dict[str, int]
    null_rate_by_feature: Dict[str, float]
    rejection_reasons: Dict[str, int]
    output_paths: Dict[str, str]
    pricing_fetch_stats: Dict[str, int]
    dataset_version: str
    builder_version: str
    created_at: datetime


# ---------------------------------------------------------------------------
# Bar access helpers
# ---------------------------------------------------------------------------


def _bget(bar: Any, key: str, default: Any = None) -> Any:
    """Retrieve a value from a bar that may be a dict or an object."""
    if bar is None:
        return default
    if isinstance(bar, dict):
        return bar.get(key, default)
    return getattr(bar, key, default)


def _bar_ts(bar: Any) -> Optional[datetime]:
    """Return the bar's timestamp field, or None."""
    return _bget(bar, "timestamp")


def _bar_high(bar: Any) -> Optional[float]:
    """Return the bar's high field as float, or None."""
    val = _bget(bar, "high")
    return _to_float(val)


def _bar_low(bar: Any) -> Optional[float]:
    """Return the bar's low field as float, or None."""
    val = _bget(bar, "low")
    return _to_float(val)


def _bar_close(bar: Any) -> Optional[float]:
    """Return the bar's close field as float, or None."""
    val = _bget(bar, "close")
    return _to_float(val)


def _aware(dt: datetime) -> datetime:
    """Ensure *dt* is timezone-aware; assume UTC if naive."""
    if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _trading_minutes_between(start: datetime, end: datetime) -> float:
    """
    Count US Eastern regular-session minutes between *start* and *end*.

    Counts minutes in [09:30, 16:00) on weekdays only.
    Uses segment arithmetic — does NOT iterate per minute.
    """
    if end <= start:
        return 0.0
    start_et = _aware(start).astimezone(_ET)
    end_et   = _aware(end).astimezone(_ET)
    total = 0.0
    current_date = start_et.date()
    end_date = end_et.date()
    while current_date <= end_date:
        if current_date.weekday() < 5:  # Mon–Fri
            day_open  = datetime.combine(current_date, _MARKET_OPEN,  tzinfo=_ET)
            day_close = datetime.combine(current_date, _MARKET_CLOSE, tzinfo=_ET)
            seg_start = max(start_et, day_open)
            seg_end   = min(end_et,   day_close)
            if seg_start < seg_end:
                total += (seg_end - seg_start).total_seconds() / 60.0
        current_date += timedelta(days=1)
    return round(total, 2)


# ---------------------------------------------------------------------------
# Private utility helpers
# ---------------------------------------------------------------------------


def _parse_dt(value: Any) -> Optional[datetime]:
    """
    Parse *value* into a datetime.

    Accepts:
    * datetime objects (returned as-is)
    * ISO-8601 strings
    * Unix timestamps (int/float)

    Returns None on failure.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value, tz=timezone.utc)
        except (OSError, OverflowError, ValueError):
            return None
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return None
        for fmt in (
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%dT%H:%M:%S.%f%z",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%dT%H:%M:%S.%f",
            "%Y-%m-%d %H:%M:%S%z",
            "%Y-%m-%d %H:%M:%S",
        ):
            try:
                return datetime.strptime(value, fmt)
            except ValueError:
                continue
        # Last-ditch: fromisoformat (Python 3.7+)
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


def _to_float(value: Any) -> Optional[float]:
    """Coerce *value* to float, returning None for non-finite or unparseable values."""
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(f):
        return None
    return f


def _to_int(value: Any) -> Optional[int]:
    """Coerce *value* to int, returning None on failure."""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _anchor_check(
    ticker: Any,
    alert_time: Any,
    price: Any,
    catalyst_type: Any,
    catalyst_subtype: Any,
    source_type: Any,
) -> Optional[str]:
    """
    Validate the minimum required fields for a RocketRecord.

    Returns a rejection-reason string if validation fails, else None.
    """
    if not ticker:
        return "missing_ticker"
    if alert_time is None:
        return "missing_alert_time"
    if price is None or price <= 0:
        return "invalid_price"
    if source_type != "prenews":
        has_cat = bool(catalyst_type and catalyst_type.strip())
        has_sub = bool(catalyst_subtype and catalyst_subtype.strip())
        if not has_cat and not has_sub:
            return "missing_catalyst"
    return None


def _minute_bucket(dt: datetime, bucket_size: int = 1) -> datetime:
    """
    Floor *dt* to the nearest *bucket_size*-minute interval.

    Example: _minute_bucket(09:37:45, 5) → 09:35:00
    """
    dt = _aware(dt)
    total_minutes = dt.hour * 60 + dt.minute
    floored = (total_minutes // bucket_size) * bucket_size
    return dt.replace(hour=floored // 60, minute=floored % 60, second=0, microsecond=0)


def _count_values(items: Sequence[Optional[str]]) -> Dict[str, int]:
    """Return a frequency dict for a sequence of nullable string values."""
    counts: Dict[str, int] = {}
    for item in items:
        if item is None:
            continue
        counts[item] = counts.get(item, 0) + 1
    return counts


def _null_rates(records: Sequence[RocketRecord], columns: Sequence[str]) -> Dict[str, float]:
    """
    Compute per-column null rates across *records*.

    Returns a dict mapping column name → fraction of records where the value
    is None (0.0 to 1.0).  Returns 1.0 for all columns when *records* is empty.
    """
    n = len(records)
    if n == 0:
        return {col: 1.0 for col in columns}
    result: Dict[str, float] = {}
    for col in columns:
        null_count = sum(1 for r in records if getattr(r, col, None) is None)
        result[col] = round(null_count / n, 6)
    return result
