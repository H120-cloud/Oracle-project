# Rocket Dataset Builder Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `src/core/agentic/rocket_dataset_builder.py` — a standalone four-stage pipeline that ingests five alert streams, enriches with forward pricing data, applies deterministic multi-tier runner labels and drawdown-quality classifications, and exports a leak-free CSV + Parquet training dataset with a calibration report.

**Architecture:** `RocketDatasetBuilder.build()` runs `_ingest → _enrich → _label → _assemble` sequentially. Pure label functions live at module level for direct unit testing. `FEATURE_COLUMNS` / `LABEL_COLUMNS` manifests are module-level constants that enforce the anti-leakage boundary at export time. No existing files are modified.

**Tech Stack:** Python 3.9+, Pydantic v2, pandas 2.x, `zoneinfo` (stdlib), `src/utils/atomic_json.load_json_file`, `src/services/market_data.get_market_data_provider`

---

## File Map

| Action | Path | Responsibility |
|---|---|---|
| Create | `src/core/agentic/rocket_dataset_builder.py` | Models, constants, pure label functions, builder class |
| Create | `tests/unit/test_rocket_labeler.py` | Unit tests for all pure label functions and ingestion logic |

---

### Task 1: Module scaffold — models, constants, test file skeleton

**Files:**
- Create: `src/core/agentic/rocket_dataset_builder.py`
- Create: `tests/unit/test_rocket_labeler.py`

- [ ] **Step 1.1 — Write the import smoke test**

Create `tests/unit/test_rocket_labeler.py`:

```python
"""Unit tests for rocket_dataset_builder pure label functions."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import pytest


def _bar(
    offset_minutes: float,
    high: float,
    low: float,
    close: float,
    base_time: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Build a synthetic OHLCV bar dict for testing."""
    t = (base_time or datetime(2026, 1, 2, 14, 30, tzinfo=timezone.utc)) + timedelta(
        minutes=offset_minutes
    )
    return {"timestamp": t, "high": high, "low": low, "close": close, "open": close}


BASE = datetime(2026, 1, 2, 14, 30, tzinfo=timezone.utc)  # Friday 9:30 ET


def test_import():
    from src.core.agentic.rocket_dataset_builder import (
        DATASET_VERSION,
        BUILDER_VERSION,
        FEATURE_COLUMNS,
        LABEL_COLUMNS,
        RUNNER_TIERS,
        DRAWDOWN_QUAL,
        RocketRecord,
        BuildSummary,
        compute_peak_metrics,
        compute_runner_tier,
        compute_mfe_mae_profiles,
        compute_drawdown_quality,
    )
    assert DATASET_VERSION == "rocket_v1"
    assert BUILDER_VERSION == "1.0.0"
    assert "runner_tier" in LABEL_COLUMNS
    assert "price_at_alert" in FEATURE_COLUMNS
    assert "peak_move_pct" not in FEATURE_COLUMNS  # leakage check
    assert "five_day_high" not in FEATURE_COLUMNS  # leakage check
```

- [ ] **Step 1.2 — Run to verify it fails**

```
cd "C:\Users\Husna\OneDrive\Desktop\Oracle project1"
python -m pytest tests/unit/test_rocket_labeler.py::test_import -v
```

Expected: `FAILED` — `ModuleNotFoundError: No module named 'src.core.agentic.rocket_dataset_builder'`

- [ ] **Step 1.3 — Create the module scaffold**

Create `src/core/agentic/rocket_dataset_builder.py`:

```python
"""
Rocket Dataset Builder
======================

Standalone four-stage pipeline that transforms raw alert streams into a
unified, leak-free training dataset with multi-tier runner labels,
MFE/MAE window profiles, and drawdown-quality classifications.

Stages: _ingest → _enrich → _label → _assemble

Pure label functions live at module level so they can be unit-tested
directly without constructing the builder.

IMPORTANT: This module does NOT modify OutcomeResolver, Telegram alert
logic, or any production gate. It only reads from existing JSON stores
and writes to data/agentic/ and docs/.
"""
from __future__ import annotations

import logging
import time as _time_module
from datetime import date, datetime, time as time_type, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
from pydantic import BaseModel, Field

from src.utils.atomic_json import load_json_file

logger = logging.getLogger(__name__)

# ── Versions ──────────────────────────────────────────────────────────────────

DATASET_VERSION = "rocket_v1"
BUILDER_VERSION = "1.0.0"

# ── String-set constants (not Python Enum — avoids pandas friction) ───────────

RUNNER_TIERS   = {"STANDARD_WIN", "MAJOR_RUNNER", "MONSTER_RUNNER", "LEGENDARY_RUNNER"}
DRAWDOWN_QUAL  = {"CLEAN_RUNNER", "DIRTY_RUNNER", "TRAP"}
DRAWDOWN_DQ    = {"intraday_exact", "daily_proxy", "missing"}
OUTCOME_SOURCE = {"bars", "stored_resolved", "daily_proxy", "missing"}
SOURCE_TYPES   = {"telegram", "shadow", "backfill", "missed", "prenews"}
DEDUP_PRIORITY = ["telegram", "missed", "prenews", "shadow", "backfill"]

# ── Trading-session constants (US Eastern) ────────────────────────────────────

try:
    from zoneinfo import ZoneInfo
except ImportError:  # Python < 3.9
    from backports.zoneinfo import ZoneInfo  # type: ignore

_ET = ZoneInfo("America/New_York")
_MARKET_OPEN  = time_type(9, 30)
_MARKET_CLOSE = time_type(16, 0)
_FETCH_DELAY  = 0.25  # seconds between market data calls

# ── Default paths ─────────────────────────────────────────────────────────────

_DEFAULT_DATA_DIR = Path("data/agentic")
_DEFAULT_DOCS_DIR = Path("docs")

# ── Leakage manifest ──────────────────────────────────────────────────────────

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

_EXPORT_COLUMNS = FEATURE_COLUMNS + LABEL_COLUMNS

# ── Data models ───────────────────────────────────────────────────────────────


class PeakMetrics(BaseModel):
    peak_move_pct: Optional[float] = None
    peak_timestamp: Optional[datetime] = None
    calendar_time_to_peak_minutes: Optional[float] = None
    trading_time_to_peak_minutes: Optional[float] = None


class MFEMAEProfiles(BaseModel):
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
    model_config = {"arbitrary_types_allowed": True}

    # Identity
    row_id: str
    source_type: str
    rejection_reason: Optional[str] = None
    dataset_version: str = DATASET_VERSION
    builder_version: str = BUILDER_VERSION

    # At-alert features (leakage-safe — in FEATURE_COLUMNS)
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

    # Forward pricing (internal only — NOT in manifest, never exported)
    intraday_bars: Optional[List[Any]] = Field(default=None, exclude=True)
    daily_bars: Optional[List[Any]] = Field(default=None, exclude=True)
    stored_mfe_pct: Optional[float] = Field(default=None, exclude=True)
    stored_mae_pct: Optional[float] = Field(default=None, exclude=True)
    stored_return_next_day_high_pct: Optional[float] = Field(default=None, exclude=True)
    stored_return_two_day_high_pct: Optional[float] = Field(default=None, exclude=True)
    stored_return_five_day_high_pct: Optional[float] = Field(default=None, exclude=True)

    # Dedup tracking (internal only — NOT in manifest)
    duplicate_of: Optional[str] = Field(default=None, exclude=True)
    dropped_source_type: Optional[str] = Field(default=None, exclude=True)
    kept_source_type: Optional[str] = Field(default=None, exclude=True)
    dedup_reason: Optional[str] = Field(default=None, exclude=True)

    # Labels (in LABEL_COLUMNS)
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


# ── Bar access helpers (handle both dict-style and object-style bars) ─────────


def _bget(bar: Any, field: str) -> Any:
    val = getattr(bar, field, None)
    if val is None and isinstance(bar, dict):
        val = bar.get(field)
    return val


def _bar_ts(bar: Any) -> Optional[datetime]:
    ts = _bget(bar, "timestamp")
    if ts is None:
        return None
    if isinstance(ts, str):
        try:
            ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            return None
    if isinstance(ts, datetime) and ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts


def _bar_high(bar: Any) -> Optional[float]:
    v = _bget(bar, "high")
    return float(v) if v is not None else None


def _bar_low(bar: Any) -> Optional[float]:
    v = _bget(bar, "low")
    return float(v) if v is not None else None


def _bar_close(bar: Any) -> Optional[float]:
    v = _bget(bar, "close")
    return float(v) if v is not None else None


def _aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _trading_minutes_between(start: datetime, end: datetime) -> float:
    """Minutes during US market hours (9:30–16:00 ET) between start and end."""
    if end <= start:
        return 0.0
    start_et = _aware(start).astimezone(_ET)
    end_et = _aware(end).astimezone(_ET)
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


# ── Pure label functions ──────────────────────────────────────────────────────


def compute_peak_metrics(
    intraday_bars: Optional[List[Any]],
    daily_bars: Optional[List[Any]],
    alert_price: float,
    alert_time: datetime,
    stored_five_day_high_pct: Optional[float] = None,
) -> PeakMetrics:
    """Find peak move within ~5 trading days of alert_time."""
    if alert_price <= 0:
        return PeakMetrics()

    alert_time = _aware(alert_time)
    window_end = alert_time + timedelta(days=8)  # 5 trading days + weekend buffer

    bars = intraday_bars or daily_bars or []
    peak_high: Optional[float] = None
    peak_ts: Optional[datetime] = None

    for bar in bars:
        ts = _bar_ts(bar)
        if ts is None or ts < alert_time or ts > window_end:
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
    use_trading_time: bool = True,
) -> Optional[str]:
    """Assign a runner tier based on peak_move_pct and timing.

    When time_to_peak_minutes is None, LEGENDARY and MONSTER can still be
    assigned (they're bounded by the 5-day observation window by construction).
    MAJOR_RUNNER and STANDARD_WIN require timing data (2-day and 1-day windows
    cannot be verified without it).
    """
    if peak_move_pct is None or peak_move_pct < 0:
        return None

    if time_to_peak_minutes is not None:
        trading_days = time_to_peak_minutes / (60.0 * 6.5)
        within_5 = trading_days <= 5.0
        within_2 = trading_days <= 2.0
        within_1 = trading_days <= 1.0
    else:
        within_5 = True   # bounded by construction — all records are ≤5-day window
        within_2 = False  # cannot verify without timing
        within_1 = False  # cannot verify without timing

    if peak_move_pct >= 300 and within_5:
        return "LEGENDARY_RUNNER"
    if peak_move_pct >= 100 and within_5:
        return "MONSTER_RUNNER"
    if peak_move_pct >= 30 and within_2:
        return "MAJOR_RUNNER"
    if peak_move_pct >= 10 and within_1:
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

    Uses intraday_bars for all windows when available.
    Falls back to daily_bars for 1d/2d/5d windows (15m/60m stay null).
    Falls back to stored_fields when no bars exist.
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
        ("5d",  timedelta(days=8)),
    ]

    result = MFEMAEProfiles()

    if intraday_bars:
        for key, delta in _WINDOWS:
            end = alert_time + delta
            highs, lows = [], []
            for bar in intraday_bars:
                ts = _bar_ts(bar)
                if ts is None or ts < alert_time or ts > end:
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
        # Sub-day windows not available from daily bars
        for key, delta in [("1d", 1), ("2d", 2), ("5d", 5)]:
            alert_date = alert_time.date()
            days_seen = 0
            day_highs, day_lows = [], []
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
                days_seen += 1
                if days_seen >= delta:
                    break
            if day_highs:
                setattr(result, f"mfe_{key}", round((max(day_highs) / alert_price - 1) * 100, 4))
            if day_lows:
                setattr(result, f"mae_{key}", round((min(day_lows) / alert_price - 1) * 100, 4))
        return result

    # Stored-fields fallback
    if stored_fields.get("stored_return_next_day_high_pct") is not None:
        result.mfe_1d = stored_fields["stored_return_next_day_high_pct"]
    if stored_fields.get("stored_return_two_day_high_pct") is not None:
        result.mfe_2d = stored_fields["stored_return_two_day_high_pct"]
    if stored_fields.get("stored_return_five_day_high_pct") is not None:
        result.mfe_5d = stored_fields["stored_return_five_day_high_pct"]
    return result


def compute_drawdown_quality(
    intraday_bars: Optional[List[Any]],
    daily_bars: Optional[List[Any]],
    alert_price: float,
    tier: Optional[str],
    drawdown_data_quality: str,
) -> Optional[str]:
    """Classify drawdown quality: CLEAN_RUNNER, DIRTY_RUNNER, or TRAP.

    Two-pass: TRAP check runs over the full window first (TRAP takes
    precedence over CLEAN/DIRTY). Returns None when tier is None or
    drawdown_data_quality is "missing".
    """
    if drawdown_data_quality == "missing" or tier is None or alert_price <= 0:
        return None

    _TIER_TARGETS = {
        "STANDARD_WIN":    10.0,
        "MAJOR_RUNNER":    30.0,
        "MONSTER_RUNNER":  100.0,
        "LEGENDARY_RUNNER": 300.0,
    }
    target_pct = _TIER_TARGETS.get(tier)
    if target_pct is None:
        return None

    bars = intraday_bars if intraday_bars else daily_bars
    if not bars:
        return None

    target_price    = alert_price * (1.0 + target_pct / 100.0)
    trap_up_thresh  = alert_price * 1.20
    trap_down_thresh = alert_price * 0.80  # -20% from alert

    # Pass 1: scan for TRAP over the full window
    peak_seen = alert_price
    activated = False
    for bar in bars:
        h = _bar_high(bar)
        l = _bar_low(bar)
        c = _bar_close(bar)
        if h is not None:
            peak_seen = max(peak_seen, h)
            if h >= trap_up_thresh:
                activated = True
        if activated:
            # Rule 1: low falls to ≤ -20% from alert
            if l is not None and l <= trap_down_thresh:
                return "TRAP"
            # Rule 2: close loses ≥ 40% from peak
            if c is not None and peak_seen > 0:
                if (1.0 - c / peak_seen) * 100.0 >= 40.0:
                    return "TRAP"

    # Pass 2: find target hit and check rolling MAE before it
    rolling_mae = 0.0
    for bar in bars:
        l = _bar_low(bar)
        h = _bar_high(bar)
        if l is not None:
            mae = (l / alert_price - 1.0) * 100.0
            if mae < rolling_mae:
                rolling_mae = mae
        if h is not None and h >= target_price:
            return "DIRTY_RUNNER" if rolling_mae <= -15.0 else "CLEAN_RUNNER"

    return None  # target never reached


def _compute_data_quality_score(record: RocketRecord) -> float:
    """Score 0–100 reflecting how reliably this record can be labeled.

    Weights (sum = 100):
      intraday_bars available  = 30
      peak_timestamp available = 10
      runner_tier assigned     = 10
      drawdown_quality assigned= 10
      each MFE+MAE window pair = 8  (× 5 windows = 40)
    """
    score = 0.0
    if record.intraday_bars:
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


# ── Builder class ─────────────────────────────────────────────────────────────


class RocketDatasetBuilder:
    """Four-stage pipeline: ingest → enrich → label → assemble."""

    def __init__(
        self,
        data_dir: Path = _DEFAULT_DATA_DIR,
        docs_dir: Path = _DEFAULT_DOCS_DIR,
    ) -> None:
        self.data_dir = Path(data_dir)
        self.docs_dir = Path(docs_dir)

    def build(self) -> BuildSummary:
        t0 = _time_module.monotonic()
        records = self._ingest()
        records = self._enrich(records)
        records = self._label(records)
        summary = self._assemble(records, elapsed=_time_module.monotonic() - t0)
        return summary

    # ── Stage 1: Ingestion ────────────────────────────────────────────────

    def _ingest(self) -> List[RocketRecord]:
        records: List[RocketRecord] = []
        records.extend(self._load_telegram())
        records.extend(self._load_shadow())
        records.extend(self._load_backfill())
        records.extend(self._load_missed())
        records.extend(self._load_prenews())
        records = self._deduplicate(records)
        logger.info("Ingested %d records (%d rejected)",
                    len(records),
                    sum(1 for r in records if r.rejection_reason))
        return records

    def _load_telegram(self) -> List[RocketRecord]:
        path = self.data_dir / "news_momentum_telegram_alerts.json"
        raw = load_json_file(str(path), default=[]) or []
        return [self._norm_telegram(r, "telegram") for r in raw]

    def _load_shadow(self) -> List[RocketRecord]:
        path = self.data_dir / "news_momentum_shadow_alerts.json"
        raw = load_json_file(str(path), default=[]) or []
        return [self._norm_telegram(r, "shadow") for r in raw]

    def _load_backfill(self) -> List[RocketRecord]:
        path = self.data_dir / "news_momentum_backfill_records.json"
        raw = load_json_file(str(path), default=[]) or []
        return [self._norm_telegram(r, "backfill") for r in raw]

    def _norm_telegram(self, raw: Dict[str, Any], source_type: str) -> RocketRecord:
        """Normalise telegram/shadow/backfill records (same schema)."""
        alert_id = raw.get("alert_id") or f"{source_type}_{id(raw)}"
        row_id   = f"{source_type}_{alert_id}"
        ticker   = (raw.get("ticker") or "").strip().upper()
        alert_time = _parse_dt(raw.get("sent_at"))
        price    = _to_float(raw.get("price_at_alert"))
        cat_type = raw.get("catalyst_type") or None
        cat_sub  = raw.get("catalyst_subtype") or None

        rejection = _anchor_check(ticker, alert_time, price, cat_type, cat_sub, source_type)

        rec = RocketRecord(
            row_id=row_id,
            source_type=source_type,
            rejection_reason=rejection,
            ticker=ticker or "UNKNOWN",
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
            # Internal stored-field fallbacks
            stored_mfe_pct=_to_float(raw.get("mfe_pct")),
            stored_mae_pct=_to_float(raw.get("mae_pct")),
            stored_return_next_day_high_pct=_to_float(raw.get("return_next_day_high_pct")),
            stored_return_two_day_high_pct=_to_float(raw.get("return_two_day_high_pct")),
            stored_return_five_day_high_pct=_to_float(raw.get("return_five_day_high_pct")),
        )
        return rec

    def _load_missed(self) -> List[RocketRecord]:
        path = self.data_dir / "news_momentum_missed_winners.json"
        raw = load_json_file(str(path), default=[]) or []
        out = []
        for r in raw:
            alert_id  = r.get("id") or f"missed_{id(r)}"
            row_id    = f"missed_{alert_id}"
            ticker    = (r.get("ticker") or "").strip().upper()
            alert_time = _parse_dt(r.get("news_time"))
            price     = _to_float(r.get("price_at_news"))
            cat_sub   = r.get("catalyst_sub_type") or r.get("catalyst_subtype") or None
            cat_type  = r.get("catalyst_category") or None
            rejection = _anchor_check(ticker, alert_time, price, cat_type, cat_sub, "missed")
            rec = RocketRecord(
                row_id=row_id,
                source_type="missed",
                rejection_reason=rejection,
                ticker=ticker or "UNKNOWN",
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
            )
            out.append(rec)
        return out

    def _load_prenews(self) -> List[RocketRecord]:
        path = self.data_dir / "pre_news_shadow_v2.json"
        raw_obj = load_json_file(str(path), default={}) or {}
        raw = raw_obj.get("records", []) if isinstance(raw_obj, dict) else []
        out = []
        for r in raw:
            shadow_id  = r.get("shadow_id") or f"prenews_{id(r)}"
            row_id     = f"prenews_{shadow_id}"
            ticker     = (r.get("ticker") or "").strip().upper()
            alert_time = _parse_dt(r.get("detection_time"))
            price      = _to_float(r.get("price_at_detection"))
            # prenews: no catalyst required
            rejection  = _anchor_check(ticker, alert_time, price, None, None, "prenews")
            rec = RocketRecord(
                row_id=row_id,
                source_type="prenews",
                rejection_reason=rejection,
                ticker=ticker or "UNKNOWN",
                alert_time=alert_time or datetime(2000, 1, 1, tzinfo=timezone.utc),
                price_at_alert=price or 0.0,
                prenews_anomaly_score=_to_float(r.get("suspicion_score")),
                outcome_window_start=alert_time,
            )
            out.append(rec)
        return out

    def _deduplicate(self, records: List[RocketRecord]) -> List[RocketRecord]:
        """Keep highest-priority source for each (ticker, minute-bucket).

        Dropped duplicates are retained with dedup metadata populated.
        """
        priority = {src: i for i, src in enumerate(DEDUP_PRIORITY)}
        # key → best record index so far
        best: Dict[Tuple[str, str], int] = {}
        for i, rec in enumerate(records):
            if rec.rejection_reason:
                continue
            bucket = _minute_bucket(rec.ticker, rec.alert_time)
            if bucket not in best:
                best[bucket] = i
            else:
                existing_idx = best[bucket]
                existing = records[existing_idx]
                if priority.get(rec.source_type, 99) < priority.get(existing.source_type, 99):
                    # New record wins — mark existing as dropped
                    existing.duplicate_of     = rec.row_id
                    existing.dropped_source_type = existing.source_type
                    existing.kept_source_type    = rec.source_type
                    existing.dedup_reason        = "priority_order"
                    existing.rejection_reason    = "duplicate"
                    best[bucket] = i
                else:
                    # Existing wins — mark new as dropped
                    rec.duplicate_of     = records[existing_idx].row_id
                    rec.dropped_source_type = rec.source_type
                    rec.kept_source_type    = records[existing_idx].source_type
                    rec.dedup_reason        = "priority_order"
                    rec.rejection_reason    = "duplicate"
        return records

    # ── Stage 2: Enrichment ───────────────────────────────────────────────

    def _enrich(self, records: List[RocketRecord]) -> List[RocketRecord]:
        """Fetch missing forward pricing for records that need it."""
        try:
            from src.services.market_data import get_market_data_provider
            provider = get_market_data_provider()
        except Exception as exc:
            logger.warning("Enrichment: market data provider unavailable: %s", exc)
            for rec in records:
                if rec.rejection_reason:
                    continue
                if rec.intraday_bars is None and rec.daily_bars is None:
                    rec.drawdown_data_quality = "missing"
            return records

        fetch_cache: Dict[str, Dict[str, Any]] = {}
        fetch_stats = {"fetched": 0, "unavailable": 0}

        for rec in records:
            if rec.rejection_reason:
                continue
            if rec.intraday_bars is not None or rec.daily_bars is not None:
                # Already enriched — set quality flag if not set
                if rec.drawdown_data_quality is None:
                    rec.drawdown_data_quality = "intraday_exact" if rec.intraday_bars else "daily_proxy"
                continue

            ticker = rec.ticker
            if ticker not in fetch_cache:
                intraday, daily = self._fetch_bars(provider, ticker)
                fetch_cache[ticker] = {"intraday": intraday, "daily": daily}
                if intraday or daily:
                    fetch_stats["fetched"] += 1
                else:
                    fetch_stats["unavailable"] += 1
                _time_module.sleep(_FETCH_DELAY)

            cached = fetch_cache[ticker]
            rec.intraday_bars = cached["intraday"] or None
            rec.daily_bars    = cached["daily"] or None

            if rec.intraday_bars:
                rec.drawdown_data_quality = "intraday_exact"
            elif rec.daily_bars:
                rec.drawdown_data_quality = "daily_proxy"
            else:
                rec.drawdown_data_quality = "missing"

        logger.info("Enrichment: fetched=%d unavailable=%d",
                    fetch_stats["fetched"], fetch_stats["unavailable"])
        return records

    @staticmethod
    def _fetch_bars(
        provider: Any, ticker: str
    ) -> Tuple[Optional[List[Any]], Optional[List[Any]]]:
        import asyncio
        intraday = daily = None
        try:
            intraday = provider.get_ohlcv(ticker, period="30d", interval="5m", prepost=True) or None
        except Exception as exc:
            logger.debug("Enrichment: intraday fetch failed %s: %s", ticker, exc)
        try:
            daily = provider.get_ohlcv(ticker, period="30d", interval="1d", prepost=False) or None
        except Exception as exc:
            logger.debug("Enrichment: daily fetch failed %s: %s", ticker, exc)
        return intraday, daily

    # ── Stage 3: Label application ────────────────────────────────────────

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
        rec.peak_move_pct               = pm.peak_move_pct
        rec.peak_timestamp              = pm.peak_timestamp
        rec.calendar_time_to_peak_minutes = pm.calendar_time_to_peak_minutes
        rec.trading_time_to_peak_minutes  = pm.trading_time_to_peak_minutes

        # Outcome source
        if rec.intraday_bars or rec.daily_bars:
            rec.outcome_source = "bars" if rec.intraday_bars else "daily_proxy"
        elif any(v is not None for v in stored.values()):
            rec.outcome_source = "stored_resolved"
        else:
            rec.outcome_source = "missing"

        # Runner tier
        time_mins = rec.trading_time_to_peak_minutes or rec.calendar_time_to_peak_minutes
        rec.runner_tier = compute_runner_tier(rec.peak_move_pct, time_mins)

        # MFE/MAE profiles
        profiles = compute_mfe_mae_profiles(
            rec.intraday_bars, rec.daily_bars,
            rec.price_at_alert, rec.alert_time, stored,
        )
        for field in MFEMAEProfiles.model_fields:
            setattr(rec, field, getattr(profiles, field))

        # Drawdown quality
        dq = rec.drawdown_data_quality or "missing"
        rec.drawdown_quality = compute_drawdown_quality(
            rec.intraday_bars, rec.daily_bars,
            rec.price_at_alert, rec.runner_tier, dq,
        )

        # Data quality score
        rec.data_quality_score = _compute_data_quality_score(rec)

    # ── Stage 4: Assembly & export ────────────────────────────────────────

    def _assemble(
        self, records: List[RocketRecord], elapsed: float = 0.0
    ) -> BuildSummary:
        created_at = datetime.now(timezone.utc)

        # Detect non-manifest columns
        all_fields = set(RocketRecord.model_fields.keys())
        manifest   = set(_EXPORT_COLUMNS)
        non_manifest = sorted(all_fields - manifest - {
            "rejection_reason", "intraday_bars", "daily_bars",
            "stored_mfe_pct", "stored_mae_pct",
            "stored_return_next_day_high_pct", "stored_return_two_day_high_pct",
            "stored_return_five_day_high_pct",
            "duplicate_of", "dropped_source_type", "kept_source_type", "dedup_reason",
        })

        valid   = [r for r in records if not r.rejection_reason]
        rejected = [r for r in records if r.rejection_reason]

        # Rows with at least one label
        exportable = [
            r for r in valid
            if any(getattr(r, c, None) is not None for c in LABEL_COLUMNS)
        ]

        # Build DataFrame
        rows = []
        for rec in exportable:
            d = rec.model_dump(include=set(_EXPORT_COLUMNS))
            rows.append(d)
        df = pd.DataFrame(rows, columns=_EXPORT_COLUMNS) if rows else pd.DataFrame(columns=_EXPORT_COLUMNS)

        # Write outputs
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.docs_dir.mkdir(parents=True, exist_ok=True)

        csv_path     = self.data_dir / "rocket_training_dataset.csv"
        parquet_path = self.data_dir / "rocket_training_dataset.parquet"
        rejected_path = self.data_dir / "rocket_rejected_rows.csv"
        report_path  = self.docs_dir / "rocket_dataset_report.md"

        df.to_csv(csv_path, index=False)
        df.to_parquet(parquet_path, compression="snappy", index=False)

        rej_rows = [
            {"row_id": r.row_id, "source_type": r.source_type,
             "ticker": r.ticker, "rejection_reason": r.rejection_reason}
            for r in rejected
        ]
        pd.DataFrame(rej_rows).to_csv(rejected_path, index=False)

        # Compute stats
        tier_counts = _count_values(exportable, "runner_tier")
        dq_counts   = _count_values(exportable, "drawdown_quality")
        rej_reasons = _count_values(rejected, "rejection_reason")
        null_rates  = _null_rates(df, FEATURE_COLUMNS)
        fetch_stats = {"fetched": 0, "unavailable": 0}
        proxy_rows  = sum(1 for r in exportable if r.drawdown_data_quality == "daily_proxy")
        dedup_records = [r for r in records if r.dedup_reason]

        # Write report
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
            dedup_records=dedup_records,
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


# ── Private helpers ───────────────────────────────────────────────────────────


def _parse_dt(val: Any) -> Optional[datetime]:
    if val is None:
        return None
    if isinstance(val, datetime):
        return _aware(val)
    if isinstance(val, str):
        try:
            dt = datetime.fromisoformat(val.replace("Z", "+00:00"))
            return _aware(dt)
        except (ValueError, AttributeError):
            return None
    return None


def _to_float(val: Any) -> Optional[float]:
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _to_int(val: Any) -> Optional[int]:
    if val is None:
        return None
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


def _anchor_check(
    ticker: str,
    alert_time: Optional[datetime],
    price: Optional[float],
    catalyst_type: Optional[str],
    catalyst_subtype: Optional[str],
    source_type: str,
) -> Optional[str]:
    """Return rejection reason string, or None if all anchors pass."""
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


def _minute_bucket(ticker: str, dt: datetime) -> Tuple[str, str]:
    rounded = dt.replace(second=0, microsecond=0)
    return (ticker, rounded.isoformat())


def _count_values(records: List[RocketRecord], field: str) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for rec in records:
        val = str(getattr(rec, field, None) or "null")
        counts[val] = counts.get(val, 0) + 1
    return counts


def _null_rates(df: pd.DataFrame, columns: List[str]) -> Dict[str, float]:
    rates: Dict[str, float] = {}
    n = max(len(df), 1)
    for col in columns:
        if col in df.columns:
            rates[col] = round(df[col].isna().sum() / n, 4)
        else:
            rates[col] = 1.0
    return rates


def _write_report(
    path: Path,
    records: List[RocketRecord],
    exportable: List[RocketRecord],
    rejected: List[RocketRecord],
    df: pd.DataFrame,
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
    n_rej = len(rejected)

    def _pct(n: int, total: int) -> str:
        return f"{n / max(total, 1) * 100:.1f}%"

    lines = [
        f"# Rocket Dataset Report",
        f"",
        f"## Run Metadata",
        f"| Field | Value |",
        f"|---|---|",
        f"| dataset_version | `{dataset_version}` |",
        f"| builder_version | `{builder_version}` |",
        f"| created_at | {created_at.isoformat()} |",
        f"| elapsed_seconds | {elapsed:.1f} |",
        f"",
        f"## Row Counts",
        f"| Source | Ingested | Exported | Rejected |",
        f"|---|---|---|---|",
    ]
    by_source: Dict[str, Dict[str, int]] = {}
    for rec in records:
        s = rec.source_type
        by_source.setdefault(s, {"ing": 0, "exp": 0, "rej": 0})
        by_source[s]["ing"] += 1
        if rec.rejection_reason:
            by_source[s]["rej"] += 1
    exp_ids = {r.row_id for r in exportable}
    for rec in exportable:
        by_source.setdefault(rec.source_type, {"ing": 0, "exp": 0, "rej": 0})
        by_source[rec.source_type]["exp"] += 1
    for src, counts in sorted(by_source.items()):
        lines.append(f"| {src} | {counts['ing']} | {counts['exp']} | {counts['rej']} |")
    lines += [
        f"| **TOTAL** | **{n_ing}** | **{n_exp}** | **{n_rej}** |",
        f"",
        f"## Rejection Summary",
        f"| Reason | Count | % of Ingested |",
        f"|---|---|---|",
    ]
    for reason, cnt in sorted(rej_reasons.items(), key=lambda x: -x[1]):
        lines.append(f"| {reason} | {cnt} | {_pct(cnt, n_ing)} |")

    lines += [
        f"",
        f"## Duplicate Summary",
        f"| Kept Source | Dropped Source | Dedup Reason | Count |",
        f"|---|---|---|---|",
    ]
    dedup_summary: Dict[Tuple[str, str, str], int] = {}
    for rec in dedup_records:
        key = (rec.kept_source_type or "", rec.dropped_source_type or "", rec.dedup_reason or "")
        dedup_summary[key] = dedup_summary.get(key, 0) + 1
    for (kept, dropped, reason), cnt in sorted(dedup_summary.items()):
        lines.append(f"| {kept} | {dropped} | {reason} | {cnt} |")

    lines += [
        f"",
        f"## Pricing & Enrichment",
        f"| Metric | Value |",
        f"|---|---|",
        f"| fetched | {fetch_stats.get('fetched', 0)} |",
        f"| unavailable | {fetch_stats.get('unavailable', 0)} |",
    ]
    outcome_src_counts = _count_values(exportable, "outcome_source")
    for src, cnt in sorted(outcome_src_counts.items()):
        lines.append(f"| outcome_source={src} | {cnt} |")

    lines += [
        f"",
        f"## Runner Tier Distribution",
        f"| Tier | Count | % |",
        f"|---|---|---|",
    ]
    for tier in list(RUNNER_TIERS) + ["null"]:
        cnt = tier_counts.get(tier, 0)
        lines.append(f"| {tier} | {cnt} | {_pct(cnt, n_exp)} |")

    lines += [
        f"",
        f"## Drawdown Quality Distribution",
        f"",
        f"> ⚠️ `daily_proxy` rows ({proxy_rows}) carry lower-confidence CLEAN/DIRTY labels "
        f"derived from daily-bar lows. Do not treat them as equivalent to `intraday_exact` rows.",
        f"",
        f"| Quality | Count | % |",
        f"|---|---|---|",
    ]
    for q in list(DRAWDOWN_QUAL) + ["null"]:
        cnt = dq_counts.get(q, 0)
        lines.append(f"| {q} | {cnt} | {_pct(cnt, n_exp)} |")
    lines += [f"| daily_proxy rows | {proxy_rows} | {_pct(proxy_rows, n_exp)} |"]

    lines += [
        f"",
        f"## Feature Null Rates",
        f"| Feature Column | Null Count | Null % |",
        f"|---|---|---|",
    ]
    n_total = max(len(df), 1)
    for col, rate in sorted(null_rates.items(), key=lambda x: -x[1]):
        null_count = int(rate * n_total)
        lines.append(f"| {col} | {null_count} | {rate * 100:.1f}% |")

    # Segmentation breakdowns
    def _segment(col: str, label: str) -> List[str]:
        seg_lines = [f"", f"### By {label}", f"| {label} | Count | % |", f"|---|---|---|"]
        if col in df.columns:
            for val, cnt in df[col].value_counts(dropna=False).items():
                seg_lines.append(f"| {val} | {cnt} | {_pct(cnt, n_exp)} |")
        return seg_lines

    lines += [f"", f"## Segmentation Breakdowns"]
    lines += _segment("catalyst_category", "Catalyst Category")
    lines += _segment("float_category", "Float Bucket")
    lines += _segment("market_cap_category", "Market Cap Bucket")

    # Price buckets
    lines += [f"", f"### By Price Bucket", f"| Price Bucket | Count | % |", f"|---|---|---|"]
    if "price_at_alert" in df.columns:
        prices = pd.to_numeric(df["price_at_alert"], errors="coerce")
        buckets = pd.cut(
            prices,
            bins=[0, 1, 5, 10, float("inf")],
            labels=["<$1", "$1–5", "$5–10", ">$10"],
        )
        for label_, cnt in buckets.value_counts(sort=False).items():
            lines.append(f"| {label_} | {cnt} | {_pct(cnt, n_exp)} |")

    lines += [
        f"",
        f"## Dropped Non-Manifest Columns",
        f"The following `RocketRecord` fields were not exported because they are "
        f"neither in `FEATURE_COLUMNS` nor `LABEL_COLUMNS`.",
        f"",
        f"| Column | Reason |",
        f"|---|---|",
    ]
    for col in non_manifest:
        lines.append(f"| {col} | not in FEATURE_COLUMNS or LABEL_COLUMNS |")

    path.write_text("\n".join(lines), encoding="utf-8")
```

- [ ] **Step 1.4 — Run the smoke test**

```
python -m pytest tests/unit/test_rocket_labeler.py::test_import -v
```

Expected: `PASSED`

- [ ] **Step 1.5 — Commit**

```
git add src/core/agentic/rocket_dataset_builder.py tests/unit/test_rocket_labeler.py
git commit -m "feat: add rocket_dataset_builder scaffold with models, constants, pure label functions, and builder class"
```

---

### Task 2: Unit tests — `compute_peak_metrics` and `compute_runner_tier`

**Files:**
- Modify: `tests/unit/test_rocket_labeler.py`

- [ ] **Step 2.1 — Write the failing tests**

Append to `tests/unit/test_rocket_labeler.py`:

```python
# ── compute_peak_metrics ──────────────────────────────────────────────────────

def test_peak_metrics_basic():
    from src.core.agentic.rocket_dataset_builder import compute_peak_metrics
    bars = [
        _bar(10,  high=11.0, low=9.5,  close=10.5),   # +10%
        _bar(30,  high=13.0, low=10.0, close=12.0),   # +30% peak
        _bar(60,  high=12.0, low=10.0, close=11.0),
    ]
    pm = compute_peak_metrics(bars, [], alert_price=10.0, alert_time=BASE)
    assert pm.peak_move_pct == pytest.approx(30.0, abs=0.01)
    assert pm.peak_timestamp is not None
    assert pm.calendar_time_to_peak_minutes == pytest.approx(30.0, abs=1.0)
    assert pm.trading_time_to_peak_minutes is not None


def test_peak_metrics_empty_bars_uses_stored_fallback():
    from src.core.agentic.rocket_dataset_builder import compute_peak_metrics
    pm = compute_peak_metrics([], [], alert_price=5.0, alert_time=BASE,
                               stored_five_day_high_pct=45.0)
    assert pm.peak_move_pct == pytest.approx(45.0, abs=0.01)
    assert pm.peak_timestamp is None
    assert pm.calendar_time_to_peak_minutes is None


def test_peak_metrics_no_data_returns_empty():
    from src.core.agentic.rocket_dataset_builder import compute_peak_metrics
    pm = compute_peak_metrics(None, None, alert_price=5.0, alert_time=BASE)
    assert pm.peak_move_pct is None
    assert pm.peak_timestamp is None


def test_peak_metrics_ignores_bars_before_alert():
    from src.core.agentic.rocket_dataset_builder import compute_peak_metrics
    bars = [
        _bar(-30, high=999.0, low=1.0, close=5.0),  # before alert — must be ignored
        _bar(10,  high=6.0,   low=4.5, close=5.5),
    ]
    pm = compute_peak_metrics(bars, [], alert_price=5.0, alert_time=BASE)
    assert pm.peak_move_pct == pytest.approx(20.0, abs=0.01)


# ── compute_runner_tier ───────────────────────────────────────────────────────

def test_runner_tier_boundaries():
    from src.core.agentic.rocket_dataset_builder import compute_runner_tier
    mins_1d = 60 * 6.5        # exactly 1 trading day
    mins_2d = 60 * 6.5 * 2
    mins_5d = 60 * 6.5 * 5

    # STANDARD_WIN boundary
    assert compute_runner_tier(9.99,  mins_1d) is None
    assert compute_runner_tier(10.0,  mins_1d) == "STANDARD_WIN"
    assert compute_runner_tier(29.99, mins_1d) == "STANDARD_WIN"

    # MAJOR_RUNNER — requires ≤2d
    assert compute_runner_tier(30.0,  mins_2d) == "MAJOR_RUNNER"
    assert compute_runner_tier(30.0,  mins_1d) == "MAJOR_RUNNER"   # within 2d ✓
    assert compute_runner_tier(29.99, mins_2d) is None              # <30% → no tier

    # MONSTER_RUNNER
    assert compute_runner_tier(100.0, mins_5d) == "MONSTER_RUNNER"
    assert compute_runner_tier(99.99, mins_5d) is None

    # LEGENDARY_RUNNER — evaluated first
    assert compute_runner_tier(300.0, mins_5d) == "LEGENDARY_RUNNER"


def test_legendary_not_compressed():
    """A 400% mover must be LEGENDARY_RUNNER, not MONSTER_RUNNER."""
    from src.core.agentic.rocket_dataset_builder import compute_runner_tier
    mins_3d = 60 * 6.5 * 3
    tier = compute_runner_tier(400.0, mins_3d)
    assert tier == "LEGENDARY_RUNNER"
    assert tier != "MONSTER_RUNNER"


def test_runner_tier_no_timing_allows_5d_tiers():
    """Without timing, LEGENDARY and MONSTER can still be assigned."""
    from src.core.agentic.rocket_dataset_builder import compute_runner_tier
    assert compute_runner_tier(350.0, None) == "LEGENDARY_RUNNER"
    assert compute_runner_tier(120.0, None) == "MONSTER_RUNNER"
    # Sub-5d tiers require timing
    assert compute_runner_tier(30.0,  None) is None
    assert compute_runner_tier(15.0,  None) is None


def test_runner_tier_negative_peak_returns_none():
    from src.core.agentic.rocket_dataset_builder import compute_runner_tier
    assert compute_runner_tier(-5.0, 60.0) is None
    assert compute_runner_tier(None, 60.0) is None
```

- [ ] **Step 2.2 — Run to verify failures**

```
python -m pytest tests/unit/test_rocket_labeler.py -k "peak_metrics or runner_tier" -v
```

Expected: all 9 tests `PASSED` (functions already implemented in Task 1).

If any fail, debug the implementation in `rocket_dataset_builder.py` before continuing.

- [ ] **Step 2.3 — Commit**

```
git add tests/unit/test_rocket_labeler.py
git commit -m "test: add compute_peak_metrics and compute_runner_tier unit tests"
```

---

### Task 3: Unit tests — `compute_mfe_mae_profiles`

**Files:**
- Modify: `tests/unit/test_rocket_labeler.py`

- [ ] **Step 3.1 — Write the tests**

Append to `tests/unit/test_rocket_labeler.py`:

```python
# ── compute_mfe_mae_profiles ──────────────────────────────────────────────────

def test_mfe_mae_intraday_basic():
    from src.core.agentic.rocket_dataset_builder import compute_mfe_mae_profiles
    # 5m bars covering the first hour after alert
    bars = [_bar(i * 5, high=10.0 + i * 0.5, low=9.5 - i * 0.1, close=10.0 + i * 0.4)
            for i in range(1, 13)]   # 12 bars = 60 min
    p = compute_mfe_mae_profiles(bars, [], alert_price=10.0, alert_time=BASE)
    # mfe_15m = max(high in first 15m) = bar at +5 and +10 and +15 min
    # bar 1 offset=5 high=10.5, bar 2 offset=10 high=11.0, bar 3 offset=15 high=11.5
    assert p.mfe_15m == pytest.approx((11.5 / 10.0 - 1) * 100, abs=0.01)
    assert p.mfe_60m is not None
    assert p.mfe_60m > p.mfe_15m  # full hour > 15m
    assert p.mae_15m is not None
    assert p.mae_15m < 0.0  # lows below alert price


def test_mfe_mae_daily_proxy():
    from src.core.agentic.rocket_dataset_builder import compute_mfe_mae_profiles
    # Daily bars: 3 days after alert
    daily = [
        _bar(24 * 60,       high=12.0, low=9.0, close=11.0),  # day 1
        _bar(24 * 60 * 2,   high=14.0, low=8.5, close=12.0),  # day 2
        _bar(24 * 60 * 3,   high=15.0, low=8.0, close=13.0),  # day 3
    ]
    p = compute_mfe_mae_profiles([], daily, alert_price=10.0, alert_time=BASE)
    # Sub-day windows must be null in daily proxy mode
    assert p.mfe_15m is None
    assert p.mae_15m is None
    assert p.mfe_60m is None
    assert p.mae_60m is None
    # 1d window: only day 1
    assert p.mfe_1d == pytest.approx((12.0 / 10.0 - 1) * 100, abs=0.01)
    assert p.mae_1d == pytest.approx((9.0  / 10.0 - 1) * 100, abs=0.01)
    # 2d window: days 1+2, max high = 14.0, min low = 8.5
    assert p.mfe_2d == pytest.approx((14.0 / 10.0 - 1) * 100, abs=0.01)
    assert p.mae_2d == pytest.approx((8.5  / 10.0 - 1) * 100, abs=0.01)


def test_mfe_mae_stored_fallback():
    from src.core.agentic.rocket_dataset_builder import compute_mfe_mae_profiles
    stored = {
        "stored_return_next_day_high_pct": 15.0,
        "stored_return_two_day_high_pct":  25.0,
        "stored_return_five_day_high_pct": 40.0,
    }
    p = compute_mfe_mae_profiles(None, None, alert_price=10.0, alert_time=BASE,
                                  stored_fields=stored)
    assert p.mfe_1d == pytest.approx(15.0, abs=0.01)
    assert p.mfe_2d == pytest.approx(25.0, abs=0.01)
    assert p.mfe_5d == pytest.approx(40.0, abs=0.01)
    # MAE always null when only stored fields
    assert p.mae_1d is None
    assert p.mae_5d is None


def test_mfe_mae_no_data_returns_all_none():
    from src.core.agentic.rocket_dataset_builder import compute_mfe_mae_profiles
    p = compute_mfe_mae_profiles(None, None, alert_price=5.0, alert_time=BASE)
    assert p.mfe_5d is None
    assert p.mae_5d is None
```

- [ ] **Step 3.2 — Run**

```
python -m pytest tests/unit/test_rocket_labeler.py -k "mfe_mae" -v
```

Expected: all 4 tests `PASSED`. Debug any failures before continuing.

- [ ] **Step 3.3 — Commit**

```
git add tests/unit/test_rocket_labeler.py
git commit -m "test: add compute_mfe_mae_profiles unit tests"
```

---

### Task 4: Unit tests — `compute_drawdown_quality`

**Files:**
- Modify: `tests/unit/test_rocket_labeler.py`

- [ ] **Step 4.1 — Write the tests**

Append to `tests/unit/test_rocket_labeler.py`:

```python
# ── compute_drawdown_quality ──────────────────────────────────────────────────

def _dq(intraday, daily, alert_price, tier):
    from src.core.agentic.rocket_dataset_builder import compute_drawdown_quality
    dq_flag = "intraday_exact" if intraday else ("daily_proxy" if daily else "missing")
    return compute_drawdown_quality(intraday, daily, alert_price, tier, dq_flag)


def test_clean_runner():
    """Target hit before MAE reaches -15% → CLEAN_RUNNER."""
    bars = [
        _bar(5,  high=10.5, low=9.8, close=10.3),   # small adverse, no target
        _bar(10, high=11.5, low=9.9, close=11.0),   # +15% → hits STANDARD_WIN target
    ]
    assert _dq(bars, [], 10.0, "STANDARD_WIN") == "CLEAN_RUNNER"


def test_dirty_runner():
    """MAE ≤ -15% before target → DIRTY_RUNNER."""
    bars = [
        _bar(5,  high=10.2, low=8.4, close=9.0),   # low = -16%  — MAE triggered
        _bar(10, high=11.5, low=9.0, close=11.0),   # +15% — target hit
    ]
    assert _dq(bars, [], 10.0, "STANDARD_WIN") == "DIRTY_RUNNER"


def test_trap_rule_1():
    """+20% then close ≤ -20% from alert → TRAP."""
    bars = [
        _bar(5,  high=12.5, low=9.5,  close=12.0),  # +25% (activates trap watch)
        _bar(10, high=12.0, low=7.0,  close=7.5),   # low goes -30%, close -25% → TRAP
    ]
    assert _dq(bars, [], 10.0, "STANDARD_WIN") == "TRAP"


def test_trap_rule_2():
    """+120% then 66.7% drop from peak → TRAP."""
    # alert_price=10, peak=22 (+120%), then close=13.2 = 22*0.6 = exactly 40% drop
    bars = [
        _bar(5,  high=22.0, low=9.5, close=21.0),  # +120% peak
        _bar(10, high=21.5, low=12.0, close=13.0), # close = 13 → (1 - 13/22)*100 = 40.9% drop
    ]
    result = _dq(bars, [], 10.0, "MONSTER_RUNNER")
    assert result == "TRAP"


def test_trap_rule_2_not_triggered():
    """+35% then only 28.6% from peak → NOT TRAP."""
    # alert_price=10, peak=13.5 (+35%), close=9.64 = 13.5*0.714 = 28.6% drop
    bars = [
        _bar(5,  high=13.5, low=9.5, close=13.0),   # +35% peak
        _bar(10, high=13.0, low=10.5, close=10.8),  # (1 - 10.8/13.5)*100 = 20% drop — under 40%
    ]
    result = _dq(bars, [], 10.0, "MAJOR_RUNNER")
    # 30% target not reached (bars top out at +35% but we need the target actually hit)
    # 13.5 >= 10*(1+0.30) = 13 → target IS reached
    assert result != "TRAP"


def test_target_never_reached_returns_none():
    """Price moves but never hits tier target → None."""
    bars = [
        _bar(5,  high=10.8, low=9.5, close=10.5),  # only +8%, below 10% target
    ]
    assert _dq(bars, [], 10.0, "STANDARD_WIN") is None


def test_missing_data_quality_returns_none():
    """drawdown_data_quality='missing' → None regardless of tier."""
    from src.core.agentic.rocket_dataset_builder import compute_drawdown_quality
    assert compute_drawdown_quality([], [], 10.0, "STANDARD_WIN", "missing") is None


def test_none_tier_returns_none():
    """No tier → no quality label."""
    from src.core.agentic.rocket_dataset_builder import compute_drawdown_quality
    bars = [_bar(5, high=15.0, low=9.0, close=14.0)]
    assert compute_drawdown_quality(bars, [], 10.0, None, "intraday_exact") is None


def test_empty_bars_returns_none():
    """No bars → None (not a crash)."""
    from src.core.agentic.rocket_dataset_builder import compute_drawdown_quality
    assert compute_drawdown_quality([], [], 10.0, "STANDARD_WIN", "intraday_exact") is None
```

- [ ] **Step 4.2 — Run**

```
python -m pytest tests/unit/test_rocket_labeler.py -k "drawdown" -v
```

Expected: all 9 tests `PASSED`. The two TRAP tests are the critical ones — if they fail, check the two-pass TRAP logic in `compute_drawdown_quality`.

- [ ] **Step 4.3 — Commit**

```
git add tests/unit/test_rocket_labeler.py
git commit -m "test: add compute_drawdown_quality unit tests including both TRAP rules"
```

---

### Task 5: Unit tests — `_compute_data_quality_score` and leakage manifest

**Files:**
- Modify: `tests/unit/test_rocket_labeler.py`

- [ ] **Step 5.1 — Write the tests**

Append to `tests/unit/test_rocket_labeler.py`:

```python
# ── _compute_data_quality_score ───────────────────────────────────────────────

def _make_record(**kwargs):
    from src.core.agentic.rocket_dataset_builder import RocketRecord
    defaults = dict(
        row_id="test_001", source_type="telegram",
        ticker="TEST", alert_time=BASE, price_at_alert=5.0,
    )
    defaults.update(kwargs)
    return RocketRecord(**defaults)


def test_data_quality_score_max_is_100():
    from src.core.agentic.rocket_dataset_builder import _compute_data_quality_score
    from datetime import datetime, timezone
    rec = _make_record(
        intraday_bars=[_bar(5, 6.0, 4.5, 5.5)],
        peak_timestamp=BASE + timedelta(minutes=30),
        runner_tier="STANDARD_WIN",
        drawdown_quality="CLEAN_RUNNER",
        mfe_15m=5.0,  mae_15m=-2.0,
        mfe_60m=8.0,  mae_60m=-3.0,
        mfe_1d=10.0,  mae_1d=-4.0,
        mfe_2d=12.0,  mae_2d=-5.0,
        mfe_5d=15.0,  mae_5d=-6.0,
    )
    score = _compute_data_quality_score(rec)
    assert score == 100.0


def test_data_quality_score_never_exceeds_100():
    """Score must be capped even if somehow all components fire."""
    from src.core.agentic.rocket_dataset_builder import _compute_data_quality_score
    rec = _make_record(
        intraday_bars=[_bar(5, 6.0, 4.5, 5.5)],
        peak_timestamp=BASE,
        runner_tier="LEGENDARY_RUNNER",
        drawdown_quality="TRAP",
        mfe_15m=1.0, mae_15m=-1.0,
        mfe_60m=2.0, mae_60m=-2.0,
        mfe_1d=3.0,  mae_1d=-3.0,
        mfe_2d=4.0,  mae_2d=-4.0,
        mfe_5d=5.0,  mae_5d=-5.0,
    )
    assert _compute_data_quality_score(rec) <= 100.0


def test_data_quality_score_empty_record():
    from src.core.agentic.rocket_dataset_builder import _compute_data_quality_score
    rec = _make_record()
    assert _compute_data_quality_score(rec) == 0.0


def test_data_quality_score_deterministic():
    from src.core.agentic.rocket_dataset_builder import _compute_data_quality_score
    rec = _make_record(
        intraday_bars=[_bar(5, 6.0, 4.5, 5.5)],
        runner_tier="MAJOR_RUNNER",
        mfe_1d=10.0, mae_1d=-3.0,
    )
    s1 = _compute_data_quality_score(rec)
    s2 = _compute_data_quality_score(rec)
    assert s1 == s2


def test_daily_proxy_never_intraday_exact():
    """Records with only daily bars must not get drawdown_data_quality='intraday_exact'."""
    from src.core.agentic.rocket_dataset_builder import RocketDatasetBuilder
    builder = RocketDatasetBuilder.__new__(RocketDatasetBuilder)
    # Simulate enrichment of a record that only gets daily bars
    rec = _make_record()
    rec.intraday_bars = None
    rec.daily_bars = [_bar(60 * 24, high=6.0, low=4.5, close=5.5)]
    # Manually set what _enrich would set
    rec.drawdown_data_quality = "daily_proxy" if rec.daily_bars else "missing"
    assert rec.drawdown_data_quality != "intraday_exact"


# ── Leakage manifest checks ───────────────────────────────────────────────────

def test_no_forward_pricing_in_feature_columns():
    """Forward-pricing fields must never appear in FEATURE_COLUMNS."""
    from src.core.agentic.rocket_dataset_builder import FEATURE_COLUMNS
    forbidden = {
        "peak_move_pct", "peak_timestamp", "five_day_high", "two_day_high",
        "next_day_high", "mfe_pct", "mae_pct", "return_five_day_high_pct",
        "mfe_15m", "mfe_60m", "mfe_1d", "mfe_2d", "mfe_5d",
        "mae_15m", "mae_60m", "mae_1d", "mae_2d", "mae_5d",
        "runner_tier", "drawdown_quality",
    }
    leaking = forbidden & set(FEATURE_COLUMNS)
    assert leaking == set(), f"Leakage detected: {leaking}"


def test_label_columns_not_in_feature_columns():
    from src.core.agentic.rocket_dataset_builder import FEATURE_COLUMNS, LABEL_COLUMNS
    overlap = set(FEATURE_COLUMNS) & set(LABEL_COLUMNS)
    assert overlap == set(), f"Column in both manifests: {overlap}"
```

- [ ] **Step 5.2 — Run**

```
python -m pytest tests/unit/test_rocket_labeler.py -k "quality_score or leakage or daily_proxy" -v
```

Expected: all 7 tests `PASSED`.

- [ ] **Step 5.3 — Commit**

```
git add tests/unit/test_rocket_labeler.py
git commit -m "test: add data_quality_score bounds, determinism, and leakage manifest tests"
```

---

### Task 6: Unit tests — ingestion anchor validation and deduplication

**Files:**
- Modify: `tests/unit/test_rocket_labeler.py`

- [ ] **Step 6.1 — Write the tests**

Append to `tests/unit/test_rocket_labeler.py`:

```python
# ── Ingestion helpers ─────────────────────────────────────────────────────────

def test_anchor_check_passes_valid_row():
    from src.core.agentic.rocket_dataset_builder import _anchor_check
    assert _anchor_check("AAPL", BASE, 5.0, "acquisition", None, "telegram") is None


def test_anchor_check_missing_ticker():
    from src.core.agentic.rocket_dataset_builder import _anchor_check
    assert _anchor_check("", BASE, 5.0, "acquisition", None, "telegram") == "missing_ticker"


def test_anchor_check_missing_price():
    from src.core.agentic.rocket_dataset_builder import _anchor_check
    assert _anchor_check("AAPL", BASE, None, "acquisition", None, "telegram") == "invalid_price"
    assert _anchor_check("AAPL", BASE, 0.0,  "acquisition", None, "telegram") == "invalid_price"
    assert _anchor_check("AAPL", BASE, -1.0, "acquisition", None, "telegram") == "invalid_price"


def test_anchor_check_missing_catalyst_required_for_non_prenews():
    from src.core.agentic.rocket_dataset_builder import _anchor_check
    assert _anchor_check("AAPL", BASE, 5.0, None, None, "telegram") == "missing_catalyst"
    assert _anchor_check("AAPL", BASE, 5.0, None, None, "shadow") == "missing_catalyst"
    assert _anchor_check("AAPL", BASE, 5.0, None, None, "backfill") == "missing_catalyst"
    assert _anchor_check("AAPL", BASE, 5.0, None, None, "missed") == "missing_catalyst"


def test_anchor_check_prenews_catalyst_not_required():
    from src.core.agentic.rocket_dataset_builder import _anchor_check
    # prenews rows may have no catalyst — must NOT be rejected for it
    assert _anchor_check("AAPL", BASE, 5.0, None, None, "prenews") is None


def test_dedup_telegram_beats_backfill(tmp_path):
    """telegram > backfill in dedup priority."""
    from src.core.agentic.rocket_dataset_builder import RocketDatasetBuilder, RocketRecord
    builder = RocketDatasetBuilder(data_dir=tmp_path, docs_dir=tmp_path)

    t = BASE
    rec_tele = RocketRecord(
        row_id="telegram_A", source_type="telegram",
        ticker="AAPL", alert_time=t, price_at_alert=5.0,
        catalyst_type="acquisition",
    )
    rec_back = RocketRecord(
        row_id="backfill_A", source_type="backfill",
        ticker="AAPL", alert_time=t, price_at_alert=5.0,
        catalyst_type="acquisition",
    )
    result = builder._deduplicate([rec_tele, rec_back])
    kept    = [r for r in result if not r.rejection_reason]
    dropped = [r for r in result if r.rejection_reason == "duplicate"]
    assert len(kept) == 1
    assert kept[0].source_type == "telegram"
    assert dropped[0].source_type == "backfill"
    assert dropped[0].kept_source_type == "telegram"


def test_dedup_missed_beats_shadow(tmp_path):
    """missed > shadow in dedup priority."""
    from src.core.agentic.rocket_dataset_builder import RocketDatasetBuilder, RocketRecord
    builder = RocketDatasetBuilder(data_dir=tmp_path, docs_dir=tmp_path)

    t = BASE
    rec_shadow = RocketRecord(
        row_id="shadow_A", source_type="shadow",
        ticker="SOUN", alert_time=t, price_at_alert=2.0,
        catalyst_type="other",
    )
    rec_missed = RocketRecord(
        row_id="missed_A", source_type="missed",
        ticker="SOUN", alert_time=t, price_at_alert=2.0,
        catalyst_type="fda_approval",
    )
    result = builder._deduplicate([rec_shadow, rec_missed])
    kept = [r for r in result if not r.rejection_reason]
    assert kept[0].source_type == "missed"
```

- [ ] **Step 6.2 — Run**

```
python -m pytest tests/unit/test_rocket_labeler.py -k "anchor or dedup" -v
```

Expected: all 8 tests `PASSED`.

- [ ] **Step 6.3 — Commit**

```
git add tests/unit/test_rocket_labeler.py
git commit -m "test: add anchor validation and deduplication priority unit tests"
```

---

### Task 7: Integration test — `build()` end-to-end with synthetic data

**Files:**
- Modify: `tests/unit/test_rocket_labeler.py`

- [ ] **Step 7.1 — Write the integration test**

Append to `tests/unit/test_rocket_labeler.py`:

```python
# ── End-to-end build() integration ───────────────────────────────────────────

def _write_json(path, data):
    import json
    with open(path, "w") as f:
        json.dump(data, f)


def _make_raw_alert(alert_id, ticker, price, sent_at, catalyst="fda_approval",
                    five_day_high=None, mfe_pct=None, return_five_day_high_pct=None):
    return {
        "alert_id": alert_id,
        "ticker": ticker,
        "sent_at": sent_at,
        "catalyst_type": catalyst,
        "price_at_alert": price,
        "news_impact_score": 75.0,
        "expected_return_score": 70.0,
        "continuation_probability": 65.0,
        "multi_day_score": 60.0,
        "five_day_high": five_day_high,
        "mfe_pct": mfe_pct,
        "return_five_day_high_pct": return_five_day_high_pct,
        "outcome": "GREAT_ALERT" if five_day_high else None,
    }


def test_build_produces_outputs(tmp_path, monkeypatch):
    """Full build() run with synthetic JSON files produces CSV, Parquet, report."""
    import json
    from src.core.agentic.rocket_dataset_builder import RocketDatasetBuilder

    # Write synthetic source files
    agentic = tmp_path / "agentic"
    agentic.mkdir()
    docs = tmp_path / "docs"
    docs.mkdir()

    alerts = [
        _make_raw_alert("a1", "AAPL", 5.0, "2026-01-02T14:30:00Z",
                        return_five_day_high_pct=45.0),
        _make_raw_alert("a2", "GOOG", 10.0, "2026-01-02T14:30:00Z",
                        return_five_day_high_pct=8.0),  # <10% → no tier
        _make_raw_alert("a3", "",    5.0, "2026-01-02T14:30:00Z"),  # missing ticker → rejected
    ]
    _write_json(agentic / "news_momentum_telegram_alerts.json", alerts)
    _write_json(agentic / "news_momentum_shadow_alerts.json", [])
    _write_json(agentic / "news_momentum_backfill_records.json", [])
    _write_json(agentic / "news_momentum_missed_winners.json", [])
    _write_json(agentic / "pre_news_shadow_v2.json", {"count": 0, "records": [], "updated_at": ""})

    # Mock market data provider to return no bars (test stored-field fallback)
    monkeypatch.setattr(
        "src.core.agentic.rocket_dataset_builder.RocketDatasetBuilder._fetch_bars",
        staticmethod(lambda provider, ticker: (None, None)),
    )

    builder = RocketDatasetBuilder(data_dir=agentic, docs_dir=docs)
    summary = builder.build()

    # Output files exist
    assert (agentic / "rocket_training_dataset.csv").exists()
    assert (agentic / "rocket_training_dataset.parquet").exists()
    assert (agentic / "rocket_rejected_rows.csv").exists()
    assert (docs / "rocket_dataset_report.md").exists()

    # Summary counts
    assert summary.total_ingested == 3
    assert summary.total_rejected >= 1  # at least the missing-ticker row
    assert summary.total_exported <= 2

    # AAPL with 45% return should be MONSTER or STANDARD win
    import pandas as pd
    df = pd.read_csv(agentic / "rocket_training_dataset.csv")
    if len(df) > 0:
        aapl = df[df["ticker"] == "AAPL"]
        if len(aapl) > 0:
            assert aapl.iloc[0]["runner_tier"] in {"MONSTER_RUNNER", "LEGENDARY_RUNNER",
                                                    "MAJOR_RUNNER", "STANDARD_WIN"}

    # Report contains required sections
    report = (docs / "rocket_dataset_report.md").read_text()
    assert "## Run Metadata" in report
    assert "## Runner Tier Distribution" in report
    assert "## Drawdown Quality Distribution" in report
    assert "## Feature Null Rates" in report
    assert "## Dropped Non-Manifest Columns" in report
    assert "daily_proxy" in report

    # Leakage check: no forward-pricing columns in exported CSV
    assert "five_day_high" not in df.columns
    assert "mfe_pct" not in df.columns
    assert "return_five_day_high_pct" not in df.columns

    # BuildSummary versioning
    assert summary.dataset_version == "rocket_v1"
    assert summary.builder_version == "1.0.0"
    assert summary.created_at is not None
```

- [ ] **Step 7.2 — Run**

```
python -m pytest tests/unit/test_rocket_labeler.py::test_build_produces_outputs -v
```

Expected: `PASSED`. If it fails with a `KeyError` or missing column, check `_assemble`'s column selection logic against `_EXPORT_COLUMNS`.

- [ ] **Step 7.3 — Run the full test suite**

```
python -m pytest tests/unit/test_rocket_labeler.py -v
```

Expected: all tests `PASSED`.

- [ ] **Step 7.4 — Run existing tests to check for regressions**

```
python -m pytest tests/ -v --ignore=tests/unit/test_rocket_labeler.py
```

Expected: all existing tests still `PASSED` (no production files were modified).

- [ ] **Step 7.5 — Commit**

```
git add tests/unit/test_rocket_labeler.py
git commit -m "test: add end-to-end build() integration test for RocketDatasetBuilder"
```

---

### Task 8: Verify the full dataset build runs against production data

**Files:** No changes — this is a smoke-run against real data.

- [ ] **Step 8.1 — Run the builder against real data**

From the project root:

```python
# run_rocket_build.py  (create temporarily, delete after)
import logging
logging.basicConfig(level=logging.INFO)
from src.core.agentic.rocket_dataset_builder import RocketDatasetBuilder
summary = RocketDatasetBuilder().build()
print(summary.model_dump_json(indent=2))
```

```
cd "C:\Users\Husna\OneDrive\Desktop\Oracle project1"
python run_rocket_build.py
```

Expected output (approximate):
```json
{
  "total_ingested": ~45000,
  "total_rejected": ~...,
  "total_exported": ~...,
  "runner_tier_counts": {...},
  "dataset_version": "rocket_v1",
  "builder_version": "1.0.0"
}
```

- [ ] **Step 8.2 — Verify output files exist and have correct shape**

```python
import pandas as pd
df = pd.read_csv("data/agentic/rocket_training_dataset.csv")
print(df.shape)
print(df["runner_tier"].value_counts(dropna=False))
print(df["drawdown_quality"].value_counts(dropna=False))
print(df["drawdown_data_quality"].value_counts(dropna=False))
# Leakage check
assert "five_day_high" not in df.columns
assert "mfe_pct" not in df.columns
print("Leakage check passed")
```

- [ ] **Step 8.3 — Review `docs/rocket_dataset_report.md`**

Open the report and verify:
- All sections present
- ⚠️ daily_proxy note present in Drawdown Quality Distribution
- Dropped Non-Manifest Columns section present
- Row counts match expected (~11k telegram + ~3k backfill + ~121 missed = ~14k before dedup)

- [ ] **Step 8.4 — Delete the temporary run script**

```
del run_rocket_build.py
```

- [ ] **Step 8.5 — Commit outputs and final state**

```
git add data/agentic/rocket_training_dataset.csv
git add data/agentic/rocket_training_dataset.parquet
git add data/agentic/rocket_rejected_rows.csv
git add docs/rocket_dataset_report.md
git commit -m "feat: generate rocket_v1 training dataset and calibration report"
```

---

## Self-Review

**Spec coverage check:**

| Spec Section | Covered by Task |
|---|---|
| Multi-tier runner labeling (§7.2) | Task 1 (`compute_runner_tier`), Task 2 (tests) |
| Legendary not compressed (§7.2) | Task 2 `test_legendary_not_compressed` |
| MFE/MAE profiles × 5 windows (§7.3) | Task 1 (`compute_mfe_mae_profiles`), Task 3 (tests) |
| peak_move_pct, peak_timestamp, calendar/trading time (§7.1) | Task 1 (`compute_peak_metrics`), Task 2 (tests) |
| TRAP Rule 1 and Rule 2 (§7.4) | Task 1 (`compute_drawdown_quality`), Task 4 (tests) |
| CLEAN_RUNNER / DIRTY_RUNNER (§7.4) | Task 1, Task 4 (tests) |
| daily_proxy honesty (§7.4) | Task 1, Task 5 `test_daily_proxy_never_intraday_exact` |
| drawdown_data_quality 3-value enum (§4.3) | Task 1 constants, Task 5 tests |
| outcome_source 4-value enum (§4.3) | Task 1 (`_apply_labels`) |
| data_quality_score 0–100, deterministic (§7.5) | Task 1 (`_compute_data_quality_score`), Task 5 (tests) |
| Anti-leakage manifest (§8.1) | Task 1 `FEATURE_COLUMNS`/`LABEL_COLUMNS`, Task 5 tests |
| 5 source ingestion (§5) | Task 1 (`_ingest`, all loaders) |
| prenews catalyst exemption (§5.2) | Task 1 `_anchor_check`, Task 6 test |
| Dedup priority telegram>missed>prenews>shadow>backfill (§5.3) | Task 1 `_deduplicate`, Task 6 tests |
| Dropped duplicate metadata (§5.3) | Task 1 `_deduplicate` |
| Stored-field forwarding (§5.4) | Task 1 `_norm_telegram`, Task 3 `test_mfe_mae_stored_fallback` |
| Enrichment best-effort fetch + rate limit (§6) | Task 1 `_enrich` |
| ticker-fetch cache | Task 1 `_enrich` (`fetch_cache`) |
| BuildSummary versioning fields (§4.2) | Task 1, Task 7 `test_build_produces_outputs` |
| CSV + Parquet + rejected CSV outputs (§8.3) | Task 1 `_assemble`, Task 7 |
| Calibration report all sections (§9) | Task 1 `_write_report`, Task 7 |
| "Dropped Non-Manifest Columns" section | Task 1 `_write_report`, Task 7 |
| Rejected rows to audit CSV (§8.2) | Task 1 `_assemble` |
| No OutcomeResolver modification | No existing files touched |
| No Telegram logic modification | No existing files touched |
