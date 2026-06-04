"""
Dilution History Engine (V23)

Aggregates historical dilution behaviour for a ticker across its recent
filings and an optional share-count time series. Produces:

- historical_dilution_behavior_score (0-100, higher = worse)
- DilutionBehavior classification
- counts of offerings / reverse splits / ATM signals
- share growth %

This engine is intentionally pure-Python and side-effect free; persistence
is handled by the orchestrator.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

from src.core.agentic.sec_filing_models import (
    DilutionBehavior,
    DilutionEvent,
    FilingType,
    SECFiling,
)


# Filing forms that represent offerings or dilution-effective events
_OFFERING_FORMS = {
    FilingType.F_424B5, FilingType.F_424B4, FilingType.F_424B3, FilingType.F_424B2,
    FilingType.S_1, FilingType.S_3,
}

_DILUTIVE_EVENT_SET = {
    DilutionEvent.ATM_OFFERING,
    DilutionEvent.DIRECT_OFFERING,
    DilutionEvent.PUBLIC_OFFERING,
    DilutionEvent.PIPE,
    DilutionEvent.WARRANT_ISSUANCE,
    DilutionEvent.CONVERTIBLE_NOTE,
    DilutionEvent.EQUITY_LINE,
    DilutionEvent.TOXIC_FINANCING,
    DilutionEvent.SHARE_AUTHORIZATION_INCREASE,
}


def count_offerings(filings: List[SECFiling], lookback_days: int = 365) -> int:
    """Count filings that represent an offering/dilution event within window."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    count = 0
    for f in filings:
        if f.filing_date < cutoff:
            continue
        if f.filing_type in _OFFERING_FORMS:
            count += 1
            continue
        if any(ev in _DILUTIVE_EVENT_SET for ev in f.dilution_events):
            count += 1
    return count


def count_reverse_splits(filings: List[SECFiling], lookback_days: int = 1095) -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    return sum(
        1 for f in filings
        if f.filing_date >= cutoff and DilutionEvent.REVERSE_SPLIT in f.dilution_events
    )


def has_active_atm(filings: List[SECFiling], lookback_days: int = 180) -> bool:
    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    return any(
        f.filing_date >= cutoff and DilutionEvent.ATM_OFFERING in f.dilution_events
        for f in filings
    )


def has_active_going_concern(filings: List[SECFiling], lookback_days: int = 180) -> bool:
    from src.core.agentic.sec_filing_models import SurvivalSignal
    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    return any(
        f.filing_date >= cutoff and SurvivalSignal.GOING_CONCERN in f.survival_signals
        for f in filings
    )


def share_growth_pct(share_history: Dict[str, int], lookback_days: int = 365) -> float:
    """Compute % share growth over `lookback_days`.

    `share_history` is {ISO-date-string -> share_count}. Returns 0.0 if
    insufficient data.
    """
    if not share_history or len(share_history) < 2:
        return 0.0
    # Parse and sort
    items: List[Tuple[datetime, int]] = []
    for k, v in share_history.items():
        try:
            d = datetime.fromisoformat(k)
            if d.tzinfo is None:
                d = d.replace(tzinfo=timezone.utc)
            items.append((d, int(v)))
        except Exception:
            continue
    if len(items) < 2:
        return 0.0
    items.sort(key=lambda kv: kv[0])

    latest_dt, latest = items[-1]
    cutoff = latest_dt - timedelta(days=lookback_days)
    # Earliest point >= cutoff (or earliest available)
    earliest = items[0][1]
    for dt, v in items:
        if dt >= cutoff:
            earliest = v
            break
    if earliest <= 0:
        return 0.0
    return round((latest - earliest) / earliest * 100.0, 2)


def historical_dilution_behavior_score(
    offerings_last_12mo: int,
    reverse_splits_last_36mo: int,
    share_growth_pct_value: float,
    has_toxic_history: bool,
    has_atm_active: bool,
) -> float:
    """Compute 0-100 score where higher = worse historical dilution behaviour."""
    score = 0.0

    # Frequency of offerings
    score += min(40.0, offerings_last_12mo * 12.0)
    # Reverse split history is catastrophic
    score += min(25.0, reverse_splits_last_36mo * 15.0)
    # Share growth %
    if share_growth_pct_value > 200:
        score += 25
    elif share_growth_pct_value > 100:
        score += 18
    elif share_growth_pct_value > 50:
        score += 10
    elif share_growth_pct_value > 25:
        score += 5
    # Toxic financing in history
    if has_toxic_history:
        score += 15
    # Active ATM
    if has_atm_active:
        score += 10

    return float(min(100.0, score))


def classify_behavior(score: float) -> DilutionBehavior:
    if score >= 70:
        return DilutionBehavior.TOXIC_DILUTION_PATTERN
    if score >= 45:
        return DilutionBehavior.SERIAL_DILUTER
    if score >= 20:
        return DilutionBehavior.OCCASIONAL_DILUTION
    return DilutionBehavior.CLEAN_STRUCTURE


def summarize_history(
    filings: List[SECFiling],
    share_history: Optional[Dict[str, int]] = None,
) -> Dict:
    """Return a dict of all aggregated historical stats for a ticker."""
    share_history = share_history or {}
    offerings = count_offerings(filings)
    splits = count_reverse_splits(filings)
    growth = share_growth_pct(share_history)
    atm = has_active_atm(filings)
    toxic = any(DilutionEvent.TOXIC_FINANCING in f.dilution_events for f in filings)
    going_concern = has_active_going_concern(filings)

    score = historical_dilution_behavior_score(
        offerings_last_12mo=offerings,
        reverse_splits_last_36mo=splits,
        share_growth_pct_value=growth,
        has_toxic_history=toxic,
        has_atm_active=atm,
    )
    behavior = classify_behavior(score)
    return {
        "offerings_last_12mo": offerings,
        "reverse_splits_last_36mo": splits,
        "share_growth_pct_12mo": growth,
        "atm_active": atm,
        "going_concern_active": going_concern,
        "historical_dilution_behavior_score": score,
        "dilution_behavior": behavior,
    }


__all__ = [
    "count_offerings",
    "count_reverse_splits",
    "has_active_atm",
    "has_active_going_concern",
    "share_growth_pct",
    "historical_dilution_behavior_score",
    "classify_behavior",
    "summarize_history",
]
