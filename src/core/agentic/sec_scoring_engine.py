"""
SEC Structural Scoring Engine (V23)

Combines analyzed filings + dilution history into the 9 structural scores
defined in the SEC Filing Intelligence spec, plus derived classification
and a structural trap risk score.

All inputs are deterministic Python data — this module is fully unit-testable.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from src.core.agentic.sec_filing_models import (
    DilutionBehavior,
    DilutionEvent,
    FilingSentiment,
    FilingType,
    OracleStructuralAction,
    PositiveStructureSignal,
    SECFiling,
    StructuralScores,
    SurvivalSignal,
)


# ── Individual scoring functions ────────────────────────────────────────────


def _recent(filings: List[SECFiling], days: int = 180) -> List[SECFiling]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    return [f for f in filings if f.filing_date >= cutoff]


def dilution_probability(filings: List[SECFiling]) -> float:
    """0-100 likelihood that further dilution will occur soon."""
    recent = _recent(filings, 180)
    score = 0.0
    if any(DilutionEvent.ATM_OFFERING in f.dilution_events for f in recent):
        score += 45
    if any(DilutionEvent.SHELF_REGISTRATION in f.dilution_events for f in recent):
        score += 25
    if any(DilutionEvent.EQUITY_LINE in f.dilution_events for f in recent):
        score += 35
    if any(DilutionEvent.PIPE in f.dilution_events for f in recent):
        score += 20
    if any(DilutionEvent.SHARE_AUTHORIZATION_INCREASE in f.dilution_events for f in recent):
        score += 15
    if any(DilutionEvent.CONVERTIBLE_NOTE in f.dilution_events for f in recent):
        score += 15
    if any(DilutionEvent.WARRANT_ISSUANCE in f.dilution_events for f in recent):
        score += 10
    if any(SurvivalSignal.LOW_CASH_RUNWAY in f.survival_signals for f in recent):
        score += 20
    return float(min(100.0, score))


def toxic_financing(filings: List[SECFiling]) -> float:
    recent = _recent(filings, 365)
    score = 0.0
    for f in recent:
        if DilutionEvent.TOXIC_FINANCING in f.dilution_events:
            score += 45
        if DilutionEvent.EQUITY_LINE in f.dilution_events:
            score += 25
        if DilutionEvent.CONVERTIBLE_NOTE in f.dilution_events:
            score += 15
    return float(min(100.0, score))


def warrant_overhang(filings: List[SECFiling]) -> float:
    """Estimate warrant overhang from recent filings.

    Without precise share count we use a heuristic: count warrant
    issuances, and downgrade if warrant_cleanup is present.
    """
    recent = _recent(filings, 540)
    issued = sum(
        1 for f in recent if DilutionEvent.WARRANT_ISSUANCE in f.dilution_events
    )
    cleaned = sum(
        1 for f in recent if PositiveStructureSignal.WARRANT_CLEANUP in f.positive_signals
    )
    score = issued * 22.0 - cleaned * 25.0
    return float(max(0.0, min(100.0, score)))


def cash_runway(filings: List[SECFiling]) -> float:
    """0-100 where higher = healthier runway.

    Uses the most recent filing with a parsed cash balance and burn rate
    (if quarterly burn isn't known we infer 12 months runway if cash is
    "substantial" relative to filing materiality).
    """
    recent = _recent(filings, 365)
    if not recent:
        return 50.0  # neutral when unknown

    # Penalize if recent filing flags low runway / going concern
    score = 60.0
    for f in recent:
        if SurvivalSignal.LOW_CASH_RUNWAY in f.survival_signals:
            score -= 30
        if SurvivalSignal.GOING_CONCERN in f.survival_signals:
            score -= 40
        if PositiveStructureSignal.IMPROVED_CASH in f.positive_signals:
            score += 20
        if PositiveStructureSignal.FINANCING_COMPLETED in f.positive_signals:
            score += 15
        if PositiveStructureSignal.DEBT_PAYOFF in f.positive_signals:
            score += 10

    # Direct estimate if both cash + burn are known
    latest_with_cash = next(
        (f for f in sorted(recent, key=lambda x: x.filing_date, reverse=True)
         if f.cash_balance_usd and f.quarterly_burn_usd),
        None,
    )
    if latest_with_cash:
        quarters = latest_with_cash.cash_balance_usd / max(latest_with_cash.quarterly_burn_usd, 1)
        if quarters >= 12:
            score = max(score, 95)
        elif quarters >= 8:
            score = max(score, 85)
        elif quarters >= 4:
            score = max(score, 70)
        elif quarters >= 2:
            score = min(score, 50)
        else:
            score = min(score, 25)

    return float(max(0.0, min(100.0, score)))


def survival_risk(filings: List[SECFiling]) -> float:
    recent = _recent(filings, 365)
    score = 0.0
    for f in recent:
        if SurvivalSignal.GOING_CONCERN in f.survival_signals:
            score += 50
        if SurvivalSignal.BANKRUPTCY_RISK in f.survival_signals:
            score += 50
        if SurvivalSignal.AUDITOR_WARNING in f.survival_signals:
            score += 25
        if SurvivalSignal.COVENANT_RISK in f.survival_signals:
            score += 20
        if SurvivalSignal.NASDAQ_DEFICIENCY in f.survival_signals:
            score += 20
        if SurvivalSignal.LOW_CASH_RUNWAY in f.survival_signals:
            score += 20
    return float(min(100.0, score))


def balance_sheet_quality(filings: List[SECFiling]) -> float:
    """0-100 where higher = healthier balance sheet."""
    recent = _recent(filings, 365)
    score = 55.0  # neutral baseline
    for f in recent:
        if PositiveStructureSignal.DEBT_PAYOFF in f.positive_signals:
            score += 15
        if PositiveStructureSignal.IMPROVED_CASH in f.positive_signals:
            score += 12
        if PositiveStructureSignal.REDUCED_LIABILITIES in f.positive_signals:
            score += 10
        if PositiveStructureSignal.BUYBACK_AUTHORIZATION in f.positive_signals:
            score += 12
        if PositiveStructureSignal.INSIDER_BUYING in f.positive_signals:
            score += 8
        if PositiveStructureSignal.WARRANT_CLEANUP in f.positive_signals:
            score += 10
        # Penalize
        if SurvivalSignal.GOING_CONCERN in f.survival_signals:
            score -= 40
        if SurvivalSignal.AUDITOR_WARNING in f.survival_signals:
            score -= 20
        if DilutionEvent.TOXIC_FINANCING in f.dilution_events:
            score -= 25
        if DilutionEvent.ATM_OFFERING in f.dilution_events:
            score -= 12
    return float(max(0.0, min(100.0, score)))


def offering_risk(filings: List[SECFiling]) -> float:
    """Risk that an offering will be priced soon."""
    recent = _recent(filings, 90)
    score = 0.0
    for f in recent:
        if f.filing_type in {FilingType.S_3, FilingType.S_3_ASR}:
            score += 25
        if f.filing_type in {FilingType.F_424B5, FilingType.F_424B4}:
            score += 60
        if DilutionEvent.ATM_OFFERING in f.dilution_events:
            score += 40
        if DilutionEvent.SHELF_REGISTRATION in f.dilution_events:
            score += 20
    return float(min(100.0, score))


def capital_raise_probability(filings: List[SECFiling]) -> float:
    """Composite: dilution probability + survival pressure."""
    return float(min(100.0, dilution_probability(filings) * 0.7 + survival_risk(filings) * 0.3))


def reverse_split_risk(filings: List[SECFiling]) -> float:
    recent = _recent(filings, 365)
    score = 0.0
    for f in recent:
        if DilutionEvent.REVERSE_SPLIT in f.dilution_events:
            score += 70
        if SurvivalSignal.NASDAQ_DEFICIENCY in f.survival_signals:
            score += 35
    return float(min(100.0, score))


def structural_trap_risk(scores: StructuralScores, dilution_behavior: DilutionBehavior) -> float:
    """How likely is a momentum spike to be a structural trap?"""
    base = (
        scores.dilution_probability_score * 0.30
        + scores.toxic_financing_score * 0.25
        + scores.offering_risk_score * 0.20
        + scores.warrant_overhang_score * 0.10
        + scores.survival_risk_score * 0.10
        + scores.reverse_split_risk_score * 0.05
    )
    if dilution_behavior == DilutionBehavior.TOXIC_DILUTION_PATTERN:
        base += 15
    elif dilution_behavior == DilutionBehavior.SERIAL_DILUTER:
        base += 10
    return float(min(100.0, base))


# ── Overall sentiment + Oracle action ───────────────────────────────────────


def _aggregate_sentiment(filings: List[SECFiling]) -> FilingSentiment:
    if not filings:
        return FilingSentiment.NEUTRAL
    recent = sorted(_recent(filings, 180), key=lambda f: f.filing_date, reverse=True)
    if not recent:
        return FilingSentiment.NEUTRAL
    # Weight more recent filings higher
    order = [FilingSentiment.VERY_NEGATIVE, FilingSentiment.NEGATIVE,
             FilingSentiment.NEUTRAL, FilingSentiment.POSITIVE, FilingSentiment.VERY_POSITIVE]
    weights = {s: i for i, s in enumerate(order)}  # 0..4
    total = 0.0
    weight_sum = 0.0
    for i, f in enumerate(recent):
        w = max(0.2, 1.0 - i * 0.15)
        total += weights[f.filing_sentiment] * w
        weight_sum += w
    avg = total / weight_sum if weight_sum else 2.0
    idx = int(round(avg))
    idx = max(0, min(4, idx))
    return order[idx]


def _oracle_action(scores: StructuralScores, overall_sentiment: FilingSentiment) -> OracleStructuralAction:
    # Catastrophic: any single very high signal OR two material risks together
    if scores.survival_risk_score >= 70 or scores.toxic_financing_score >= 60:
        return OracleStructuralAction.STRUCTURAL_TRAP
    if scores.survival_risk_score >= 40 and scores.toxic_financing_score >= 40:
        return OracleStructuralAction.STRUCTURAL_TRAP
    if scores.structural_trap_risk_score >= 65 or scores.offering_risk_score >= 70:
        return OracleStructuralAction.AVOID_CHASE
    if scores.dilution_probability_score >= 50 or scores.warrant_overhang_score >= 50:
        return OracleStructuralAction.CAUTION
    if scores.balance_sheet_quality_score >= 70 and scores.dilution_probability_score <= 30:
        if overall_sentiment in {FilingSentiment.POSITIVE, FilingSentiment.VERY_POSITIVE}:
            return OracleStructuralAction.TRADEABLE
        return OracleStructuralAction.SWING_WATCH
    return OracleStructuralAction.SWING_WATCH


# ── Main entrypoint ─────────────────────────────────────────────────────────


def compute_all_scores(
    filings: List[SECFiling],
    historical_summary: Optional[Dict] = None,
) -> StructuralScores:
    """Compute all 9 structural scores + derived structural trap risk."""
    scores = StructuralScores(
        dilution_probability_score=dilution_probability(filings),
        toxic_financing_score=toxic_financing(filings),
        warrant_overhang_score=warrant_overhang(filings),
        cash_runway_score=cash_runway(filings),
        survival_risk_score=survival_risk(filings),
        balance_sheet_quality_score=balance_sheet_quality(filings),
        offering_risk_score=offering_risk(filings),
        capital_raise_probability=capital_raise_probability(filings),
        reverse_split_risk_score=reverse_split_risk(filings),
    )

    behavior = DilutionBehavior.CLEAN_STRUCTURE
    if historical_summary:
        scores.historical_dilution_behavior_score = float(
            historical_summary.get("historical_dilution_behavior_score", 0.0)
        )
        behavior = historical_summary.get("dilution_behavior", behavior)

    scores.structural_trap_risk_score = structural_trap_risk(scores, behavior)
    # historical_structure_similarity_score is filled in by the orchestrator
    # (which has access to historical archetypes).
    return scores


def derive_action_and_sentiment(
    filings: List[SECFiling],
    scores: StructuralScores,
) -> tuple:
    sentiment = _aggregate_sentiment(filings)
    action = _oracle_action(scores, sentiment)
    return sentiment, action


__all__ = [
    "compute_all_scores",
    "derive_action_and_sentiment",
    "dilution_probability",
    "toxic_financing",
    "warrant_overhang",
    "cash_runway",
    "survival_risk",
    "balance_sheet_quality",
    "offering_risk",
    "capital_raise_probability",
    "reverse_split_risk",
    "structural_trap_risk",
]
