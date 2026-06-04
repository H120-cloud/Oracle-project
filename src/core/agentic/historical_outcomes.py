"""Outcome Labeler

Labels historical catalyst events with outcome classes based on post-news price action.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any

from src.core.agentic.historical_models import (
    HistoricalCatalystEvent,
    HistoricalOutcome,
    HistoricalOutcomeClass,
    DataQuality,
)

logger = logging.getLogger(__name__)


class OutcomeLabeler:
    """Labels catalyst events with outcome classes using post-event price data."""

    # Thresholds (percent)
    CLEAN_EXPANSION_MIN = 8.0
    SECOND_LEG_MIN = 5.0
    PARTIAL_MIN = 2.0
    FAILED_MAX = 1.0
    TRAP_DIP_MIN = -2.0
    TRAP_RECOVER_MAX = 1.0

    @classmethod
    def label(
        cls,
        event: HistoricalCatalystEvent,
        price_path: Optional[List[Dict[str, Any]]] = None,
    ) -> HistoricalOutcome:
        """Label a single event given optional post-event price path.

        price_path: list of dicts with keys: timestamp, price, high, low, volume.
        """
        base = event.price_at_news
        if base <= 0:
            logger.warning("Cannot label %s: price_at_news is zero", event.ticker)
            return HistoricalOutcome(
                event_id=event.id,
                outcome_class=HistoricalOutcomeClass.NO_REACTION,
                data_quality=DataQuality.STALE,
            )

        # Default values
        outcome = HistoricalOutcome(
            event_id=event.id,
            move_after_news_pct=0.0,
            data_quality=DataQuality.FULL if price_path else DataQuality.PARTIAL,
        )

        if not price_path:
            logger.info("No price path for %s, using fallback label", event.ticker)
            outcome.outcome_class = HistoricalOutcomeClass.NO_REACTION
            outcome.label_confidence = "low"
            return outcome

        prices = [p["price"] for p in price_path]
        highs = [p.get("high", p["price"]) for p in price_path]
        lows = [p.get("low", p["price"]) for p in price_path]

        # Time buckets
        t0 = price_path[0]["timestamp"]
        b5m, b15m, b30m, b1h = None, None, None, None
        for p in price_path:
            ts = p["timestamp"]
            mins = (ts - t0).total_seconds() / 60.0 if isinstance(ts, datetime) else 0
            if b5m is None and mins >= 5:
                b5m = p["price"]
            if b15m is None and mins >= 15:
                b15m = p["price"]
            if b30m is None and mins >= 30:
                b30m = p["price"]
            if b1h is None and mins >= 60:
                b1h = p["price"]

        outcome.price_after_5m = b5m
        outcome.price_after_15m = b15m
        outcome.price_after_30m = b30m
        outcome.price_after_1h = b1h

        # End-of-path price
        outcome.price_after_eod = prices[-1]
        outcome.move_after_news_pct = round((prices[-1] - base) / base * 100, 2)

        # Max favourable / adverse excursion
        max_high = max(highs) if highs else base
        min_low = min(lows) if lows else base
        outcome.max_favorable_excursion_pct = round((max_high - base) / base * 100, 2)
        outcome.max_adverse_excursion_pct = round((min_low - base) / base * 100, 2)

        # Time to high / failure
        for i, h in enumerate(highs):
            if h == max_high:
                outcome.time_to_high_minutes = i  # assuming 1-minute bars
                break
        for i, l in enumerate(lows):
            if l == min_low:
                outcome.time_to_failure_minutes = i
                break

        # Classify
        outcome.outcome_class = cls._classify(
            move=outcome.move_after_news_pct,
            mfe=outcome.max_favorable_excursion_pct,
            mae=outcome.max_adverse_excursion_pct,
            price_path=prices,
            base=base,
        )

        # Derived flags
        outcome.new_high_of_day_made = outcome.max_favorable_excursion_pct > 2.0
        outcome.made_second_leg = outcome.outcome_class == HistoricalOutcomeClass.SECOND_LEG_CONTINUATION
        outcome.initial_spike_only = outcome.outcome_class == HistoricalOutcomeClass.PARTIAL_MOVE
        outcome.vwap_lost_after_news = outcome.max_adverse_excursion_pct < -2.0

        # Target hits (simplified 2R / 3R targets)
        outcome.target_1_hit = outcome.max_favorable_excursion_pct >= cls.PARTIAL_MIN
        outcome.target_2_hit = outcome.max_favorable_excursion_pct >= cls.CLEAN_EXPANSION_MIN
        outcome.target_1_pct = round(cls.PARTIAL_MIN, 1)
        outcome.target_2_pct = round(cls.CLEAN_EXPANSION_MIN, 1)

        outcome.labeled_at = datetime.now(timezone.utc)
        outcome.label_confidence = "medium" if len(price_path) > 30 else "low"
        return outcome

    @classmethod
    def _classify(
        cls,
        move: float,
        mfe: float,
        mae: float,
        price_path: List[float],
        base: float,
    ) -> HistoricalOutcomeClass:
        # Failed: no meaningful move
        if move < cls.FAILED_MAX and mfe < cls.PARTIAL_MIN:
            return HistoricalOutcomeClass.FAILED_CATALYST

        # Trap: initial spike then failure
        if len(price_path) >= 3:
            early_high = max(price_path[:min(5, len(price_path))])
            early_move = (early_high - base) / base * 100
            if early_move > cls.PARTIAL_MIN and move < cls.FAILED_MAX:
                return HistoricalOutcomeClass.TRAP_MOVE

        # Clean expansion: strong sustained move with minimal drawdown
        if move >= cls.CLEAN_EXPANSION_MIN and abs(mae) < cls.FAILED_MAX:
            return HistoricalOutcomeClass.CLEAN_EXPANSION

        # Second leg: initial move, pullback, then continuation
        if move >= cls.SECOND_LEG_MIN:
            return HistoricalOutcomeClass.SECOND_LEG_CONTINUATION

        # Partial: small move then fade
        if move >= cls.PARTIAL_MIN and move < cls.CLEAN_EXPANSION_MIN:
            return HistoricalOutcomeClass.PARTIAL_MOVE

        # Sell the news: immediate fade
        if move < cls.TRAP_RECOVER_MAX and mae < cls.TRAP_DIP_MIN:
            return HistoricalOutcomeClass.SELL_THE_NEWS

        # Default: faded move
        if move > 0:
            return HistoricalOutcomeClass.FADED_MOVE

        return HistoricalOutcomeClass.NO_REACTION
