"""Historical Event Dataset Builder

Builds a dataset of historical catalyst events from news feeds,
SEC filings, and agentic outcomes. Reuses existing Agentic models
and infrastructure where possible.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Dict, Any

from src.utils.atomic_json import save_json_file, load_json_file

from src.core.agentic.historical_models import (
    HistoricalCatalystEvent,
    DataQuality,
)
from src.core.agentic.models import CatalystType

logger = logging.getLogger(__name__)

DATA_DIR = os.environ.get("AGENTIC_DATA_DIR", "data/agentic")


class HistoricalDatasetBuilder:
    """Builds and manages the historical catalyst event dataset."""

    def __init__(self, data_dir: str = DATA_DIR):
        self.data_dir = data_dir
        os.makedirs(self.data_dir, exist_ok=True)
        self._events: List[HistoricalCatalystEvent] = []
        self._load_existing()

    def _dataset_path(self) -> str:
        return os.path.join(self.data_dir, "historical_catalysts.json")

    def _load_existing(self) -> None:
        path = self._dataset_path()
        raw = load_json_file(path, default=None)
        if raw is None:
            return
        try:
            self._events = [HistoricalCatalystEvent(**item) for item in raw]
            logger.info("Loaded %s historical catalyst events", len(self._events))
        except Exception as exc:
            logger.warning("Could not load historical dataset: %s", exc)

    def _save(self) -> None:
        path = self._dataset_path()
        data = [evt.model_dump(mode="json") for evt in self._events]
        save_json_file(path, data)

    # ------------------------------------------------------------------ #
    #  Public API
    # ------------------------------------------------------------------ #

    def add_event(
        self,
        ticker: str,
        catalyst_type: CatalystType,
        headline: str = "",
        source: str = "",
        timestamp: Optional[datetime] = None,
        price_at_news: float = 0.0,
        float_shares: Optional[float] = None,
        market_cap: Optional[float] = None,
        is_premarket: bool = False,
        time_of_day_bucket: Optional[str] = None,
        **extra: Any,
    ) -> HistoricalCatalystEvent:
        """Add a new historical catalyst event."""
        event = HistoricalCatalystEvent(
            ticker=ticker.upper(),
            catalyst_type=catalyst_type,
            catalyst_headline=headline,
            catalyst_source=source,
            catalyst_timestamp=timestamp or datetime.now(timezone.utc),
            price_at_news=price_at_news,
            float_shares=float_shares,
            market_cap=market_cap,
            is_premarket=is_premarket,
            time_of_day_bucket=time_of_day_bucket,
            event_date=(timestamp or datetime.now(timezone.utc)).strftime("%Y-%m-%d"),
            data_quality=DataQuality.FULL,
            **extra,
        )
        self._events.append(event)
        self._save()
        logger.info("Added historical catalyst event %s for %s", event.id, event.ticker)
        return event

    def get_events(
        self,
        ticker: Optional[str] = None,
        catalyst_type: Optional[CatalystType] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        has_outcome: Optional[bool] = None,
        limit: int = 5000,
    ) -> List[HistoricalCatalystEvent]:
        """Query historical events with filters."""
        results: List[HistoricalCatalystEvent] = []
        for evt in self._events:
            if ticker and evt.ticker != ticker.upper():
                continue
            if catalyst_type and evt.catalyst_type != catalyst_type:
                continue
            if start_date and evt.catalyst_timestamp and evt.catalyst_timestamp < start_date:
                continue
            if end_date and evt.catalyst_timestamp and evt.catalyst_timestamp > end_date:
                continue
            if has_outcome is not None:
                has = evt.outcome is not None
                if has != has_outcome:
                    continue
            results.append(evt)
            if len(results) >= limit:
                break
        return results

    def get_event(self, event_id: str) -> Optional[HistoricalCatalystEvent]:
        for evt in self._events:
            if evt.id == event_id:
                return evt
        return None

    def update_event(self, event_id: str, **updates: Any) -> Optional[HistoricalCatalystEvent]:
        """Update an existing event and persist."""
        for idx, evt in enumerate(self._events):
            if evt.id == event_id:
                data = evt.model_dump()
                data.update(updates)
                updated = HistoricalCatalystEvent(**data)
                self._events[idx] = updated
                self._save()
                return updated
        return None

    def stats(self) -> Dict[str, Any]:
        """Quick summary stats for the dataset."""
        total = len(self._events)
        resolved = sum(1 for e in self._events if e.outcome is not None)
        by_type: Dict[str, int] = {}
        for e in self._events:
            by_type[e.catalyst_type.value] = by_type.get(e.catalyst_type.value, 0) + 1
        return {
            "total_events": total,
            "resolved_events": resolved,
            "unresolved_events": total - resolved,
            "by_catalyst_type": by_type,
            "date_range": {
                "earliest": (
                    min(e.catalyst_timestamp for e in self._events if e.catalyst_timestamp).isoformat()
                    if total else None
                ),
                "latest": (
                    max(e.catalyst_timestamp for e in self._events if e.catalyst_timestamp).isoformat()
                    if total else None
                ),
            },
        }

    def clear(self) -> None:
        """Clear the entire dataset (useful for testing)."""
        self._events.clear()
        self._save()
        logger.info("Cleared historical catalyst dataset")
