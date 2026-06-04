"""
Agentic Momentum State Classifier — Part 4

Classifies where a stock is in the catalyst-momentum lifecycle:
  INITIAL_SPIKE → SPIKE_PULLBACK → CONSOLIDATION → SECOND_LEG_FORMING → CONTINUATION_CONFIRMED
  or → FAILED / DEAD
"""

import logging
from typing import Optional

from src.models.market_data import OHLCVBar
from src.core.agentic.models import MomentumState, MomentumSnapshot, AgenticCandidate

logger = logging.getLogger(__name__)


class MomentumClassifier:
    """Classify the momentum state of a catalyst candidate using intraday bars."""

    def classify(self, candidate: AgenticCandidate, bars: list[OHLCVBar]) -> AgenticCandidate:
        if not bars or len(bars) < 5:
            return candidate

        prices = [b.close for b in bars]
        volumes = [b.volume for b in bars]
        highs = [b.high for b in bars]
        lows = [b.low for b in bars]

        current_price = prices[-1]
        high_of_day = max(highs)
        recent_low = min(lows[-min(len(lows), 10):])

        # VWAP approximation: cumulative (price * volume) / cumulative volume
        cum_pv = 0.0
        cum_vol = 0.0
        for b in bars:
            typical = (b.high + b.low + b.close) / 3
            cum_pv += typical * b.volume
            cum_vol += b.volume
        vwap = cum_pv / cum_vol if cum_vol > 0 else current_price

        # Volume persistence: last 5 bars avg vs first 5 bars avg (spike vs now)
        spike_vol = sum(volumes[:5]) / max(len(volumes[:5]), 1)
        recent_vol = sum(volumes[-5:]) / max(len(volumes[-5:]), 1)
        vol_persistence = (recent_vol / spike_vol * 100) if spike_vol > 0 else 0

        # Higher low detection: compare last 3 swing lows
        swing_lows = []
        for i in range(2, len(lows) - 1):
            if lows[i] < lows[i - 1] and lows[i] < lows[i + 1]:
                swing_lows.append(lows[i])
        higher_low = len(swing_lows) >= 2 and swing_lows[-1] > swing_lows[-2] if len(swing_lows) >= 2 else False

        vwap_reclaimed = current_price > vwap

        # Consolidation detection: narrow range in last N bars
        if len(bars) >= 10:
            last_10_range = max(highs[-10:]) - min(lows[-10:])
            full_range = high_of_day - min(lows)
            consolidation_ratio = last_10_range / full_range if full_range > 0 else 1.0
            consolidating = consolidation_ratio < 0.35
            consolidation_bars = sum(1 for i in range(-min(len(bars), 20), 0)
                                     if (highs[i] - lows[i]) / current_price < 0.01)
        else:
            consolidating = False
            consolidation_bars = 0

        # Breakout from consolidation
        breakout = False
        if consolidating and len(bars) >= 12:
            consol_high = max(highs[-12:-2]) if len(highs) >= 12 else high_of_day
            if current_price > consol_high:
                breakout = True

        # Determine drop from high
        drop_from_high_pct = ((high_of_day - current_price) / high_of_day * 100) if high_of_day > 0 else 0

        # ── State classification ─────────────────────────────────────────
        if drop_from_high_pct < 3 and vol_persistence > 60:
            state = MomentumState.INITIAL_SPIKE
        elif drop_from_high_pct >= 3 and not consolidating and not higher_low:
            state = MomentumState.SPIKE_PULLBACK
        elif consolidating and not breakout:
            state = MomentumState.CONSOLIDATION
        elif higher_low and vwap_reclaimed and not breakout:
            state = MomentumState.SECOND_LEG_FORMING
        elif breakout and vwap_reclaimed:
            state = MomentumState.CONTINUATION_CONFIRMED
        elif drop_from_high_pct > 40 or (not vwap_reclaimed and vol_persistence < 20):
            state = MomentumState.DEAD
        elif drop_from_high_pct > 25 and not vwap_reclaimed:
            state = MomentumState.FAILED
        else:
            state = MomentumState.SPIKE_PULLBACK

        candidate.momentum = MomentumSnapshot(
            state=state,
            vwap=round(vwap, 4),
            price=current_price,
            high_of_day=high_of_day,
            post_spike_low=recent_low,
            consolidation_bars=consolidation_bars,
            higher_low_formed=higher_low,
            vwap_reclaimed=vwap_reclaimed,
            breakout_confirmed=breakout,
            volume_persistence_pct=round(vol_persistence, 1),
        )

        return candidate
