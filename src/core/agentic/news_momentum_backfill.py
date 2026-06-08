"""
Back-fill driver for unresolved shadow alerts and candidates.

Groups records by (ticker, date), fetches bars once per group,
computes MFE/MAE using the same math as the live resolver,
and writes outcomes to sidecar JSONL files.  Checkpointing lets
an interrupted run resume without re-fetching.

No original JSON files are modified.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
import traceback
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.core.agentic.news_momentum_models import (
    AlertOutcome,
    CatalystSubType,
    NewsMomentumCandidate,
    TelegramAlertRecord,
)
from src.core.agentic.news_momentum_outcome_resolver import (
    _bar_close_at,
    _max_high_n_days,
    _next_day_open_close_high,
)
from src.services.market_data import get_market_data_provider

logger = logging.getLogger(__name__)

from src.utils.data_paths import AGENTIC_DATA_DIR as DATA_DIR
SHADOW_FILE = DATA_DIR / "news_momentum_shadow_alerts.json"
CANDIDATE_FILE = DATA_DIR / "news_momentum_candidates.json"
BACKFILL_DIR = DATA_DIR / "backfill_runs"

# Same age thresholds as the live resolver (see news_momentum_outcome_resolver.py)
HOURS_BEFORE_NEXT_DAY = 18
HOURS_BEFORE_TWO_DAY = 36
HOURS_BEFORE_FIVE_DAY = 24 * 5 + 4


class BackfillError(Exception):
    """Base exception for back-fill failures."""


@dataclass
class _GroupKey:
    ticker: str
    date: str  # YYYY-MM-DD

    def __hash__(self) -> int:
        return hash((self.ticker, self.date))


@dataclass
class _ResolvedFields:
    """Outcome fields written to the sidecar."""
    source: str
    record_id: str
    price_15m_later: Optional[float] = None
    price_1h_later: Optional[float] = None
    price_4h_later: Optional[float] = None
    next_day_open: Optional[float] = None
    next_day_high: Optional[float] = None
    next_day_close: Optional[float] = None
    two_day_high: Optional[float] = None
    five_day_high: Optional[float] = None
    mfe_pct: Optional[float] = None
    mae_pct: Optional[float] = None
    outcome: Optional[str] = None


def _alert_time_from_record(record: Any) -> datetime:
    """Extract the alert/evaluation timestamp from a record."""
    if isinstance(record, TelegramAlertRecord):
        return record.sent_at
    if isinstance(record, NewsMomentumCandidate):
        return record.published_at
    # Fallback for raw dicts
    sent = getattr(record, "sent_at", None) or getattr(record, "published_at", None)
    if isinstance(sent, str):
        return datetime.fromisoformat(sent.replace("Z", "+00:00"))
    return sent


def _price_at_alert_from_record(record: Any) -> float:
    if isinstance(record, TelegramAlertRecord):
        return record.price_at_alert
    if isinstance(record, NewsMomentumCandidate):
        return record.current_price or 0.0
    price = getattr(record, "price_at_alert", None) or getattr(record, "current_price", None)
    return float(price) if price is not None else 0.0


def _record_id_from_record(record: Any) -> str:
    if isinstance(record, TelegramAlertRecord):
        return record.alert_id
    if isinstance(record, NewsMomentumCandidate):
        return record.id
    return getattr(record, "alert_id", None) or getattr(record, "id", "unknown")


def _classify_outcome(mfe_pct: Optional[float], mae_pct: Optional[float]) -> str:
    """Pure-function replica of AdaptiveTelegramLearning._classify_outcome.

    Uses the exact same thresholds so back-filled labels are comparable
    to live-resolved labels.
    """
    mfe = mfe_pct or 0.0
    mae = mae_pct or 0.0
    move_pct = mfe

    if move_pct > 25:
        return AlertOutcome.GREAT_ALERT.value
    if move_pct > 10:
        return AlertOutcome.GOOD_ALERT.value
    if move_pct < 2 and mae > 8:
        return AlertOutcome.TRAP_ALERT.value
    if move_pct < 2:
        return AlertOutcome.NO_FOLLOW_THROUGH.value
    if mae > 15:
        return AlertOutcome.TRAP_ALERT.value
    return AlertOutcome.LATE_ALERT.value


def _compute_mfe_mae(
    price_at_alert: float,
    price_15m: Optional[float],
    price_1h: Optional[float],
    price_4h: Optional[float],
    next_day_high: Optional[float],
    two_day_high: Optional[float],
    five_day_high: Optional[float],
    next_day_close: Optional[float],
) -> Tuple[Optional[float], Optional[float]]:
    """Pure-function replica of the MFE/MAE math in resolve_outcome."""
    if price_at_alert <= 0:
        return None, None
    highs = [h for h in [price_15m, price_1h, price_4h, next_day_high, two_day_high, five_day_high] if h]
    lows = [l for l in [price_15m, price_1h, price_4h, next_day_close] if l]
    mfe = None
    mae = None
    if highs:
        mfe = round(((max(highs) - price_at_alert) / price_at_alert) * 100, 2)
    if lows:
        mae = round(((price_at_alert - min(lows)) / price_at_alert) * 100, 2)
    return mfe, mae


class BackfillDriver:
    """
    Batch back-fill driver.

    Usage:
        driver = BackfillDriver(run_id="run_20260528_010000")
        driver.run()
    """

    def __init__(
        self,
        run_id: Optional[str] = None,
        output_dir: Optional[Path] = None,
        politeness_seconds: float = 0.1,
    ) -> None:
        self.run_id = run_id or datetime.now(timezone.utc).strftime("run_%Y%m%d_%H%M%S")
        self.output_dir = output_dir or (BACKFILL_DIR / self.run_id)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.politeness = politeness_seconds

        self.checkpoint_file = self.output_dir / "checkpoint.json"
        self.shadow_sidecar = self.output_dir / "shadow_resolved.jsonl"
        self.candidate_sidecar = self.output_dir / "candidate_resolved.jsonl"
        self.failure_log = self.output_dir / "failures.jsonl"
        self.summary_file = self.output_dir / "summary.json"

        self.completed_groups: set = set()
        self.failed_groups: Dict[str, str] = {}
        self.stats = {
            "total_groups": 0,
            "completed": 0,
            "failed": 0,
            "shadow_resolved": 0,
            "candidate_resolved": 0,
        }

        self._load_checkpoint()

    # ── Checkpointing ──────────────────────────────────────────────────────

    def _load_checkpoint(self) -> None:
        if self.checkpoint_file.exists():
            data = json.loads(self.checkpoint_file.read_text(encoding="utf-8"))
            self.completed_groups = set(data.get("completed_groups", []))
            self.failed_groups = dict(data.get("failed_groups", {}))
            self.stats = data.get("stats", self.stats)
            logger.info("Backfill: loaded checkpoint with %d completed, %d failed",
                        len(self.completed_groups), len(self.failed_groups))

    def _save_checkpoint(self) -> None:
        payload = {
            "run_id": self.run_id,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "completed_groups": sorted(self.completed_groups),
            "failed_groups": self.failed_groups,
            "stats": self.stats,
        }
        self.checkpoint_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _append_sidecar(self, sidecar: Path, record: _ResolvedFields) -> None:
        line = json.dumps({
            "source": record.source,
            "record_id": record.record_id,
            "price_15m_later": record.price_15m_later,
            "price_1h_later": record.price_1h_later,
            "price_4h_later": record.price_4h_later,
            "next_day_open": record.next_day_open,
            "next_day_high": record.next_day_high,
            "next_day_close": record.next_day_close,
            "two_day_high": record.two_day_high,
            "five_day_high": record.five_day_high,
            "mfe_pct": record.mfe_pct,
            "mae_pct": record.mae_pct,
            "outcome": record.outcome,
        }, default=str)
        with sidecar.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")

    def _log_failure(self, group_key: _GroupKey, record_id: str, reason: str) -> None:
        line = json.dumps({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "ticker": group_key.ticker,
            "date": group_key.date,
            "record_id": record_id,
            "reason": reason,
        })
        with self.failure_log.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")

    # ── Data loading ─────────────────────────────────────────────────────

    def load_shadow(self) -> List[TelegramAlertRecord]:
        raw = json.loads(SHADOW_FILE.read_text(encoding="utf-8"))
        records: List[TelegramAlertRecord] = []
        for item in raw:
            try:
                rec = TelegramAlertRecord(**item)
                records.append(rec)
            except Exception:
                # Log but do not silently swallow — one noisy log line is enough
                logger.warning("Backfill: failed to parse shadow record %s", item.get("alert_id", "unknown"))
        logger.info("Backfill: loaded %d shadow records", len(records))
        return records

    def load_candidates(self) -> List[NewsMomentumCandidate]:
        raw = json.loads(CANDIDATE_FILE.read_text(encoding="utf-8"))
        records: List[NewsMomentumCandidate] = []
        for item in raw:
            try:
                rec = NewsMomentumCandidate(**item)
                records.append(rec)
            except Exception:
                logger.warning("Backfill: failed to parse candidate record %s", item.get("id", "unknown"))
        logger.info("Backfill: loaded %d candidate records", len(records))
        return records

    # ── Grouping ───────────────────────────────────────────────────────────

    @staticmethod
    def _group_records(records: List[Any]) -> Dict[_GroupKey, List[Any]]:
        groups: Dict[_GroupKey, List[Any]] = defaultdict(list)
        for rec in records:
            try:
                dt = _alert_time_from_record(rec)
                key = _GroupKey(ticker=rec.ticker, date=dt.strftime("%Y-%m-%d"))
                groups[key].append(rec)
            except Exception:
                rid = _record_id_from_record(rec)
                logger.warning("Backfill: skipping ungroupable record %s", rid)
        return groups

    # ── Resolution ─────────────────────────────────────────────────────────

    def _resolve_group(
        self,
        key: _GroupKey,
        records: List[Any],
        provider,
    ) -> List[_ResolvedFields]:
        """Fetch bars once and resolve every record in the group."""
        ticker = key.ticker
        alert_date = datetime.strptime(key.date, "%Y-%m-%d").date()

        # Determine a sensible fetch window. We need the alert day + next few days.
        # Use start/end explicitly to avoid ambiguity with yfinance's "period" logic.
        start_dt = datetime.combine(alert_date, datetime.min.time(), tzinfo=timezone.utc)
        end_dt = start_dt + timedelta(days=7)

        # Fetch intraday bars (5m) for MFE/MAE within the first few hours
        intraday_bars: List[Any] = []
        try:
            intraday_bars = provider.get_ohlcv(
                ticker,
                start=start_dt.strftime("%Y-%m-%d"),
                end=end_dt.strftime("%Y-%m-%d"),
                interval="5m",
                prepost=True,
            ) or []
        except Exception as exc:
            logger.debug("Backfill: intraday fetch failed for %s %s: %s", ticker, key.date, exc)

        # Fetch daily bars for next-day / multi-day highs
        daily_bars: List[Any] = []
        try:
            daily_bars = provider.get_ohlcv(
                ticker,
                start=start_dt.strftime("%Y-%m-%d"),
                end=(start_dt + timedelta(days=10)).strftime("%Y-%m-%d"),
                interval="1d",
                prepost=False,
            ) or []
        except Exception as exc:
            logger.debug("Backfill: daily fetch failed for %s %s: %s", ticker, key.date, exc)

        if not intraday_bars and not daily_bars:
            raise BackfillError(f"No bars returned for {ticker} on {key.date}")

        resolved: List[_ResolvedFields] = []
        for rec in records:
            rid = _record_id_from_record(rec)
            alert_time = _alert_time_from_record(rec)
            price_at_alert = _price_at_alert_from_record(rec)
            source = "shadow" if isinstance(rec, TelegramAlertRecord) else "candidate"

            if price_at_alert <= 0:
                self._log_failure(key, rid, "invalid_price_at_alert")
                continue

            # Compute price levels using the same helpers as the live resolver
            price_15m = price_1h = price_4h = None
            if intraday_bars:
                price_15m = _bar_close_at(intraday_bars, alert_time + timedelta(minutes=15))
                price_1h = _bar_close_at(intraday_bars, alert_time + timedelta(hours=1))
                price_4h = _bar_close_at(intraday_bars, alert_time + timedelta(hours=4))

            next_day_open = next_day_close = next_day_high = None
            if daily_bars:
                next_day_open, next_day_close, next_day_high = _next_day_open_close_high(daily_bars, alert_time)

            two_day_high = None
            if daily_bars:
                two_day_high = _max_high_n_days(daily_bars, alert_time, n_days=2)

            five_day_high = None
            if daily_bars:
                five_day_high = _max_high_n_days(daily_bars, alert_time, n_days=5)

            mfe, mae = _compute_mfe_mae(
                price_at_alert,
                price_15m, price_1h, price_4h,
                next_day_high, two_day_high, five_day_high,
                next_day_close,
            )

            outcome = None
            if mfe is not None:
                outcome = _classify_outcome(mfe, mae)

            res = _ResolvedFields(
                source=source,
                record_id=rid,
                price_15m_later=price_15m,
                price_1h_later=price_1h,
                price_4h_later=price_4h,
                next_day_open=next_day_open,
                next_day_high=next_day_high,
                next_day_close=next_day_close,
                two_day_high=two_day_high,
                five_day_high=five_day_high,
                mfe_pct=mfe,
                mae_pct=mae,
                outcome=outcome,
            )
            resolved.append(res)

            sidecar = self.shadow_sidecar if source == "shadow" else self.candidate_sidecar
            self._append_sidecar(sidecar, res)

        return resolved

    # ── Main loop ──────────────────────────────────────────────────────────

    def run(self) -> dict:
        """Execute the back-fill. Returns a summary dict."""
        logger.info("Backfill: starting run %s", self.run_id)

        provider = get_market_data_provider()
        logger.info("Backfill: using provider %s", provider.__class__.__name__)

        shadow_records = self.load_shadow()
        candidate_records = self.load_candidates()

        shadow_groups = self._group_records(shadow_records)
        candidate_groups = self._group_records(candidate_records)

        # Merge groups — a (ticker, date) may appear in both sources
        all_groups: Dict[_GroupKey, List[Any]] = defaultdict(list)
        for key, recs in shadow_groups.items():
            all_groups[key].extend(recs)
        for key, recs in candidate_groups.items():
            all_groups[key].extend(recs)

        self.stats["total_groups"] = len(all_groups)
        self._save_checkpoint()

        for idx, (key, records) in enumerate(sorted(all_groups.items(), key=lambda kv: kv[0].date), start=1):
            group_str = f"{key.ticker}|{key.date}"

            if group_str in self.completed_groups:
                logger.debug("Backfill: skipping already-completed group %s", group_str)
                continue
            if group_str in self.failed_groups:
                logger.debug("Backfill: skipping previously-failed group %s", group_str)
                continue

            logger.info("Backfill: [%d/%d] resolving %s (%d records)", idx, len(all_groups), group_str, len(records))
            sys.stdout.flush()

            try:
                resolved = self._resolve_group(key, records, provider)
                self.completed_groups.add(group_str)
                for r in resolved:
                    if r.source == "shadow":
                        self.stats["shadow_resolved"] += 1
                    else:
                        self.stats["candidate_resolved"] += 1
            except BackfillError as exc:
                logger.warning("Backfill: group %s failed — %s", group_str, exc)
                self.failed_groups[group_str] = str(exc)
                for rec in records:
                    self._log_failure(key, _record_id_from_record(rec), str(exc))
                self.stats["failed"] += 1
            except Exception as exc:
                # Unexpected error — log structured info, then raise
                logger.error("Backfill: unexpected error in group %s: %s", group_str, exc)
                traceback.print_exc()
                for rec in records:
                    self._log_failure(key, _record_id_from_record(rec), f"unexpected: {exc}")
                raise BackfillError(f"Unexpected error in group {group_str}: {exc}") from exc

            self._save_checkpoint()

            # Politeness sleep between groups (not within a group)
            if self.politeness > 0:
                time.sleep(self.politeness)

        # Final summary
        self.stats["completed"] = len(self.completed_groups)
        summary = {
            "run_id": self.run_id,
            "finished_at": datetime.now(timezone.utc).isoformat(),
            **self.stats,
        }
        self.summary_file.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        logger.info("Backfill: finished. Summary: %s", summary)
        return summary


def main() -> None:
    _handler = logging.StreamHandler(sys.stdout)
    _handler.setLevel(logging.DEBUG)
    _handler.addFilter(lambda rec: rec.levelno < logging.WARNING)
    _handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    _err_handler = logging.StreamHandler(sys.stderr)
    _err_handler.setLevel(logging.WARNING)
    _err_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[_handler, _err_handler])
    driver = BackfillDriver()
    try:
        result = driver.run()
        print(json.dumps(result, indent=2))
    except BackfillError as exc:
        logger.error("Backfill failed: %s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
