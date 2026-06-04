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
import time as _time_module
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import pandas as pd

try:
    from zoneinfo import ZoneInfo
except ImportError:  # Python < 3.9
    from backports.zoneinfo import ZoneInfo  # type: ignore

from pydantic import BaseModel, Field

from src.core.agentic.rocket_ticker_integrity import (
    SYNTHETIC_REJECTION_REASON,
    is_synthetic_test_ticker,
)
from src.utils.atomic_json import load_json_file

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Version constants
# ---------------------------------------------------------------------------

DATASET_VERSION: str = "rocket_v1"
BUILDER_VERSION: str = "1.0.0"

# ---------------------------------------------------------------------------
# String-set constants
# ---------------------------------------------------------------------------

RUNNER_TIERS: set[str] = {"STANDARD_WIN", "MAJOR_RUNNER", "MONSTER_RUNNER", "LEGENDARY_RUNNER"}

DRAWDOWN_QUAL: set[str] = {"CLEAN_RUNNER", "DIRTY_RUNNER", "TRAP"}

DRAWDOWN_DQ: set[str] = {
    "ok",
    "partial_bars",
    "no_intraday_bars",
    "no_daily_bars",
    "price_zero",
    "insufficient_window",
}

OUTCOME_SOURCE: set[str] = {
    "bars",
    "daily_proxy",
    "stored_resolved",
    "missing",
}

SOURCE_TYPES: set[str] = {
    "telegram",
    "shadow",
    "backfill",
    "missed",
    "prenews",
}

DEDUP_PRIORITY = ["telegram", "missed", "prenews", "shadow", "backfill"]

_REJECTION_DUPLICATE   = "duplicate"
_DEDUP_REASON_PRIORITY = "priority_order"
_UNKNOWN_TICKER        = "UNKNOWN"

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

_DEFAULT_DATA_DIR: Path = Path("data/agentic")
_DEFAULT_DOCS_DIR: Path = Path("docs")

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
    rejection_reason: Optional[str] = Field(default=None, exclude=True)
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
    stored_return_15m_pct: Optional[float] = Field(default=None, exclude=True)
    stored_return_1h_pct:  Optional[float] = Field(default=None, exclude=True)
    stored_return_4h_pct:  Optional[float] = Field(default=None, exclude=True)

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


# Fields excluded from export by Field(exclude=True) — derived from model metadata
_INTERNAL_FIELDS: frozenset = frozenset(
    name for name, f in RocketRecord.model_fields.items() if f.exclude
)


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
    * datetime objects (returned as-is, made timezone-aware)
    * bare date objects (converted to midnight UTC)
    * ISO-8601 strings
    * Unix timestamps (int/float)

    Returns None on failure.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return _aware(value)
    if isinstance(value, date) and not isinstance(value, datetime):
        return datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
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
    if is_synthetic_test_ticker(ticker):
        return SYNTHETIC_REJECTION_REASON
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


def _minute_bucket(ticker: str, dt: datetime) -> Tuple[str, str]:
    """Return a dedup key (ticker, minute-floored ISO timestamp)."""
    rounded = _aware(dt).replace(second=0, microsecond=0)
    return (ticker, rounded.isoformat())


def _count_values(
    items: Any,
    col: Optional[str] = None,
) -> Dict[str, int]:
    """Return a frequency dict for a sequence of nullable string values.

    Two call forms:
    * ``_count_values(seq_of_strings)``  — legacy flat-sequence form
    * ``_count_values(records, "column_name")``  — extract attribute from each record
    """
    counts: Dict[str, int] = {}
    if col is not None:
        # New form: extract attribute from each record
        for item in items:
            val = getattr(item, col, None)
            if val is None:
                continue
            counts[str(val)] = counts.get(str(val), 0) + 1
    else:
        # Legacy form: flat sequence of nullable strings
        for item in items:
            if item is None:
                continue
            counts[item] = counts.get(item, 0) + 1
    return counts


def _null_rates(
    records: Any,
    columns: Sequence[str],
) -> Dict[str, float]:
    """
    Compute per-column null rates across *records*.

    Accepts either a list of ``RocketRecord`` objects or a ``pd.DataFrame``.
    Returns a dict mapping column name → fraction of records where the value
    is None / NaN (0.0 to 1.0).  Returns 1.0 for all columns when empty.
    """
    if isinstance(records, pd.DataFrame):
        n = len(records)
        if n == 0:
            return {col: 1.0 for col in columns}
        result: Dict[str, float] = {}
        for col in columns:
            if col in records.columns:
                null_count = int(records[col].isna().sum())
            else:
                null_count = n
            result[col] = round(null_count / n, 6)
        return result
    # Sequence[RocketRecord] path
    n = len(records)
    if n == 0:
        return {col: 1.0 for col in columns}
    result = {}
    for col in columns:
        null_count = sum(1 for r in records if getattr(r, col, None) is None)
        result[col] = round(null_count / n, 6)
    return result


# ---------------------------------------------------------------------------
# Label functions
# ---------------------------------------------------------------------------


def compute_peak_metrics(
    intraday_bars: Optional[List[Any]],
    daily_bars: Optional[List[Any]],
    alert_price: float,
    alert_time: datetime,
    stored_five_day_high_pct: Optional[float] = None,
) -> PeakMetrics:
    """Find peak move within ~5 trading days of alert_time.

    Scans bars (intraday preferred, daily fallback) for the highest high
    within the observation window. Falls back to stored_five_day_high_pct
    when no bars are available.
    """
    if alert_price <= 0:
        return PeakMetrics()

    alert_time = _aware(alert_time)
    window_end = alert_time + timedelta(days=8)  # 5 trading days + weekend buffer

    bars = intraday_bars or daily_bars or []
    peak_high: Optional[float] = None
    peak_ts: Optional[datetime] = None

    for bar in bars:
        ts = _bar_ts(bar)
        if ts is None or _aware(ts) < alert_time or _aware(ts) > window_end:
            continue
        high = _bar_high(bar)
        if high is None:
            continue
        if peak_high is None or high > peak_high:
            peak_high = high
            peak_ts = ts

    if peak_high is None:
        if stored_five_day_high_pct is not None:
            return PeakMetrics(peak_move_pct=round(stored_five_day_high_pct, 4))
        return PeakMetrics()

    peak_move_pct = round((peak_high / alert_price - 1.0) * 100.0, 4)
    calendar_mins = (peak_ts - alert_time).total_seconds() / 60.0
    trading_mins  = _trading_minutes_between(alert_time, peak_ts)

    return PeakMetrics(
        peak_move_pct=peak_move_pct,
        peak_timestamp=peak_ts,
        calendar_time_to_peak_minutes=round(calendar_mins, 2),
        trading_time_to_peak_minutes=trading_mins,
    )


def compute_runner_tier(
    peak_move_pct: Optional[float],
    time_to_peak_minutes: Optional[float],
) -> Optional[str]:
    """Assign runner tier based on peak_move_pct and timing.

    Evaluated sequentially from highest milestone down so a 400% mover
    is classified as LEGENDARY_RUNNER, never compressed into MONSTER_RUNNER.

    When time_to_peak_minutes is None:
    - LEGENDARY and MONSTER can still be assigned (5-day tiers, bounded
      by construction from the observation window)
    - MAJOR_RUNNER and STANDARD_WIN require timing data (shorter windows
      cannot be verified without it)
    """
    if peak_move_pct is None or peak_move_pct < 0:
        return None

    if time_to_peak_minutes is not None:
        trading_days = time_to_peak_minutes / (60.0 * 6.5)
        within_5 = trading_days <= 5.0
        within_2 = trading_days <= 2.0
        within_1 = trading_days <= 1.0
    else:
        within_5 = True   # bounded by 5-day observation window by construction
        within_2 = False  # cannot verify 2-day window without timing
        within_1 = False  # cannot verify 1-day window without timing

    if peak_move_pct >= 300 and within_5:
        return "LEGENDARY_RUNNER"
    if peak_move_pct >= 100 and within_5:
        return "MONSTER_RUNNER"
    if peak_move_pct >= 30  and within_2:
        return "MAJOR_RUNNER"
    if peak_move_pct >= 10  and within_1:
        return "STANDARD_WIN"
    return None


def compute_mfe_mae_profiles(
    intraday_bars: Optional[List[Any]],
    daily_bars: Optional[List[Any]],
    alert_price: float,
    alert_time: datetime,
    stored_fields: Optional[Dict[str, Optional[float]]] = None,
) -> MFEMAEProfiles:
    """Compute MFE and MAE for five observation windows.

    Priority:
    1. intraday_bars — all 5 windows available
    2. daily_bars — only 1d/2d/5d available; 15m/60m stay null
    3. stored_fields — mfe_1d/2d/5d from pre-resolved data; all MAE null
    """
    if alert_price <= 0:
        return MFEMAEProfiles()

    alert_time = _aware(alert_time)
    stored_fields = stored_fields or {}

    _WINDOWS: List[Tuple[str, timedelta]] = [
        ("15m", timedelta(minutes=15)),
        ("60m", timedelta(minutes=60)),
        ("1d",  timedelta(hours=24)),
        ("2d",  timedelta(hours=48)),
        ("5d",  timedelta(days=8)),   # matches compute_peak_metrics observation window
    ]

    result = MFEMAEProfiles()

    if intraday_bars:
        for key, delta in _WINDOWS:
            end = alert_time + delta
            highs: List[float] = []
            lows: List[float] = []
            for bar in intraday_bars:
                ts = _bar_ts(bar)
                if ts is None or _aware(ts) < alert_time or _aware(ts) > end:
                    continue
                h = _bar_high(bar)
                l = _bar_low(bar)
                if h is not None:
                    highs.append(h)
                if l is not None:
                    lows.append(l)
            if highs:
                setattr(result, f"mfe_{key}", round((max(highs) / alert_price - 1) * 100, 4))
            if lows:
                setattr(result, f"mae_{key}", round((min(lows) / alert_price - 1) * 100, 4))
        return result

    if daily_bars:
        # Sub-day windows are not available from daily bars — they stay null
        for key, n_days in [("1d", 1), ("2d", 2), ("5d", 5)]:
            alert_date = alert_time.date()
            days_seen = 0
            day_highs: List[float] = []
            day_lows: List[float] = []
            for bar in daily_bars:
                ts = _bar_ts(bar)
                if ts is None or ts.date() <= alert_date:
                    continue
                h = _bar_high(bar)
                l = _bar_low(bar)
                if h is not None:
                    day_highs.append(h)
                if l is not None:
                    day_lows.append(l)
                if h is not None or l is not None:  # only count as a trading day if data present
                    days_seen += 1
                if days_seen >= n_days:
                    break
            if day_highs:
                setattr(result, f"mfe_{key}", round((max(day_highs) / alert_price - 1) * 100, 4))
            if day_lows:
                setattr(result, f"mae_{key}", round((min(day_lows) / alert_price - 1) * 100, 4))
        return result

    # Stored-fields fallback — MFE only, MAE always null
    mapping = {
        "stored_return_next_day_high_pct": "mfe_1d",
        "stored_return_two_day_high_pct":  "mfe_2d",
        "stored_return_five_day_high_pct": "mfe_5d",
    }
    for stored_key, result_field in mapping.items():
        v = stored_fields.get(stored_key)
        if v is not None:
            setattr(result, result_field, v)
    return result


_TRAP_ACTIVATE_PCT    = 20.0   # stock must rise >= +20% to activate TRAP watch
_TRAP_RULE1_DOWN_PCT  = -20.0  # Rule 1: low must fall to <= -20% from alert
_TRAP_RULE2_PEAK_LOSS = 40.0   # Rule 2: close must lose >= 40% from peak
_DIRTY_MAE_THRESHOLD  = -15.0  # rolling MAE <= -15% before target → DIRTY


def compute_drawdown_quality(
    intraday_bars: Optional[List[Any]],
    daily_bars: Optional[List[Any]],
    alert_price: float,
    tier: Optional[str],
    drawdown_data_quality: str,
    alert_time: Optional[datetime] = None,
) -> Optional[str]:
    """Classify drawdown quality: CLEAN_RUNNER, DIRTY_RUNNER, or TRAP.

    TRAP is checked over the full observation window and takes precedence.
    CLEAN/DIRTY is only checked when the tier target is reached.
    Returns None when tier is None or drawdown_data_quality is "missing".
    """
    if drawdown_data_quality == "missing" or tier is None or alert_price <= 0:
        return None

    _TIER_TARGETS = {
        "STANDARD_WIN":     10.0,
        "MAJOR_RUNNER":     30.0,
        "MONSTER_RUNNER":  100.0,
        "LEGENDARY_RUNNER": 300.0,
    }
    target_pct = _TIER_TARGETS.get(tier)
    if target_pct is None:
        return None

    bars = intraday_bars if intraday_bars else (daily_bars if daily_bars else [])
    if not bars:
        return None

    # Filter to bars after alert_time only
    if alert_time is not None:
        alert_dt = _aware(alert_time)
        bars = [b for b in bars if (_bar_ts(b) is not None and _aware(_bar_ts(b)) >= alert_dt)]
    if not bars:
        return None

    target_price     = alert_price * (1.0 + target_pct / 100.0)
    trap_up_thresh   = alert_price * (1.0 + _TRAP_ACTIVATE_PCT / 100.0)
    trap_down_thresh = alert_price * (1.0 + _TRAP_RULE1_DOWN_PCT / 100.0)

    # ── Pass 1: TRAP detection (full window) ─────────────────────────────
    peak_seen = alert_price
    activated = False  # saw >= +20% from alert

    for bar in bars:
        h = _bar_high(bar)
        l = _bar_low(bar)
        c = _bar_close(bar)

        if h is not None:
            peak_seen = max(peak_seen, h)
            if h >= trap_up_thresh:
                activated = True

        if activated:
            # Rule 1: low drops to ≤ -20% from alert
            if l is not None and l <= trap_down_thresh:
                return "TRAP"
            # Rule 2: close loses ≥ 40% from peak
            if c is not None and peak_seen > 0:
                if (1.0 - c / peak_seen) * 100.0 >= _TRAP_RULE2_PEAK_LOSS:
                    return "TRAP"

    # ── Pass 2: CLEAN / DIRTY (path to target) ───────────────────────────
    rolling_mae = 0.0  # min (low / alert_price - 1) * 100, tracks worst excursion

    for bar in bars:
        l = _bar_low(bar)
        h = _bar_high(bar)

        if l is not None:
            mae = (l / alert_price - 1.0) * 100.0
            if mae < rolling_mae:
                rolling_mae = mae

        if h is not None and h >= target_price:
            return "DIRTY_RUNNER" if rolling_mae <= _DIRTY_MAE_THRESHOLD else "CLEAN_RUNNER"

    return None  # target never reached


def _compute_data_quality_score(record: "RocketRecord") -> float:
    """Score 0–100 reflecting how reliably this record can be labeled.

    Weights sum to exactly 100:
      intraday_bars available   = 30
      peak_timestamp available  = 10
      runner_tier assigned      = 10
      drawdown_quality assigned = 10
      each MFE+MAE window pair  =  8  (× 5 windows = 40)
    """
    score = 0.0
    if record.intraday_bars and record.peak_timestamp is not None:
        score += 30.0
    if record.peak_timestamp is not None:
        score += 10.0
    if record.runner_tier is not None:
        score += 10.0
    if record.drawdown_quality is not None:
        score += 10.0
    pairs = [
        (record.mfe_15m, record.mae_15m),
        (record.mfe_60m, record.mae_60m),
        (record.mfe_1d,  record.mae_1d),
        (record.mfe_2d,  record.mae_2d),
        (record.mfe_5d,  record.mae_5d),
    ]
    for mfe, mae in pairs:
        if mfe is not None and mae is not None:
            score += 8.0
    return min(100.0, score)


# ---------------------------------------------------------------------------
# Module-level report writer
# ---------------------------------------------------------------------------


def _write_report(
    path: Path,
    records: List[RocketRecord],
    exportable: List[RocketRecord],
    rejected: List[RocketRecord],
    df: "pd.DataFrame",
    tier_counts: Dict[str, int],
    dq_counts: Dict[str, int],
    rej_reasons: Dict[str, int],
    null_rates: Dict[str, float],
    fetch_stats: Dict[str, int],
    proxy_rows: int,
    dedup_records: List[RocketRecord],
    non_manifest: List[str],
    dataset_version: str,
    builder_version: str,
    created_at: datetime,
    elapsed: float,
) -> None:
    n_exp = len(exportable)
    n_ing = len(records)

    def _pct(n: int, total: int) -> str:
        return f"{n / max(total, 1) * 100:.1f}%"

    lines: List[str] = [
        "# Rocket Dataset Report",
        "",
        "## Run Metadata",
        "| Field | Value |",
        "|---|---|",
        f"| dataset_version | `{dataset_version}` |",
        f"| builder_version | `{builder_version}` |",
        f"| created_at | {created_at.isoformat()} |",
        f"| elapsed_seconds | {elapsed:.1f} |",
        "",
        "## Row Counts",
        "| Source | Ingested | Exported | Rejected |",
        "|---|---|---|---|",
    ]

    # Per-source counts
    by_source: Dict[str, Dict[str, int]] = {}
    for rec in records:
        s = rec.source_type
        if s not in by_source:
            by_source[s] = {"ing": 0, "exp": 0, "rej": 0}
        by_source[s]["ing"] += 1
        if rec.rejection_reason:
            by_source[s]["rej"] += 1
    for rec in exportable:
        by_source.setdefault(rec.source_type, {"ing": 0, "exp": 0, "rej": 0})
        by_source[rec.source_type]["exp"] += 1

    for src, cnts in sorted(by_source.items()):
        lines.append(f"| {src} | {cnts['ing']} | {cnts['exp']} | {cnts['rej']} |")
    lines += [
        f"| **TOTAL** | **{n_ing}** | **{n_exp}** | **{len(rejected)}** |",
        "",
        "## Rejection Summary",
        "| Reason | Count | % of Ingested |",
        "|---|---|---|",
    ]
    for reason, cnt in sorted(rej_reasons.items(), key=lambda x: -x[1]):
        lines.append(f"| {reason} | {cnt} | {_pct(cnt, n_ing)} |")

    lines += [
        "",
        "## Duplicate Summary",
        "| Kept Source | Dropped Source | Dedup Reason | Count |",
        "|---|---|---|---|",
    ]
    dedup_summary: Dict[Tuple[str, str, str], int] = {}
    for rec in dedup_records:
        key = (
            rec.kept_source_type or "",
            rec.dropped_source_type or "",
            rec.dedup_reason or "",
        )
        dedup_summary[key] = dedup_summary.get(key, 0) + 1
    for (kept, dropped, reason), cnt in sorted(dedup_summary.items()):
        lines.append(f"| {kept} | {dropped} | {reason} | {cnt} |")

    lines += [
        "",
        "## Pricing & Enrichment",
        "| Metric | Value |",
        "|---|---|",
        f"| fetched | {fetch_stats.get('fetched', 0)} |",
        f"| unavailable | {fetch_stats.get('unavailable', 0)} |",
    ]
    outcome_src_counts = _count_values(exportable, "outcome_source")
    for src, cnt in sorted(outcome_src_counts.items()):
        lines.append(f"| outcome_source={src} | {cnt} |")

    lines += [
        "",
        "## Runner Tier Distribution",
        "| Tier | Count | % |",
        "|---|---|---|",
    ]
    for tier in sorted(RUNNER_TIERS):
        cnt = tier_counts.get(tier, 0)
        lines.append(f"| {tier} | {cnt} | {_pct(cnt, n_exp)} |")
    # True null = exportable rows without any tier assigned
    tier_null = n_exp - sum(tier_counts.values())
    lines.append(f"| _(unlabeled)_ | {tier_null} | {_pct(tier_null, n_exp)} |")

    lines += [
        "",
        "## Drawdown Quality Distribution",
        "",
        f"> ⚠️ `daily_proxy` rows ({proxy_rows}) carry lower-confidence CLEAN/DIRTY labels "
        f"derived from daily-bar lows. Do not treat them as equivalent to `intraday_exact` rows.",
        "",
        "| Quality | Count | % |",
        "|---|---|---|",
    ]
    for q in sorted(DRAWDOWN_QUAL):
        cnt = dq_counts.get(q, 0)
        lines.append(f"| {q} | {cnt} | {_pct(cnt, n_exp)} |")
    # True null = exportable rows without any drawdown quality assigned
    dq_null = n_exp - sum(dq_counts.values())
    lines.append(f"| _(unlabeled)_ | {dq_null} | {_pct(dq_null, n_exp)} |")
    lines.append(f"| _(daily_proxy rows)_ | {proxy_rows} | {_pct(proxy_rows, n_exp)} |")

    lines += [
        "",
        "## Feature Null Rates",
        "| Feature Column | Null % |",
        "|---|---|",
    ]
    for col, rate in sorted(null_rates.items(), key=lambda x: -x[1]):
        lines.append(f"| {col} | {rate * 100:.1f}% |")

    # Segmentation helpers
    def _seg(col: str, label: str) -> List[str]:
        seg: List[str] = ["", f"### By {label}", f"| {label} | Count | % |", "|---|---|---|"]
        if col in df.columns:
            for val, cnt in df[col].value_counts(dropna=False).items():
                seg.append(f"| {val} | {cnt} | {_pct(int(cnt), n_exp)} |")
        return seg

    lines += ["", "## Segmentation Breakdowns"]
    lines += _seg("catalyst_category", "Catalyst Category")
    lines += _seg("float_category",    "Float Bucket")
    lines += _seg("market_cap_category", "Market Cap Bucket")

    # Price bucket segmentation
    lines += ["", "### By Price Bucket", "| Price Bucket | Count | % |", "|---|---|---|"]
    if "price_at_alert" in df.columns:
        import pandas as _pd
        prices = _pd.to_numeric(df["price_at_alert"], errors="coerce")
        buckets = _pd.cut(
            prices,
            bins=[0, 1, 5, 10, float("inf")],
            labels=["$0–$1", "$1–$5", "$5–$10", ">$10"],
        )
        for label_, cnt in buckets.value_counts(sort=False).items():
            lines.append(f"| {label_} | {cnt} | {_pct(int(cnt), n_exp)} |")

    lines += [
        "",
        "## Dropped Non-Manifest Columns",
        "The following `RocketRecord` fields exist on the model but are not exported "
        "(they are neither in `FEATURE_COLUMNS` nor `LABEL_COLUMNS`).",
        "",
        "| Column | Reason |",
        "|---|---|",
    ]
    for col in non_manifest:
        lines.append(f"| {col} | not in FEATURE_COLUMNS or LABEL_COLUMNS |")
    if not non_manifest:
        lines.append("| _(none)_ | — |")

    path.write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# RocketDatasetBuilder
# ---------------------------------------------------------------------------


class RocketDatasetBuilder:
    """Four-stage pipeline: ingest → enrich → label → assemble."""

    def __init__(
        self,
        data_dir: Path = _DEFAULT_DATA_DIR,
        docs_dir: Path = _DEFAULT_DOCS_DIR,
    ) -> None:
        self.data_dir = Path(data_dir)
        self.docs_dir = Path(docs_dir)

    # ── Public API ────────────────────────────────────────────────────────

    def build(self) -> BuildSummary:
        """Run the full four-stage pipeline and return a BuildSummary."""
        import time as _t
        t0 = _t.monotonic()
        records = self._ingest()
        records = self._enrich(records)
        records = self._label(records)
        summary = self._assemble(records, elapsed=_t.monotonic() - t0)
        return summary

    # ── Stage 3: Labelling ────────────────────────────────────────────────

    def _label(self, records: List[RocketRecord]) -> List[RocketRecord]:
        for rec in records:
            if rec.rejection_reason:
                continue
            try:
                self._apply_labels(rec)
            except Exception as exc:
                logger.warning("Label error for %s: %s", rec.row_id, exc)
        return records

    @staticmethod
    def _apply_labels(rec: RocketRecord) -> None:
        """Apply all pure label functions to a single record in-place."""
        stored = {
            "stored_return_next_day_high_pct": rec.stored_return_next_day_high_pct,
            "stored_return_two_day_high_pct":  rec.stored_return_two_day_high_pct,
            "stored_return_five_day_high_pct": rec.stored_return_five_day_high_pct,
        }

        # Peak metrics
        pm = compute_peak_metrics(
            rec.intraday_bars,
            rec.daily_bars,
            rec.price_at_alert,
            rec.alert_time,
            stored_five_day_high_pct=rec.stored_return_five_day_high_pct,
        )
        rec.peak_move_pct                  = pm.peak_move_pct
        rec.peak_timestamp                 = pm.peak_timestamp
        rec.calendar_time_to_peak_minutes  = pm.calendar_time_to_peak_minutes
        rec.trading_time_to_peak_minutes   = pm.trading_time_to_peak_minutes

        # Outcome source
        if rec.intraday_bars or rec.daily_bars:
            rec.outcome_source = "bars" if rec.intraday_bars else "daily_proxy"
        elif any(v is not None for v in stored.values()):
            rec.outcome_source = "stored_resolved"
        else:
            rec.outcome_source = "missing"

        # Runner tier (prefer trading time, fall back to calendar time)
        time_mins = rec.trading_time_to_peak_minutes or rec.calendar_time_to_peak_minutes
        rec.runner_tier = compute_runner_tier(rec.peak_move_pct, time_mins)

        # MFE/MAE profiles
        profiles = compute_mfe_mae_profiles(
            rec.intraday_bars,
            rec.daily_bars,
            rec.price_at_alert,
            rec.alert_time,
            stored,
        )
        for field in MFEMAEProfiles.model_fields:
            setattr(rec, field, getattr(profiles, field))

        # Drawdown quality (pass alert_time for bar filtering)
        dq_flag = rec.drawdown_data_quality or "missing"
        rec.drawdown_quality = compute_drawdown_quality(
            rec.intraday_bars,
            rec.daily_bars,
            rec.price_at_alert,
            rec.runner_tier,
            dq_flag,
            alert_time=rec.alert_time,
        )

        # Data quality score
        rec.data_quality_score = _compute_data_quality_score(rec)

    # ── Stage 1: Ingestion ────────────────────────────────────────────────

    def _ingest(self) -> List[RocketRecord]:
        records: List[RocketRecord] = []
        records.extend(self._load_telegram())
        records.extend(self._load_shadow())
        records.extend(self._load_backfill())
        records.extend(self._load_missed())
        records.extend(self._load_prenews())
        records = self._deduplicate(records)
        logger.info(
            "Ingested %d records (%d rejected)",
            len(records),
            sum(1 for r in records if r.rejection_reason),
        )
        return records

    def _load_alert_file(self, filename: str, source_type: str) -> List[RocketRecord]:
        raw = load_json_file(str(self.data_dir / filename), default=[]) or []
        return [self._norm_telegram(r, source_type) for r in raw]

    def _load_telegram(self) -> List[RocketRecord]:
        return self._load_alert_file("news_momentum_telegram_alerts.json", "telegram")

    def _load_shadow(self) -> List[RocketRecord]:
        return self._load_alert_file("news_momentum_shadow_alerts.json", "shadow")

    def _load_backfill(self) -> List[RocketRecord]:
        return self._load_alert_file("news_momentum_backfill_records.json", "backfill")

    def _norm_telegram(self, raw: Dict[str, Any], source_type: str) -> RocketRecord:
        """Normalise telegram/shadow/backfill records (all share the same schema)."""
        alert_id  = raw.get("alert_id") or f"{source_type}_{id(raw)}"
        row_id    = f"{source_type}_{alert_id}"
        ticker    = (raw.get("ticker") or "").strip().upper()
        alert_time = _parse_dt(raw.get("sent_at"))
        price     = _to_float(raw.get("price_at_alert"))
        cat_type  = raw.get("catalyst_type") or None
        cat_sub   = raw.get("catalyst_subtype") or None
        rejection = _anchor_check(ticker, alert_time, price, cat_type, cat_sub, source_type)
        return RocketRecord(
            row_id=row_id,
            source_type=source_type,
            rejection_reason=rejection,
            ticker=ticker or _UNKNOWN_TICKER,
            alert_time=alert_time or datetime(2000, 1, 1, tzinfo=timezone.utc),
            price_at_alert=price or 0.0,
            catalyst_type=cat_type,
            catalyst_subtype=cat_sub,
            catalyst_category=raw.get("catalyst_category"),
            session_type=raw.get("session_type"),
            float_category=raw.get("float_category"),
            market_cap_category=raw.get("market_cap_category"),
            move_pct_at_alert=_to_float(raw.get("move_pct_at_alert")),
            rvol_at_alert=_to_float(raw.get("rvol_at_alert")),
            volume_at_alert=_to_int(raw.get("volume_at_alert")),
            spread_pct_at_alert=_to_float(raw.get("spread_pct_at_alert")),
            trap_risk_at_alert=_to_float(raw.get("trap_risk_at_alert")),
            dilution_risk_at_alert=_to_float(raw.get("dilution_risk_at_alert")),
            velocity_score_at_alert=_to_float(raw.get("velocity_score_at_alert")),
            sources_seen_count=_to_int(raw.get("sources_seen_count")),
            is_negative=raw.get("is_negative"),
            is_vague=raw.get("is_vague"),
            is_delayed_reaction=raw.get("is_delayed_reaction"),
            prenews_anomaly_score=_to_float(raw.get("prenews_anomaly_score")),
            ml_predicted_win_prob=_to_float(raw.get("ml_predicted_win_prob")),
            news_impact_score=_to_float(raw.get("news_impact_score")),
            expected_return_score=_to_float(raw.get("expected_return_score")),
            continuation_probability=_to_float(raw.get("continuation_probability")),
            multi_day_score=_to_float(raw.get("multi_day_score")),
            sec_dilution_probability=_to_float(raw.get("sec_dilution_probability")),
            sec_toxic_financing_score=_to_float(raw.get("sec_toxic_financing_score")),
            sec_warrant_overhang_score=_to_float(raw.get("sec_warrant_overhang_score")),
            sec_cash_runway_score=_to_float(raw.get("sec_cash_runway_score")),
            sec_survival_risk_score=_to_float(raw.get("sec_survival_risk_score")),
            sec_balance_sheet_quality_score=_to_float(raw.get("sec_balance_sheet_quality_score")),
            sec_offering_risk_score=_to_float(raw.get("sec_offering_risk_score")),
            sec_reverse_split_risk_score=_to_float(raw.get("sec_reverse_split_risk_score")),
            sec_structural_trap_risk_score=_to_float(raw.get("sec_structural_trap_risk_score")),
            sec_historical_dilution_behavior_score=_to_float(raw.get("sec_historical_dilution_behavior_score")),
            sec_dilution_behavior=raw.get("sec_dilution_behavior"),
            sec_oracle_action=raw.get("sec_oracle_action"),
            sec_atm_active=raw.get("sec_atm_active"),
            sec_going_concern_active=raw.get("sec_going_concern_active"),
            outcome_window_start=alert_time,
            # Internal stored-field fallbacks (excluded from export)
            stored_mfe_pct=_to_float(raw.get("mfe_pct")),
            stored_mae_pct=_to_float(raw.get("mae_pct")),
            stored_return_next_day_high_pct=_to_float(raw.get("return_next_day_high_pct")),
            stored_return_two_day_high_pct=_to_float(raw.get("return_two_day_high_pct")),
            stored_return_five_day_high_pct=_to_float(raw.get("return_five_day_high_pct")),
            stored_return_15m_pct=_to_float(raw.get("return_15m_pct")),
            stored_return_1h_pct=_to_float(raw.get("return_1h_pct")),
            stored_return_4h_pct=_to_float(raw.get("return_4h_pct")),
        )

    def _load_missed(self) -> List[RocketRecord]:
        path = self.data_dir / "news_momentum_missed_winners.json"
        raw = load_json_file(str(path), default=[]) or []
        out: List[RocketRecord] = []
        for r in raw:
            alert_id  = r.get("id") or f"missed_{id(r)}"
            row_id    = f"missed_{alert_id}"
            ticker    = (r.get("ticker") or "").strip().upper()
            alert_time = _parse_dt(r.get("news_time"))
            price     = _to_float(r.get("price_at_news"))
            cat_sub   = r.get("catalyst_sub_type") or r.get("catalyst_subtype") or None
            cat_type  = r.get("catalyst_category") or None
            rejection = _anchor_check(ticker, alert_time, price, cat_type, cat_sub, "missed")
            out.append(RocketRecord(
                row_id=row_id,
                source_type="missed",
                rejection_reason=rejection,
                ticker=ticker or _UNKNOWN_TICKER,
                alert_time=alert_time or datetime(2000, 1, 1, tzinfo=timezone.utc),
                price_at_alert=price or 0.0,
                catalyst_type=cat_type,
                catalyst_subtype=cat_sub,
                catalyst_category=cat_type,
                news_impact_score=_to_float(r.get("news_impact_score")),
                expected_return_score=_to_float(r.get("expected_return_score")),
                continuation_probability=_to_float(r.get("continuation_probability")),
                multi_day_score=_to_float(r.get("multi_day_score")),
                trap_risk_at_alert=_to_float(r.get("trap_risk")),
                dilution_risk_at_alert=_to_float(r.get("dilution_risk")),
                outcome_window_start=alert_time,
            ))
        return out

    def _load_prenews(self) -> List[RocketRecord]:
        path = self.data_dir / "pre_news_shadow_v2.json"
        raw_obj = load_json_file(str(path), default={}) or {}
        if isinstance(raw_obj, list):
            raw = raw_obj
        elif isinstance(raw_obj, dict):
            raw = raw_obj.get("records", [])
        else:
            logger.warning("_load_prenews: unexpected format in pre_news_shadow_v2.json, skipping")
            raw = []
        out: List[RocketRecord] = []
        for r in raw:
            shadow_id  = r.get("shadow_id") or f"prenews_{id(r)}"
            row_id     = f"prenews_{shadow_id}"
            ticker     = (r.get("ticker") or "").strip().upper()
            alert_time = _parse_dt(r.get("detection_time"))
            price      = _to_float(r.get("price_at_detection"))
            # prenews: no catalyst required (anomaly detected before any news)
            rejection  = _anchor_check(ticker, alert_time, price, None, None, "prenews")
            out.append(RocketRecord(
                row_id=row_id,
                source_type="prenews",
                rejection_reason=rejection,
                ticker=ticker or _UNKNOWN_TICKER,
                alert_time=alert_time or datetime(2000, 1, 1, tzinfo=timezone.utc),
                price_at_alert=price or 0.0,
                prenews_anomaly_score=_to_float(r.get("suspicion_score")),
                outcome_window_start=alert_time,
            ))
        return out

    def _deduplicate(self, records: List[RocketRecord]) -> List[RocketRecord]:
        """Keep the highest-priority source for each (ticker, minute-bucket).

        Dropped duplicates are retained in the list with rejection_reason="duplicate"
        and dedup metadata fields populated for the calibration report.
        Priority: telegram > missed > prenews > shadow > backfill
        """
        priority = {src: i for i, src in enumerate(DEDUP_PRIORITY)}
        best: Dict[Tuple[str, str], int] = {}  # bucket → index of winning record

        for i, rec in enumerate(records):
            if rec.rejection_reason:
                continue  # already-rejected rows don't participate in dedup
            bucket = _minute_bucket(rec.ticker, rec.alert_time)
            if bucket not in best:
                best[bucket] = i
            else:
                existing_idx = best[bucket]
                existing = records[existing_idx]
                new_pri = priority.get(rec.source_type, 99)
                old_pri = priority.get(existing.source_type, 99)
                if new_pri < old_pri:
                    # New record wins — mark existing as dropped
                    existing.duplicate_of        = rec.row_id
                    existing.dropped_source_type = existing.source_type
                    existing.kept_source_type    = rec.source_type
                    existing.dedup_reason        = _DEDUP_REASON_PRIORITY
                    existing.rejection_reason    = _REJECTION_DUPLICATE
                    best[bucket] = i
                else:
                    # Existing wins — mark new as dropped
                    rec.duplicate_of        = existing.row_id
                    rec.dropped_source_type = rec.source_type
                    rec.kept_source_type    = existing.source_type
                    rec.dedup_reason        = _DEDUP_REASON_PRIORITY
                    rec.rejection_reason    = _REJECTION_DUPLICATE
        return records

    # ── Stage 2: Enrichment ───────────────────────────────────────────────────────

    def _enrich(self, records: List[RocketRecord]) -> List[RocketRecord]:
        """Fetch missing forward pricing for records that need it.

        Uses a per-ticker cache so each ticker is fetched at most once per run.
        Rate-limited to _FETCH_DELAY seconds between calls.
        Failures are logged at DEBUG level and never raised.
        """
        try:
            from src.services.market_data import get_market_data_provider
            provider = get_market_data_provider()
        except Exception as exc:
            logger.warning("Enrichment: market data provider unavailable: %s", exc)
            for rec in records:
                if rec.rejection_reason:
                    continue
                if not rec.intraday_bars and not rec.daily_bars:
                    rec.drawdown_data_quality = "missing"
            return records

        fetch_cache: Dict[str, Dict[str, Any]] = {}

        for rec in records:
            if rec.rejection_reason:
                continue

            # Records that already have bars (e.g. pre-enriched) — just set quality flag
            intraday_ok = bool(rec.intraday_bars)
            daily_ok    = bool(rec.daily_bars)
            if intraday_ok or daily_ok:
                if rec.drawdown_data_quality is None:
                    rec.drawdown_data_quality = "intraday_exact" if intraday_ok else "daily_proxy"
                continue

            ticker = rec.ticker
            if ticker not in fetch_cache:
                if fetch_cache:  # skip throttle before first call; sleep before subsequent ones
                    _time_module.sleep(_FETCH_DELAY)
                intraday, daily = self._fetch_bars(provider, ticker)
                fetch_cache[ticker] = {"intraday": intraday, "daily": daily}

            cached = fetch_cache[ticker]
            rec.intraday_bars = cached["intraday"]
            rec.daily_bars    = cached["daily"]

            if rec.intraday_bars:
                rec.drawdown_data_quality = "intraday_exact"
            elif rec.daily_bars:
                rec.drawdown_data_quality = "daily_proxy"
            else:
                rec.drawdown_data_quality = "missing"

        fetched    = sum(1 for v in fetch_cache.values() if v["intraday"] or v["daily"])
        unavailable = sum(1 for v in fetch_cache.values() if not v["intraday"] and not v["daily"])
        logger.info("Enrichment: unique tickers fetched=%d unavailable=%d", fetched, unavailable)
        return records

    @staticmethod
    def _fetch_bars(
        provider: Any, ticker: str
    ) -> Tuple[Optional[List[Any]], Optional[List[Any]]]:
        """Fetch intraday (5m) and daily (1d) bars for ticker. Never raises."""
        intraday: Optional[List[Any]] = None
        daily:    Optional[List[Any]] = None
        try:
            result = provider.get_ohlcv(ticker, period="30d", interval="5m", prepost=True)
            intraday = result or None
        except Exception as exc:
            logger.debug("Enrichment: intraday fetch failed %s: %s", ticker, exc)
        try:
            result = provider.get_ohlcv(ticker, period="30d", interval="1d", prepost=False)
            daily = result or None
        except Exception as exc:
            logger.debug("Enrichment: daily fetch failed %s: %s", ticker, exc)
        return intraday, daily

    # ── Stage 4: Assembly ─────────────────────────────────────────────────

    def _assemble(
        self, records: List[RocketRecord], elapsed: float = 0.0
    ) -> "BuildSummary":
        """Apply leakage manifest, export CSV/Parquet/rejected, write report."""
        created_at = datetime.now(timezone.utc)

        # Detect non-manifest columns (report but do not export)
        all_fields   = set(RocketRecord.model_fields.keys())
        manifest     = set(_EXPORT_COLUMNS)
        # Internal/pipeline fields excluded by design — not counted as "dropped"
        _INTERNAL = _INTERNAL_FIELDS
        non_manifest = sorted(all_fields - manifest - _INTERNAL)

        valid    = [r for r in records if not r.rejection_reason]
        rejected = [r for r in records if r.rejection_reason]

        # Only export rows that have at least one label populated
        exportable = [
            r for r in valid
            if any(getattr(r, c, None) is not None for c in LABEL_COLUMNS)
        ]

        # Build DataFrame using only manifest columns
        rows = [
            {c: getattr(rec, c, None) for c in _EXPORT_COLUMNS}
            for rec in exportable
        ]
        df = (
            pd.DataFrame(rows, columns=_EXPORT_COLUMNS)
            if rows
            else pd.DataFrame(columns=_EXPORT_COLUMNS)
        )

        # Write outputs
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.docs_dir.mkdir(parents=True, exist_ok=True)

        csv_path      = self.data_dir / "rocket_training_dataset.csv"
        parquet_path  = self.data_dir / "rocket_training_dataset.parquet"
        rejected_path = self.data_dir / "rocket_rejected_rows.csv"
        report_path   = self.docs_dir / "rocket_dataset_report.md"

        df.to_csv(str(csv_path), index=False, encoding="utf-8")
        df.to_parquet(str(parquet_path), compression="snappy", index=False)

        rej_rows = [
            {
                "row_id":           r.row_id,
                "source_type":      r.source_type,
                "ticker":           r.ticker,
                "rejection_reason": r.rejection_reason,
            }
            for r in rejected
        ]
        pd.DataFrame(rej_rows).to_csv(str(rejected_path), index=False, encoding="utf-8")

        # Compute stats for BuildSummary and report
        tier_counts = _count_values(exportable, "runner_tier")
        dq_counts   = _count_values(exportable, "drawdown_quality")
        rej_reasons = _count_values(rejected,   "rejection_reason")
        null_rates  = _null_rates(df, FEATURE_COLUMNS)
        proxy_rows  = sum(1 for r in exportable if r.drawdown_data_quality == "daily_proxy")
        dedup_recs  = [r for r in records if r.dedup_reason]

        # Pricing fetch stats: count drawdown_data_quality distribution
        fetch_stats: Dict[str, int] = {"fetched": 0, "unavailable": 0}
        for rec in exportable:
            if rec.drawdown_data_quality in ("intraday_exact", "daily_proxy"):
                fetch_stats["fetched"] += 1
            elif rec.drawdown_data_quality == "missing":
                fetch_stats["unavailable"] += 1

        _write_report(
            path=report_path,
            records=records,
            exportable=exportable,
            rejected=rejected,
            df=df,
            tier_counts=tier_counts,
            dq_counts=dq_counts,
            rej_reasons=rej_reasons,
            null_rates=null_rates,
            fetch_stats=fetch_stats,
            proxy_rows=proxy_rows,
            dedup_records=dedup_recs,
            non_manifest=non_manifest,
            dataset_version=DATASET_VERSION,
            builder_version=BUILDER_VERSION,
            created_at=created_at,
            elapsed=elapsed,
        )

        logger.info(
            "Assembled: ingested=%d exported=%d rejected=%d",
            len(records), len(exportable), len(rejected),
        )

        return BuildSummary(
            total_ingested=len(records),
            total_rejected=len(rejected),
            total_exported=len(exportable),
            runner_tier_counts=tier_counts,
            drawdown_quality_counts=dq_counts,
            null_rate_by_feature=null_rates,
            rejection_reasons=rej_reasons,
            output_paths={
                "csv":     str(csv_path),
                "parquet": str(parquet_path),
                "report":  str(report_path),
            },
            pricing_fetch_stats=fetch_stats,
            dataset_version=DATASET_VERSION,
            builder_version=BUILDER_VERSION,
            created_at=created_at,
        )
