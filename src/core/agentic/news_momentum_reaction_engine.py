"""
News Momentum Reaction Engine (V22)

Tracks price and volume reaction to news events.
Computes a news reaction score 0-100.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from src.core.agentic.news_momentum_models import NewsReactionScore, NewsReactionMetrics

logger = logging.getLogger(__name__)


def compute_reaction_metrics(
    price_before: Optional[float],
    price_current: Optional[float],
    volume_before: Optional[int],
    volume_current: Optional[int],
    vwap: Optional[float] = None,
    bid: Optional[float] = None,
    ask: Optional[float] = None,
    high: Optional[float] = None,
    low: Optional[float] = None,
    halt_count: int = 0,
) -> NewsReactionMetrics:
    """Build reaction metrics from raw market data."""
    m = NewsReactionMetrics()
    m.price_before_news = price_before
    m.price_current = price_current
    m.volume_before = volume_before
    m.volume_after = volume_current
    m.halt_count = halt_count

    if price_before and price_current and price_before > 0:
        m.move_pct = round(((price_current - price_before) / price_before) * 100, 2)

    if bid and ask and ask > 0:
        m.spread_pct = round(((ask - bid) / ask) * 100, 2)

    if vwap and price_current and vwap > 0:
        m.vwap_distance_pct = round(((price_current - vwap) / vwap) * 100, 2)
        m.holding_vwap = price_current >= vwap

    if high and low and high > low:
        total_range = high - low
        if price_current and price_before:
            upper = high - max(price_current, price_before)
            lower = min(price_current, price_before) - low
            m.upper_wick_pct = round((upper / total_range) * 100, 2) if total_range > 0 else 0
            m.lower_wick_pct = round((lower / total_range) * 100, 2) if total_range > 0 else 0

    return m


def score_news_reaction(
    metrics: NewsReactionMetrics,
    rvol: Optional[float] = None,
) -> NewsReactionScore:
    """
    Compute a news reaction score 0-100 based on how the market
    reacted to the news (price move, volume, continuation quality).
    """
    score = NewsReactionScore()
    score.rvol_score = rvol or 0.0

    # Price reaction strength
    move = metrics.move_pct
    if move > 100:
        score.price_reaction_strength = 100.0
    elif move > 50:
        score.price_reaction_strength = 90.0
    elif move > 25:
        score.price_reaction_strength = 80.0
    elif move > 10:
        score.price_reaction_strength = 65.0
    elif move > 5:
        score.price_reaction_strength = 45.0
    else:
        score.price_reaction_strength = 25.0

    # Volume reaction strength
    if metrics.volume_before and metrics.volume_after and metrics.volume_before > 0:
        vol_ratio = metrics.volume_after / metrics.volume_before
        if vol_ratio > 10:
            score.volume_reaction_strength = 100.0
        elif vol_ratio > 5:
            score.volume_reaction_strength = 85.0
        elif vol_ratio > 2:
            score.volume_reaction_strength = 65.0
        elif vol_ratio > 1:
            score.volume_reaction_strength = 40.0
        else:
            score.volume_reaction_strength = 20.0
    else:
        score.volume_reaction_strength = 30.0

    # Spread score (tighter = better)
    if metrics.spread_pct is not None:
        if metrics.spread_pct < 1.0:
            score.spread_score = 90.0
        elif metrics.spread_pct < 3.0:
            score.spread_score = 65.0
        elif metrics.spread_pct < 8.0:
            score.spread_score = 40.0
        else:
            score.spread_score = 15.0
    else:
        score.spread_score = 50.0

    # VWAP behavior score
    if metrics.holding_vwap:
        if metrics.vwap_distance_pct and metrics.vwap_distance_pct > 10:
            score.vwap_behavior_score = 90.0
        else:
            score.vwap_behavior_score = 75.0
    else:
        if metrics.vwap_distance_pct and metrics.vwap_distance_pct < -5:
            score.vwap_behavior_score = 25.0
        else:
            score.vwap_behavior_score = 45.0

    # Continuation quality
    cont = 50.0
    if metrics.higher_lows:
        cont += 20.0
    if metrics.holding_vwap:
        cont += 15.0
    if metrics.upper_wick_pct and metrics.upper_wick_pct < 20:
        cont += 10.0
    if metrics.move_pct > 30 and metrics.move_pct < 100:
        cont += 5.0
    score.continuation_quality = min(cont, 100.0)

    # Halt impact
    if metrics.halt_count > 2:
        score.halt_impact = 90.0
    elif metrics.halt_count > 0:
        score.halt_impact = 65.0
    else:
        score.halt_impact = 40.0

    # Composite
    composite = (
        score.price_reaction_strength * 0.25 +
        score.volume_reaction_strength * 0.20 +
        score.rvol_score * 0.15 +
        score.spread_score * 0.05 +
        score.vwap_behavior_score * 0.15 +
        score.continuation_quality * 0.15 +
        score.halt_impact * 0.05
    )
    score.composite_score = round(max(0.0, min(100.0, composite)), 1)
    return score
