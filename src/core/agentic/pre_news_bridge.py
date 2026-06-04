"""
Pre-News → Agentic Bridge — V19.1

Lightweight integration: when Agentic processes a candidate,
check if that ticker has an active pre-news anomaly.

Effects:
- If pre-news anomaly is HIGH suspicion + NO news yet:
  boost trap_risk (possible insider selling / distribution)
  OR boost catalyst_strength (possible impending catalyst)
- If pre-news anomaly already matched to news:
  confirm catalyst validity
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

from src.core.agentic.pre_news_models import (
    PreNewsAnomaly,
    SuspicionLevel,
    NewsStatus,
)

logger = logging.getLogger(__name__)

_ANOMALIES_FILE = Path("data/agentic/pre_news_anomalies.json")
_CACHE_TTL = timedelta(minutes=5)
_last_load: Optional[datetime] = None
_cached_anomalies: dict[str, dict] = {}


def _load_anomalies() -> dict[str, dict]:
    """Load pre-news anomalies from disk with caching."""
    global _last_load, _cached_anomalies
    now = datetime.now(timezone.utc)
    if _last_load and (now - _last_load) < _CACHE_TTL:
        return _cached_anomalies

    if not _ANOMALIES_FILE.exists():
        _cached_anomalies = {}
        _last_load = now
        return {}

    try:
        with open(_ANOMALIES_FILE) as f:
            data = json.load(f)
        # Data may be a list or dict depending on version
        if isinstance(data, list):
            _cached_anomalies = {a.get("ticker", ""): a for a in data if a.get("ticker")}
        elif isinstance(data, dict):
            _cached_anomalies = data
        else:
            _cached_anomalies = {}
        _last_load = now
    except Exception as exc:
        logger.warning("Pre-news bridge: failed to load anomalies: %s", exc)
        _cached_anomalies = {}

    return _cached_anomalies


def get_pre_news_for_ticker(ticker: str) -> Optional[dict]:
    """Return raw pre-news anomaly data for a ticker if exists."""
    anomalies = _load_anomalies()
    return anomalies.get(ticker.upper())


def apply_pre_news_to_candidate(candidate) -> None:
    """
    Check if candidate has a pre-news anomaly and adjust scoring.
    Modifies candidate in place.
    """
    pn = get_pre_news_for_ticker(candidate.ticker)
    if not pn:
        return

    suspicion = pn.get("suspicion_level", "LOW")
    news_status = pn.get("news_status", "UNKNOWN")
    suspicion_score = pn.get("composite_suspicion_score", 0)

    # Attach pre-news metadata to candidate for ML features
    candidate.pre_news_suspicion_score = suspicion_score
    candidate.pre_news_has_anomaly = True

    if suspicion in ("HIGH", "CRITICAL") and news_status in ("NO_NEWS", "STALE"):
        # High suspicion with no news: possible distribution or imminent move
        # Increase trap risk slightly (be more cautious)
        if candidate.trap:
            old_trap = candidate.trap.trap_risk_score
            candidate.trap.trap_risk_score = min(95, old_trap + 10)
            logger.info(
                "Pre-news HIGH suspicion + no news for %s: trap risk %d → %d",
                candidate.ticker, old_trap, candidate.trap.trap_risk_score,
            )

    elif news_status == "MATCHED" and suspicion_score > 50:
        # News confirmed the anomaly: boost catalyst strength
        if candidate.catalyst:
            old_strength = candidate.catalyst.strength_score
            candidate.catalyst.strength_score = min(100, old_strength + 8)
            logger.info(
                "Pre-news confirmed catalyst for %s: strength %d → %d",
                candidate.ticker, old_strength, candidate.catalyst.strength_score,
            )

    logger.debug(
        "Pre-news bridge applied to %s: suspicion=%s, news=%s, score=%.0f",
        candidate.ticker, suspicion, news_status, suspicion_score,
    )
