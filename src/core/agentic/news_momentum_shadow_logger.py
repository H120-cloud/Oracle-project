"""
Shadow logger for the News Momentum pipeline.

Captures every candidate that hits the Telegram gate — whether the alert was
actually sent or blocked — into a separate JSON file. This lets us:
  1. Track "what would have happened" outcomes for blocked candidates.
  2. Retrain the ML model on a much larger, fuller dataset at end-of-week.
  3. Validate the 40% win-prob threshold against ground truth.

The same TelegramAlertRecord schema is reused with two extra flags:
  - was_blocked: True if the alert was NOT sent.
  - block_reason: short string explaining why (e.g. 'ml_hard_floor', 'cooldown').
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional, TYPE_CHECKING

from src.core.agentic.news_momentum_models import TelegramAlertRecord
from src.utils.atomic_json import load_json_file, save_json_file

if TYPE_CHECKING:
    from src.core.agentic.news_momentum_models import NewsMomentumCandidate

logger = logging.getLogger(__name__)

DATA_DIR = Path("data/agentic")
SHADOW_FILE = DATA_DIR / "news_momentum_shadow_alerts.json"

# ── Rolling-window limits ─────────────────────────────────────────────────
# Before this cap, the shadow log grew unbounded — hit 166MB and the atomic
# write (temp file + rename, needs 2× the size in temp space) started silently
# failing, leaving the file stuck at the last successful write for 18+ hours.
# Both limits are upper bounds; whichever hits first prunes the in-memory list.
SHADOW_MAX_AGE_DAYS = float(os.environ.get("SHADOW_MAX_AGE_DAYS", "7") or 7)
SHADOW_MAX_RECORDS = int(os.environ.get("SHADOW_MAX_RECORDS", "30000") or 30000)


def _prune(records: List[TelegramAlertRecord]) -> List[TelegramAlertRecord]:
    """Apply rolling-window limits: drop records older than SHADOW_MAX_AGE_DAYS,
    then keep only the most recent SHADOW_MAX_RECORDS. The function is total —
    no side effects beyond returning the pruned list."""
    if not records:
        return records
    cutoff = datetime.now(timezone.utc) - timedelta(days=SHADOW_MAX_AGE_DAYS)
    kept = [r for r in records if (r.sent_at or cutoff) >= cutoff]
    if len(kept) > SHADOW_MAX_RECORDS:
        kept.sort(key=lambda r: r.sent_at or datetime.min.replace(tzinfo=timezone.utc))
        kept = kept[-SHADOW_MAX_RECORDS:]
    return kept


class ShadowAlertLogger:
    """Append-only log of every candidate the Telegram gate evaluated."""

    def __init__(self) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._records: List[TelegramAlertRecord] = []
        self._load()

    def _load(self) -> None:
        try:
            raw = load_json_file(SHADOW_FILE, default=[])
            for item in raw:
                try:
                    self._records.append(TelegramAlertRecord(**item))
                except Exception:
                    pass
            before = len(self._records)
            self._records = _prune(self._records)
            pruned = before - len(self._records)
            if pruned:
                logger.info(
                    "ShadowLogger: loaded %d records, pruned %d old/excess on load",
                    len(self._records), pruned,
                )
            else:
                logger.info("ShadowLogger: loaded %d shadow records", len(self._records))
        except Exception as exc:
            logger.warning("ShadowLogger: failed to load shadow records: %s", exc)

    def _save(self) -> None:
        # Prune at write-time too: keeps the file bounded even between restarts.
        self._records = _prune(self._records)
        data = [r.model_dump(mode="json") for r in self._records]
        save_json_file(SHADOW_FILE, data)

    def log_candidate(
        self,
        c: "NewsMomentumCandidate",
        was_blocked: bool,
        block_reason: Optional[str] = None,
    ) -> None:
        """Record a candidate evaluation. Safe to call from the gate path."""
        try:
            ml_pred = getattr(c, "_ml_prediction", None)
            record = TelegramAlertRecord(
                alert_id=f"shadow_{c.ticker}_{int(datetime.now(timezone.utc).timestamp())}",
                ticker=c.ticker,
                sent_at=datetime.now(timezone.utc),
                catalyst_type=c.catalyst_sub_type,
                session_type=c.session,
                price_at_alert=c.current_price or 0.0,
                news_impact_score=c.news_impact_score,
                expected_return_score=c.expected_return_score,
                continuation_probability=getattr(c, "continuation_probability", 0.0),
                multi_day_score=getattr(c, "multi_day_score", 0.0),
                catalyst_category=c.catalyst_category.value if c.catalyst_category else None,
                float_category=c.float_category.value if getattr(c, "float_category", None) else None,
                market_cap_category=(
                    c.market_cap_category.value if getattr(c, "market_cap_category", None) else None
                ),
                move_pct_at_alert=c.move_pct,
                rvol_at_alert=getattr(c, "rvol", None),
                volume_at_alert=getattr(c, "volume", None),
                spread_pct_at_alert=getattr(c, "spread_pct", None),
                trap_risk_at_alert=getattr(c, "trap_risk", None),
                dilution_risk_at_alert=getattr(c, "dilution_risk", None),
                velocity_score_at_alert=getattr(c, "velocity_score", None),
                sources_seen_count=getattr(c, "sources_seen_count", None),
                is_negative=c.is_negative,
                is_vague=c.is_vague,
                is_delayed_reaction=getattr(c, "is_delayed_reaction", None),
                ml_predicted_win_prob=ml_pred.win_probability if ml_pred else None,
                ml_model_version=ml_pred.model_version if ml_pred else None,
                was_blocked=was_blocked,
                block_reason=block_reason,
            )
            self._records.append(record)
            # Save every 10 records to balance disk IO with crash safety
            if len(self._records) % 10 == 0:
                self._save()
        except Exception as exc:
            logger.debug("ShadowLogger: failed to log %s: %s", c.ticker, exc)

    def flush(self) -> None:
        """Force-save to disk. Call from EOD or shutdown hooks."""
        self._save()

    def get_unresolved(self, min_age_minutes: int = 30) -> List[TelegramAlertRecord]:
        """Return shadow records old enough to have outcomes but not yet resolved."""
        now = datetime.now(timezone.utc)
        out: List[TelegramAlertRecord] = []
        for r in self._records:
            if r.outcome is not None:
                continue
            age_min = (now - r.sent_at).total_seconds() / 60
            if age_min < min_age_minutes:
                continue
            out.append(r)
        return out

    @property
    def records(self) -> List[TelegramAlertRecord]:
        return self._records
