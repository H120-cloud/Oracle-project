"""
Pre-News Anomaly Detector — Baseline Capture & Tracking

Captures baseline snapshots from the same scan universe for A/B comparison
against detector alerts. Baselines prove whether the Pre-News Detector
outperforms simple strategies (top gainers, raw RVOL, breakout-only,
random same-universe, and quiet volume without full V3 filters).

Usage:
    tracker = PreNewsBaselineTracker()
    tracker.record_baseline(ticker, baseline_type, raw_metrics)
    tracker.update_forward_for_ticker(ticker, current_price, current_time, vwap)
    tracker.finalize_all_eod(force=False)

Baseline types:
  - TOP_GAINERS_BASELINE
  - HIGH_RVOL_BASELINE
  - BREAKOUT_ONLY_BASELINE
  - RANDOM_SAME_UNIVERSE_BASELINE
  - QUIET_VOLUME_BASELINE
"""

from __future__ import annotations

import csv
import json
import logging
import random
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from src.utils.atomic_json import save_json_file, load_json_file

from pydantic import BaseModel, Field

from src.core.agentic.pre_news_models import (
    DataQuality,
    NewsStatus,
    PreNewsAnomaly,
)

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════════
#  PATHS
# ═══════════════════════════════════════════════════════════════════════════════

from src.utils.data_paths import AGENTIC_DATA_DIR as BASE_DIR
BASELINE_SNAPSHOTS_FILE = BASE_DIR / "pre_news_baseline_snapshots.json"
REPORTS_DIR = BASE_DIR / "evaluation_reports"


def _ensure_dir():
    BASE_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)


# ═══════════════════════════════════════════════════════════════════════════════
#  DATA MODELS
# ═══════════════════════════════════════════════════════════════════════════════


class BaselineType(str):
    TOP_GAINERS = "TOP_GAINERS_BASELINE"
    HIGH_RVOL = "HIGH_RVOL_BASELINE"
    BREAKOUT_ONLY = "BREAKOUT_ONLY_BASELINE"
    RANDOM_SAME_UNIVERSE = "RANDOM_SAME_UNIVERSE_BASELINE"
    QUIET_VOLUME = "QUIET_VOLUME_BASELINE"


class PreNewsBaselineSnapshot(BaseModel):
    """Immutable snapshot of a baseline ticker at scan time."""

    # Identity
    baseline_id: str = Field(default_factory=lambda: f"BL_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{random.randint(1000,9999)}")
    baseline_type: str
    ticker: str
    scan_time: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    session_date: str = Field(default_factory=lambda: datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    scan_source: str = ""

    # Price at scan
    price_at_scan: float = 0.0
    open_price: Optional[float] = None
    previous_close: Optional[float] = None
    day_high_at_scan: Optional[float] = None
    day_low_at_scan: Optional[float] = None
    vwap_at_scan: Optional[float] = None
    vwap_distance: float = 0.0
    price_change_pct: float = 0.0
    price_change_from_open_pct: float = 0.0

    # Volume at scan
    current_volume: Optional[float] = None
    average_volume: Optional[float] = None
    relative_volume: Optional[float] = None
    time_of_day_rvol: Optional[float] = None
    intraday_volume_curve_deviation: Optional[float] = None
    current_5m_volume_zscore: Optional[float] = None
    volume_acceleration_score: float = 0.0

    # Tape / structure
    latest_5candle_summary: str = ""
    buying_pressure: float = 0.0
    selling_pressure: float = 0.0
    upper_wick_pct: float = 0.0
    absorption_quality_score: float = 0.0

    # News / risk
    news_status: str = ""
    catalyst_age_bucket: str = ""
    offering_risk_score: float = 0.0
    market_cap: Optional[float] = None
    float_shares: Optional[float] = None

    # Forward tracking (updated after scan)
    max_price_30m: Optional[float] = None
    max_price_1h: Optional[float] = None
    max_price_2h: Optional[float] = None
    max_price_same_day: Optional[float] = None
    min_price_after_scan: Optional[float] = None
    drawdown_before_max_move_pct: Optional[float] = None
    efficiency_ratio: Optional[float] = None
    first_vwap_loss_time: Optional[datetime] = None
    vwap_hold_after_scan: Optional[bool] = None
    final_baseline_outcome_label: str = "unresolved"
    outcome_notes: list[str] = Field(default_factory=list)

    # Computed move fields
    max_move_30m_pct: Optional[float] = None
    max_move_1h_pct: Optional[float] = None
    max_move_2h_pct: Optional[float] = None
    max_move_same_day_pct: Optional[float] = None

    recorded_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def model_dump(self, **kwargs):
        data = super().model_dump(**kwargs)
        for key in list(data.keys()):
            if isinstance(data[key], datetime):
                data[key] = data[key].isoformat()
        return data


# ═══════════════════════════════════════════════════════════════════════════════
#  OUTCOME HELPERS (mirrors evaluator logic for baselines)
# ═══════════════════════════════════════════════════════════════════════════════


def _calculate_max_move_percentages(snap: PreNewsBaselineSnapshot):
    """Compute % moves from scan price to forward max prices."""
    price = snap.price_at_scan
    if price <= 0:
        return
    field_map = {
        "max_price_30m": "max_move_30m_pct",
        "max_price_1h": "max_move_1h_pct",
        "max_price_2h": "max_move_2h_pct",
        "max_price_same_day": "max_move_same_day_pct",
    }
    for src_attr, dest_attr in field_map.items():
        val = getattr(snap, src_attr)
        if val is not None and val > 0:
            pct = round((val - price) / price * 100, 2)
            setattr(snap, dest_attr, pct)


def _calculate_drawdown(snap: PreNewsBaselineSnapshot):
    """Compute drawdown before max move."""
    price = snap.price_at_scan
    max_price = snap.max_price_same_day or snap.max_price_2h or snap.max_price_1h or snap.max_price_30m
    min_price = snap.min_price_after_scan
    if price and max_price and min_price and max_price > min_price:
        dd = round((price - min_price) / price * 100, 2)
        snap.drawdown_before_max_move_pct = dd
    else:
        snap.drawdown_before_max_move_pct = 0.0


def _calculate_efficiency(snap: PreNewsBaselineSnapshot):
    """Efficiency = max_move_1h_pct / max(1, drawdown_before_max_move_pct)."""
    move = snap.max_move_1h_pct or 0.0
    dd = snap.drawdown_before_max_move_pct or 0.0
    if dd <= 0:
        snap.efficiency_ratio = round(move, 2) if move > 0 else 0.0
    else:
        snap.efficiency_ratio = round(move / max(dd, 1.0), 2)


def _finalize_outcome(snap: PreNewsBaselineSnapshot):
    """Label baseline outcome based on forward metrics."""
    m1h = snap.max_move_1h_pct or 0.0
    m2h = snap.max_move_2h_pct or 0.0
    dd = snap.drawdown_before_max_move_pct or 0.0
    eff = snap.efficiency_ratio or 0.0
    vwap_held = snap.vwap_hold_after_scan

    if m2h >= 10.0 and dd <= 5.0 and eff >= 2.0 and vwap_held:
        snap.final_baseline_outcome_label = "clean_baseline_winner"
    elif m1h >= 5.0:
        snap.final_baseline_outcome_label = "baseline_moved_up"
    elif m1h < 3.0 and dd > 5.0:
        snap.final_baseline_outcome_label = "baseline_failed"
    else:
        snap.final_baseline_outcome_label = "baseline_no_follow_through"


# ═══════════════════════════════════════════════════════════════════════════════
#  TRACKER
# ═══════════════════════════════════════════════════════════════════════════════


class PreNewsBaselineTracker:
    """Manages baseline snapshots, forward tracking, and daily exports."""

    def __init__(self):
        self._snapshots: dict[str, PreNewsBaselineSnapshot] = {}
        self._ticker_index: dict[str, list[str]] = {}
        _ensure_dir()
        self._load_state()

    # ── Persistence ───────────────────────────────────────────────────────

    def _load_state(self):
        raw = load_json_file(BASELINE_SNAPSHOTS_FILE, default=None)
        if raw is None:
            return
        for bid, d in raw.items():
            try:
                for key in ("scan_time", "first_vwap_loss_time", "recorded_at", "last_updated_at"):
                    if d.get(key):
                        try:
                            d[key] = datetime.fromisoformat(d[key])
                        except Exception:
                            pass
                snap = PreNewsBaselineSnapshot(**d)
                self._snapshots[bid] = snap
                self._ticker_index.setdefault(snap.ticker, []).append(bid)
            except Exception:
                pass
        logger.info("PreNewsBaselineTracker: loaded %d snapshots", len(self._snapshots))

    def _persist_state(self):
        data = {bid: s.model_dump() for bid, s in self._snapshots.items()}
        save_json_file(BASELINE_SNAPSHOTS_FILE, data)

    # ── Recording ─────────────────────────────────────────────────────────

    def record_baseline(
        self,
        baseline_type: str,
        ticker: str,
        scan_time: Optional[datetime] = None,
        session_date: Optional[str] = None,
        scan_source: str = "",
        price_at_scan: float = 0.0,
        open_price: Optional[float] = None,
        previous_close: Optional[float] = None,
        day_high_at_scan: Optional[float] = None,
        day_low_at_scan: Optional[float] = None,
        vwap_at_scan: Optional[float] = None,
        vwap_distance: float = 0.0,
        price_change_pct: float = 0.0,
        price_change_from_open_pct: float = 0.0,
        current_volume: Optional[float] = None,
        average_volume: Optional[float] = None,
        relative_volume: Optional[float] = None,
        time_of_day_rvol: Optional[float] = None,
        intraday_volume_curve_deviation: Optional[float] = None,
        current_5m_volume_zscore: Optional[float] = None,
        volume_acceleration_score: float = 0.0,
        latest_5candle_summary: str = "",
        buying_pressure: float = 0.0,
        selling_pressure: float = 0.0,
        upper_wick_pct: float = 0.0,
        absorption_quality_score: float = 0.0,
        news_status: str = "",
        catalyst_age_bucket: str = "",
        offering_risk_score: float = 0.0,
        market_cap: Optional[float] = None,
        float_shares: Optional[float] = None,
    ) -> PreNewsBaselineSnapshot:
        """Record a new baseline snapshot."""
        now = datetime.now(timezone.utc)
        snap = PreNewsBaselineSnapshot(
            baseline_type=baseline_type,
            ticker=ticker.upper(),
            scan_time=scan_time or now,
            session_date=session_date or now.strftime("%Y-%m-%d"),
            scan_source=scan_source,
            price_at_scan=price_at_scan,
            open_price=open_price,
            previous_close=previous_close,
            day_high_at_scan=day_high_at_scan,
            day_low_at_scan=day_low_at_scan,
            vwap_at_scan=vwap_at_scan,
            vwap_distance=vwap_distance,
            price_change_pct=price_change_pct,
            price_change_from_open_pct=price_change_from_open_pct,
            current_volume=current_volume,
            average_volume=average_volume,
            relative_volume=relative_volume,
            time_of_day_rvol=time_of_day_rvol,
            intraday_volume_curve_deviation=intraday_volume_curve_deviation,
            current_5m_volume_zscore=current_5m_volume_zscore,
            volume_acceleration_score=volume_acceleration_score,
            latest_5candle_summary=latest_5candle_summary,
            buying_pressure=buying_pressure,
            selling_pressure=selling_pressure,
            upper_wick_pct=upper_wick_pct,
            absorption_quality_score=absorption_quality_score,
            news_status=news_status,
            catalyst_age_bucket=catalyst_age_bucket,
            offering_risk_score=offering_risk_score,
            market_cap=market_cap,
            float_shares=float_shares,
        )
        self._snapshots[snap.baseline_id] = snap
        self._ticker_index.setdefault(snap.ticker, []).append(snap.baseline_id)
        self._persist_state()
        logger.debug("PreNewsBaselineTracker: recorded %s for %s", baseline_type, ticker)
        return snap

    def record_from_detector_anomaly(self, anomaly: PreNewsAnomaly, baseline_type: str) -> PreNewsBaselineSnapshot:
        """Record a baseline snapshot from an existing detector anomaly (for cross-type baselines)."""
        return self.record_baseline(
            baseline_type=baseline_type,
            ticker=anomaly.ticker,
            scan_time=anomaly.detected_at,
            session_date=(anomaly.detected_at.strftime("%Y-%m-%d") if anomaly.detected_at else None),
            scan_source=anomaly.discovery_source or "",
            price_at_scan=anomaly.price or 0.0,
            open_price=getattr(anomaly, "open_price", None),
            previous_close=getattr(anomaly, "previous_close", None),
            day_high_at_scan=getattr(anomaly, "day_high", None),
            day_low_at_scan=getattr(anomaly, "day_low", None),
            vwap_at_scan=getattr(anomaly, "vwap", None),
            vwap_distance=getattr(anomaly, "vwap_distance_pct", 0.0),
            price_change_pct=getattr(anomaly, "price_change_pct", 0.0),
            price_change_from_open_pct=getattr(anomaly, "price_change_from_open_pct", 0.0),
            current_volume=getattr(anomaly, "current_volume", None),
            average_volume=getattr(anomaly, "average_volume", None),
            relative_volume=getattr(anomaly, "relative_volume", None),
            time_of_day_rvol=getattr(anomaly, "time_of_day_rvol", None),
            volume_acceleration_score=getattr(anomaly, "volume_acceleration_score", 0.0),
            latest_5candle_summary=getattr(anomaly, "latest_5candle_summary", ""),
            buying_pressure=getattr(anomaly, "buy_pressure_score", 0.0),
            selling_pressure=getattr(anomaly, "sell_pressure_score", 0.0),
            upper_wick_pct=getattr(anomaly, "upper_wick_pct", 0.0),
            absorption_quality_score=getattr(anomaly, "absorption_quality_score", 0.0),
            news_status=(anomaly.news_status.value if anomaly.news_status else ""),
            catalyst_age_bucket=(anomaly.catalyst_age_bucket.value if anomaly.catalyst_age_bucket else ""),
            offering_risk_score=getattr(anomaly, "offering_risk_score", 0.0),
            market_cap=getattr(anomaly, "market_cap", None),
            float_shares=getattr(anomaly, "float_shares", None),
        )

    # ── Forward Tracking ──────────────────────────────────────────────────

    def update_forward_for_ticker(self, ticker: str, current_price: float, current_time: datetime, vwap: Optional[float] = None):
        """Update all active (unresolved) baseline snapshots for this ticker."""
        updated = 0
        for bid in self._ticker_index.get(ticker.upper(), []):
            snap = self._snapshots.get(bid)
            if not snap or snap.final_baseline_outcome_label != "unresolved":
                continue
            elapsed = (current_time - snap.scan_time).total_seconds() / 60.0
            if snap.max_price_30m is None or current_price > snap.max_price_30m:
                snap.max_price_30m = current_price
            if elapsed <= 30 and (snap.max_price_30m is None or current_price > snap.max_price_30m):
                snap.max_price_30m = current_price
            if elapsed <= 60 and (snap.max_price_1h is None or current_price > snap.max_price_1h):
                snap.max_price_1h = current_price
            if elapsed <= 120 and (snap.max_price_2h is None or current_price > snap.max_price_2h):
                snap.max_price_2h = current_price
            if snap.max_price_same_day is None or current_price > snap.max_price_same_day:
                snap.max_price_same_day = current_price
            if snap.min_price_after_scan is None or current_price < snap.min_price_after_scan:
                snap.min_price_after_scan = current_price
            if vwap is not None and vwap > 0:
                if current_price < vwap:
                    if snap.first_vwap_loss_time is None:
                        snap.first_vwap_loss_time = current_time
                    snap.vwap_hold_after_scan = False
                elif snap.vwap_hold_after_scan is None:
                    snap.vwap_hold_after_scan = True
            snap.last_updated_at = current_time
            updated += 1
        if updated:
            self._persist_state()

    def finalize_all_eod(self, force: bool = False):
        """Finalize outcome labels for all baseline snapshots. Call at EOD."""
        finalized = 0
        for snap in self._snapshots.values():
            if snap.final_baseline_outcome_label == "unresolved" or force:
                _calculate_max_move_percentages(snap)
                _calculate_drawdown(snap)
                _calculate_efficiency(snap)
                _finalize_outcome(snap)
                finalized += 1
        if finalized:
            self._persist_state()
            logger.info("PreNewsBaselineTracker: finalized %d baseline snapshots", finalized)

    # ── Export ────────────────────────────────────────────────────────────

    def export_daily_baselines(self, session_date: Optional[str] = None) -> dict:
        """Export today's baseline snapshots to CSV and JSON."""
        session_date = session_date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        items = [s for s in self._snapshots.values() if s.session_date == session_date]
        if not items:
            return {"session_date": session_date, "total": 0, "csv_path": None, "json_path": None}

        # JSON export
        json_path = REPORTS_DIR / f"{session_date}_pre_news_baselines.json"
        report = {
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "session_date": session_date,
            "total_snapshots": len(items),
            "snapshots": [s.model_dump() for s in items],
        }
        save_json_file(json_path, report)

        # CSV export
        csv_path = REPORTS_DIR / f"{session_date}_pre_news_baselines.csv"
        headers = [
            "baseline_id", "baseline_type", "ticker", "scan_time", "session_date",
            "price_at_scan", "vwap_distance", "price_change_pct", "current_volume",
            "average_volume", "relative_volume", "time_of_day_rvol",
            "volume_acceleration_score", "latest_5candle_summary",
            "buying_pressure", "selling_pressure", "upper_wick_pct",
            "absorption_quality_score", "news_status", "catalyst_age_bucket",
            "offering_risk_score", "market_cap", "float_shares",
            "max_move_30m_pct", "max_move_1h_pct", "max_move_2h_pct",
            "max_move_same_day_pct", "drawdown_before_max_move_pct",
            "efficiency_ratio", "vwap_hold_after_scan", "final_baseline_outcome_label",
        ]
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=headers)
            writer.writeheader()
            for s in items:
                row = {h: (getattr(s, h) if getattr(s, h) is not None else "") for h in headers}
                for key in row:
                    if isinstance(row[key], bool):
                        row[key] = "Y" if row[key] else "N"
                    elif isinstance(row[key], list):
                        row[key] = ";".join(str(x) for x in row[key])
                writer.writerow(row)

        logger.info("PreNewsBaselineTracker: exported %d baselines for %s", len(items), session_date)
        return {"session_date": session_date, "total": len(items), "csv_path": str(csv_path), "json_path": str(json_path)}

    # ── Queries ───────────────────────────────────────────────────────────

    def get_all(self) -> list[PreNewsBaselineSnapshot]:
        return list(self._snapshots.values())

    def get_by_type(self, baseline_type: str) -> list[PreNewsBaselineSnapshot]:
        return [s for s in self._snapshots.values() if s.baseline_type == baseline_type]

    def get_summary(self) -> dict[str, Any]:
        all_snaps = list(self._snapshots.values())
        by_type = defaultdict(list)
        for s in all_snaps:
            by_type[s.baseline_type].append(s)
        return {
            "total_baselines": len(all_snaps),
            "by_type": {k: len(v) for k, v in by_type.items()},
            "unresolved": sum(1 for s in all_snaps if s.final_baseline_outcome_label == "unresolved"),
        }
