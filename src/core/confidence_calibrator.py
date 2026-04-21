"""
Confidence Calibrator — V10

Maps raw system confidence scores to actual historical win rates.
After backtesting, this module:
  1. Builds a calibration curve from historical trades
  2. Adjusts live confidence scores to reflect real probabilities
  3. Persists calibration data for use across sessions

Without calibration data, passes through raw scores unchanged.
"""

import json
import logging
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, Dict, List, Tuple

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class CalibrationBucket:
    """One bucket in the calibration curve."""
    raw_range_low: float
    raw_range_high: float
    trade_count: int
    actual_win_rate: float
    avg_pnl: float
    calibrated_confidence: float  # What to display instead


@dataclass
class CalibrationProfile:
    """Full calibration state."""
    buckets: List[CalibrationBucket] = field(default_factory=list)
    grade_adjustments: Dict[str, float] = field(default_factory=dict)
    htf_adjustments: Dict[str, float] = field(default_factory=dict)
    total_trades_used: int = 0
    last_calibrated: str = ""
    is_calibrated: bool = False


class ConfidenceCalibrator:
    """
    Calibrates confidence scores based on actual backtest outcomes.

    Usage:
        calibrator = ConfidenceCalibrator()
        # After backtesting:
        calibrator.calibrate_from_trades(backtest_trades)
        # In live pipeline:
        adjusted = calibrator.adjust(raw_confidence=75, grade="B", htf_bias="BULLISH")
    """

    def __init__(self, data_dir: str = "data/calibration"):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.profile = CalibrationProfile()
        self._load()

    def calibrate_from_trades(self, trades: list) -> CalibrationProfile:
        """
        Build calibration curve from backtest trades.

        Each trade must have: .confidence, .pnl_pct, .setup_grade, .htf_bias
        """
        if len(trades) < 20:
            logger.warning("Only %d trades — need 20+ for meaningful calibration", len(trades))

        # 1. Build confidence buckets
        bucket_ranges = [(0, 30), (30, 45), (45, 55), (55, 65), (65, 75), (75, 85), (85, 100)]
        buckets = []
        for lo, hi in bucket_ranges:
            bucket_trades = [t for t in trades if lo <= (getattr(t, 'confidence', 0) or 0) < hi]
            if bucket_trades:
                wins = [t for t in bucket_trades if t.pnl_pct > 0]
                actual_wr = len(wins) / len(bucket_trades) * 100
                avg_pnl = np.mean([t.pnl_pct for t in bucket_trades])

                # Calibrated confidence = actual win rate (what the number SHOULD mean)
                calibrated = round(actual_wr, 1)

                buckets.append(CalibrationBucket(
                    raw_range_low=lo, raw_range_high=hi,
                    trade_count=len(bucket_trades),
                    actual_win_rate=round(actual_wr, 1),
                    avg_pnl=round(avg_pnl, 2),
                    calibrated_confidence=calibrated,
                ))

        # 2. Grade adjustments
        grade_adj = {}
        for grade in ["A", "B", "C", "D", "F"]:
            g_trades = [t for t in trades if getattr(t, 'setup_grade', '') == grade]
            if g_trades:
                g_wins = [t for t in g_trades if t.pnl_pct > 0]
                wr = len(g_wins) / len(g_trades) * 100
                baseline = sum(1 for t in trades if t.pnl_pct > 0) / len(trades) * 100 if trades else 50
                grade_adj[grade] = round(wr - baseline, 1)

        # 3. HTF bias adjustments
        htf_adj = {}
        for bias in ["BULLISH", "NEUTRAL", "BEARISH"]:
            h_trades = [t for t in trades if getattr(t, 'htf_bias', None) == bias]
            if h_trades:
                h_wins = [t for t in h_trades if t.pnl_pct > 0]
                wr = len(h_wins) / len(h_trades) * 100
                baseline = sum(1 for t in trades if t.pnl_pct > 0) / len(trades) * 100 if trades else 50
                htf_adj[bias] = round(wr - baseline, 1)

        from datetime import datetime
        self.profile = CalibrationProfile(
            buckets=buckets,
            grade_adjustments=grade_adj,
            htf_adjustments=htf_adj,
            total_trades_used=len(trades),
            last_calibrated=datetime.utcnow().isoformat(),
            is_calibrated=True,
        )
        self._save()

        logger.info(
            "Calibration complete: %d trades, %d buckets, grades=%s, htf=%s",
            len(trades), len(buckets), grade_adj, htf_adj,
        )
        return self.profile

    def adjust(
        self,
        raw_confidence: float,
        grade: Optional[str] = None,
        htf_bias: Optional[str] = None,
    ) -> float:
        """
        Adjust a raw confidence score using calibration data.

        Returns calibrated confidence (actual expected win rate).
        Falls back to raw score if not calibrated.
        """
        if not self.profile.is_calibrated:
            return raw_confidence

        # Find matching bucket
        calibrated = raw_confidence
        for bucket in self.profile.buckets:
            if bucket.raw_range_low <= raw_confidence < bucket.raw_range_high:
                calibrated = bucket.calibrated_confidence
                break

        # Apply grade adjustment
        if grade and grade in self.profile.grade_adjustments:
            calibrated += self.profile.grade_adjustments[grade] * 0.5

        # Apply HTF adjustment
        if htf_bias and htf_bias in self.profile.htf_adjustments:
            calibrated += self.profile.htf_adjustments[htf_bias] * 0.3

        return round(max(0, min(100, calibrated)), 1)

    def get_profile(self) -> dict:
        """Return calibration profile as dict."""
        if not self.profile.is_calibrated:
            return {"calibrated": False, "message": "Run backtesting first to calibrate"}

        return {
            "calibrated": True,
            "total_trades": self.profile.total_trades_used,
            "last_calibrated": self.profile.last_calibrated,
            "buckets": [
                {
                    "raw_range": f"{b.raw_range_low}-{b.raw_range_high}%",
                    "trades": b.trade_count,
                    "actual_win_rate": b.actual_win_rate,
                    "displayed_as": b.calibrated_confidence,
                    "avg_pnl": b.avg_pnl,
                }
                for b in self.profile.buckets
            ],
            "grade_impact": self.profile.grade_adjustments,
            "htf_impact": self.profile.htf_adjustments,
        }

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _save(self):
        try:
            path = self.data_dir / "calibration.json"
            data = {
                "buckets": [
                    {
                        "raw_range_low": b.raw_range_low,
                        "raw_range_high": b.raw_range_high,
                        "trade_count": b.trade_count,
                        "actual_win_rate": b.actual_win_rate,
                        "avg_pnl": b.avg_pnl,
                        "calibrated_confidence": b.calibrated_confidence,
                    }
                    for b in self.profile.buckets
                ],
                "grade_adjustments": self.profile.grade_adjustments,
                "htf_adjustments": self.profile.htf_adjustments,
                "total_trades_used": self.profile.total_trades_used,
                "last_calibrated": self.profile.last_calibrated,
                "is_calibrated": self.profile.is_calibrated,
            }
            with open(path, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error("Failed to save calibration: %s", e)

    def _load(self):
        try:
            path = self.data_dir / "calibration.json"
            if not path.exists():
                return
            with open(path) as f:
                data = json.load(f)
            self.profile = CalibrationProfile(
                buckets=[CalibrationBucket(**b) for b in data.get("buckets", [])],
                grade_adjustments=data.get("grade_adjustments", {}),
                htf_adjustments=data.get("htf_adjustments", {}),
                total_trades_used=data.get("total_trades_used", 0),
                last_calibrated=data.get("last_calibrated", ""),
                is_calibrated=data.get("is_calibrated", False),
            )
            if self.profile.is_calibrated:
                logger.info("Loaded calibration: %d trades, %d buckets",
                           self.profile.total_trades_used, len(self.profile.buckets))
        except Exception as e:
            logger.warning("Failed to load calibration: %s", e)
