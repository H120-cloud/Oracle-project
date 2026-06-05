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
from src.utils.data_paths import agentic_data_dir, agentic_path
from typing import Optional

from src.core.agentic.pre_news_models import (
    PreNewsAnomaly,
    SuspicionLevel,
    NewsStatus,
)

logger = logging.getLogger(__name__)

_ANOMALIES_FILE = agentic_path("pre_news_anomalies.json")
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


def _enum_value(value, default: str = "") -> str:
    if value is None:
        return default
    raw = getattr(value, "value", value)
    return str(raw or default).strip().lower()


def _suspicion_value(pn: dict) -> str:
    return _enum_value(
        pn.get("classification")
        or pn.get("suspicion_level")
        or pn.get("suspicion")
        or "low"
    )


def _score_value(pn: dict) -> float:
    for key in (
        "pre_news_suspicion_score",
        "suspicion_score",
        "composite_suspicion_score",
    ):
        if key in pn:
            try:
                return float(pn.get(key) or 0.0)
            except Exception:
                return 0.0
    return 0.0


def _news_status_value(pn: dict) -> str:
    return _enum_value(pn.get("news_status") or "unknown_news_status")


def apply_pre_news_to_candidate(candidate) -> None:
    """
    Check if candidate has a pre-news anomaly and adjust scoring.
    Modifies candidate in place.
    """
    pn = get_pre_news_for_ticker(candidate.ticker)
    if not pn:
        return

    suspicion = _suspicion_value(pn)
    news_status = _news_status_value(pn)
    suspicion_score = _score_value(pn)

    # Attach pre-news metadata to candidate for ML features
    candidate.pre_news_suspicion_score = suspicion_score
    candidate.pre_news_has_anomaly = True

    no_news_statuses = {
        "no_news",
        "no_news_found",
        "no_public_news_found_in_sources",
        "stale",
        "unknown_news_status",
    }
    confirmed_statuses = {
        "matched",
        "news_lag_confirmed",
        "news_appeared_after_detection",
        "public_catalyst_already_visible",
    }

    if suspicion in ("high", "extreme", "critical") and news_status in no_news_statuses:
        # High suspicion with no news: possible distribution or imminent move
        # Increase trap risk slightly (be more cautious)
        if candidate.trap:
            old_trap = candidate.trap.trap_risk_score
            candidate.trap.trap_risk_score = min(95, old_trap + 10)
            logger.info(
                "Pre-news HIGH suspicion + no news for %s: trap risk %d → %d",
                candidate.ticker, old_trap, candidate.trap.trap_risk_score,
            )

    elif news_status in confirmed_statuses and suspicion_score > 50:
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
