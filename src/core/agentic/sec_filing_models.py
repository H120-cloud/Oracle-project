"""
SEC Filing Intelligence — Data Models (V23)

All Pydantic models, enums, and score containers for the SEC Filing
Intelligence & Dilution Risk Engine. Pure data definitions only — no I/O,
no scoring logic. Keep this file small and import-safe.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


# ── Enums ───────────────────────────────────────────────────────────────────


class FilingType(str, Enum):
    """SEC filing form types we care about."""
    S_1 = "S-1"
    S_3 = "S-3"
    S_3_ASR = "S-3ASR"
    F_1 = "F-1"
    F_3 = "F-3"
    F_424B5 = "424B5"
    F_424B4 = "424B4"
    F_424B3 = "424B3"
    F_424B2 = "424B2"
    EIGHT_K = "8-K"
    SIX_K = "6-K"
    TEN_Q = "10-Q"
    TEN_K = "10-K"
    TWENTY_F = "20-F"
    DEF_14A = "DEF 14A"
    PRE_14A = "PRE 14A"
    SC_13D = "SCHEDULE 13D"
    SC_13G = "SCHEDULE 13G"
    FORM_4 = "4"
    FORM_3 = "3"
    NT_10K = "NT 10-K"
    NT_10Q = "NT 10-Q"
    UNKNOWN = "UNKNOWN"


class DilutionEvent(str, Enum):
    """Specific dilution-event types extracted from filing text."""
    ATM_OFFERING = "atm_offering"
    DIRECT_OFFERING = "direct_offering"
    PUBLIC_OFFERING = "public_offering"
    PIPE = "pipe_financing"
    WARRANT_ISSUANCE = "warrant_issuance"
    WARRANT_EXERCISE = "warrant_exercise"
    CONVERTIBLE_NOTE = "convertible_note"
    EQUITY_LINE = "equity_line_financing"
    TOXIC_FINANCING = "toxic_financing"
    SHELF_REGISTRATION = "shelf_registration"
    SHARE_AUTHORIZATION_INCREASE = "share_authorization_increase"
    REVERSE_SPLIT = "reverse_split"
    BANKRUPTCY = "bankruptcy"


class SurvivalSignal(str, Enum):
    """Survival-risk signals extracted from filing text."""
    GOING_CONCERN = "going_concern_warning"
    LOW_CASH_RUNWAY = "low_cash_runway"
    COVENANT_RISK = "covenant_risk"
    DEBT_RESTRUCTURING = "debt_restructuring"
    BANKRUPTCY_RISK = "bankruptcy_risk"
    AUDITOR_WARNING = "auditor_warning"
    NASDAQ_DEFICIENCY = "nasdaq_deficiency"


class PositiveStructureSignal(str, Enum):
    """Positive balance-sheet signals."""
    DEBT_PAYOFF = "debt_payoff"
    INSIDER_BUYING = "insider_buying"
    FINANCING_COMPLETED = "financing_completed"
    WARRANT_CLEANUP = "warrant_cleanup"
    REDUCED_LIABILITIES = "reduced_liabilities"
    IMPROVED_CASH = "improved_cash_position"
    BUYBACK_AUTHORIZATION = "buyback_authorization"


class FilingSentiment(str, Enum):
    VERY_POSITIVE = "very_positive"
    POSITIVE = "positive"
    NEUTRAL = "neutral"
    NEGATIVE = "negative"
    VERY_NEGATIVE = "very_negative"


class DilutionBehavior(str, Enum):
    CLEAN_STRUCTURE = "clean_structure"
    OCCASIONAL_DILUTION = "occasional_dilution"
    SERIAL_DILUTER = "serial_diluter"
    TOXIC_DILUTION_PATTERN = "toxic_dilution_pattern"


class OracleStructuralAction(str, Enum):
    TRADEABLE = "tradeable"
    SWING_WATCH = "swing_watch"
    CAUTION = "caution"
    AVOID_CHASE = "avoid_chase"
    STRUCTURAL_TRAP = "structural_trap"


# ── Atomic filing record ────────────────────────────────────────────────────


class SECFiling(BaseModel):
    """A single SEC filing (raw metadata + extracted signals)."""

    accession_number: str
    ticker: str
    cik: Optional[str] = None
    filing_type: FilingType = FilingType.UNKNOWN
    filing_date: datetime
    title: str = ""
    summary: str = ""

    # Raw fetched content (truncated to keep payloads small)
    raw_text_excerpt: str = ""
    url: Optional[str] = None

    # Extracted signals
    dilution_events: List[DilutionEvent] = Field(default_factory=list)
    survival_signals: List[SurvivalSignal] = Field(default_factory=list)
    positive_signals: List[PositiveStructureSignal] = Field(default_factory=list)

    # Per-filing scores
    filing_sentiment: FilingSentiment = FilingSentiment.NEUTRAL
    filing_materiality_score: float = 0.0  # 0-100

    # Optional structured fields parsed from the filing
    offering_amount_usd: Optional[float] = None
    share_count_after: Optional[int] = None
    share_count_before: Optional[int] = None
    warrants_outstanding: Optional[int] = None
    convertibles_outstanding: Optional[float] = None
    cash_balance_usd: Optional[float] = None
    quarterly_burn_usd: Optional[float] = None

    # Human-readable summary for UI / Telegram
    why_it_matters: str = ""

    # Bookkeeping
    discovered_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ── Structural scoring container ────────────────────────────────────────────


class StructuralScores(BaseModel):
    """All 9 structural scores produced for a ticker (0-100 each)."""

    dilution_probability_score: float = 0.0
    toxic_financing_score: float = 0.0
    warrant_overhang_score: float = 0.0
    cash_runway_score: float = 0.0          # higher = healthier (more runway)
    survival_risk_score: float = 0.0
    balance_sheet_quality_score: float = 0.0  # higher = healthier
    offering_risk_score: float = 0.0
    capital_raise_probability: float = 0.0
    reverse_split_risk_score: float = 0.0

    # Derived
    structural_trap_risk_score: float = 0.0
    historical_dilution_behavior_score: float = 0.0  # 0=clean, 100=toxic
    historical_structure_similarity_score: float = 0.0


# ── Per-ticker SEC intelligence candidate ───────────────────────────────────


class SECIntelligenceCandidate(BaseModel):
    """A ticker analysed by the SEC intelligence engine.

    Combines: latest scores, recent filings, classification, and a
    human-readable summary that the momentum engine / Telegram alerts
    can consume directly.
    """

    ticker: str
    cik: Optional[str] = None
    company_name: str = ""

    # Latest snapshot of scores
    scores: StructuralScores = Field(default_factory=StructuralScores)

    # Classification
    dilution_behavior: DilutionBehavior = DilutionBehavior.CLEAN_STRUCTURE
    overall_filing_sentiment: FilingSentiment = FilingSentiment.NEUTRAL
    oracle_action: OracleStructuralAction = OracleStructuralAction.TRADEABLE

    # Recent filings (most recent first)
    recent_filings: List[SECFiling] = Field(default_factory=list)

    # Structured share-count history (date -> share_count)
    share_history: Dict[str, int] = Field(default_factory=dict)

    # Historical dilution stats
    offerings_last_12mo: int = 0
    reverse_splits_last_36mo: int = 0
    share_growth_pct_12mo: float = 0.0
    atm_active: bool = False
    going_concern_active: bool = False

    # Human-readable
    sec_summary: str = ""
    why_it_matters: str = ""

    # Bookkeeping
    last_updated: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ── Outcome / learning records ──────────────────────────────────────────────


class StructuralAlertOutcome(BaseModel):
    """Records whether a structural assessment was accurate."""

    ticker: str
    assessed_at: datetime
    assessed_action: OracleStructuralAction
    assessed_dilution_score: float
    assessed_trap_score: float

    # Resolved outcome
    dilution_occurred_within_30d: Optional[bool] = None
    offering_announced_within_30d: Optional[bool] = None
    reverse_split_within_60d: Optional[bool] = None
    price_at_assessment: Optional[float] = None
    price_30d_later: Optional[float] = None
    max_drawdown_30d: Optional[float] = None

    resolved: bool = False
    resolved_at: Optional[datetime] = None


# ── Cross-analysis output (momentum × SEC) ──────────────────────────────────


class StructuralAdjustment(BaseModel):
    """Adjustments the SEC engine recommends applying to momentum scores."""

    expected_return_delta: float = 0.0          # add/subtract from score
    continuation_probability_delta: float = 0.0
    multi_day_continuation_delta: float = 0.0
    trap_risk_delta: float = 0.0
    exhaustion_probability_delta: float = 0.0
    dilution_risk_delta: float = 0.0

    reasons: List[str] = Field(default_factory=list)
    veto_alert: bool = False
    veto_reason: str = ""


__all__ = [
    "FilingType",
    "DilutionEvent",
    "SurvivalSignal",
    "PositiveStructureSignal",
    "FilingSentiment",
    "DilutionBehavior",
    "OracleStructuralAction",
    "SECFiling",
    "StructuralScores",
    "SECIntelligenceCandidate",
    "StructuralAlertOutcome",
    "StructuralAdjustment",
]
