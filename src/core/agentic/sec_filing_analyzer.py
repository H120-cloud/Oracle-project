"""
SEC Filing NLP Analyzer (V23)

Pure-text classifier: takes the raw text of an SEC filing and returns the
extracted signals + a per-filing sentiment + materiality score.

Implementation uses curated regex + keyword bundles. It does NOT require
network access, ML libraries, or LLMs — making it deterministic, cheap,
and exhaustively testable. Each signal carries enough text snippets that
we can later upgrade to embeddings without changing the public API.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from src.core.agentic.sec_filing_models import (
    DilutionEvent,
    FilingSentiment,
    FilingType,
    PositiveStructureSignal,
    SECFiling,
    SurvivalSignal,
)


# ── Keyword bundles ─────────────────────────────────────────────────────────
# Each bundle uses lowercase substrings. Filing text is lowercased before
# matching. We use compiled regex for multi-token / proximity patterns.


DILUTION_PATTERNS: Dict[DilutionEvent, List[re.Pattern]] = {
    DilutionEvent.ATM_OFFERING: [
        re.compile(r"at[\s\-]?the[\s\-]?market\s+offering"),
        re.compile(r"\batm\s+(?:offering|program|sales? agreement)"),
        re.compile(r"sales agreement.*\bcommon stock\b.*\bplacement agent\b"),
    ],
    DilutionEvent.DIRECT_OFFERING: [
        re.compile(r"registered direct offering"),
        re.compile(r"best[\s\-]efforts\s+offering"),
    ],
    DilutionEvent.PUBLIC_OFFERING: [
        re.compile(r"underwritten public offering"),
        re.compile(r"firm commitment.*public offering"),
    ],
    DilutionEvent.PIPE: [
        re.compile(r"private investment in public equity"),
        re.compile(r"\bpipe\s+(?:financing|transaction|investors|offering)"),
        re.compile(r"securities purchase agreement.*accredited investors"),
    ],
    DilutionEvent.WARRANT_ISSUANCE: [
        re.compile(r"issuance of (?:common stock )?warrants?"),
        re.compile(r"\bpre[\s\-]?funded warrants?"),
        re.compile(r"warrants? to purchase.*shares of common stock"),
    ],
    DilutionEvent.WARRANT_EXERCISE: [
        re.compile(r"exercise of warrants?"),
        re.compile(r"warrant\s+exercises?\s+resulted"),
    ],
    DilutionEvent.CONVERTIBLE_NOTE: [
        re.compile(r"convertible (?:senior )?(?:promissory )?notes?"),
        re.compile(r"convertible debentures?"),
        re.compile(r"conversion price"),
    ],
    DilutionEvent.EQUITY_LINE: [
        re.compile(r"equity line of credit"),
        re.compile(r"standby equity (?:purchase|distribution) agreement"),
        re.compile(r"\bELOC\b"),
    ],
    DilutionEvent.TOXIC_FINANCING: [
        re.compile(r"variable conversion (?:price|rate)"),
        re.compile(r"floor price.*conversion"),
        re.compile(r"death spiral"),
        re.compile(r"reset features?"),
        re.compile(r"most favored nation"),
    ],
    DilutionEvent.SHELF_REGISTRATION: [
        re.compile(r"shelf registration"),
        re.compile(r"automatic shelf registration"),
        re.compile(r"\bs[\s\-]?3\s+registration"),
    ],
    DilutionEvent.SHARE_AUTHORIZATION_INCREASE: [
        re.compile(r"increase (?:the )?authorized (?:number of )?shares"),
        re.compile(r"amendment to.*certificate of incorporation.*authorized"),
    ],
    DilutionEvent.REVERSE_SPLIT: [
        re.compile(r"reverse stock split"),
        re.compile(r"reverse split"),
        re.compile(r"share consolidation"),
    ],
    DilutionEvent.BANKRUPTCY: [
        re.compile(r"chapter 11"),
        re.compile(r"voluntary petition.*bankruptcy"),
    ],
}


SURVIVAL_PATTERNS: Dict[SurvivalSignal, List[re.Pattern]] = {
    SurvivalSignal.GOING_CONCERN: [
        re.compile(r"going concern"),
        re.compile(r"substantial doubt.*ability to continue"),
    ],
    SurvivalSignal.LOW_CASH_RUNWAY: [
        re.compile(r"insufficient (?:cash|liquidity)"),
        re.compile(r"raise additional capital.*(?:within|next) \d+ months"),
        re.compile(r"cash.*(?:will not|may not) be sufficient"),
    ],
    SurvivalSignal.COVENANT_RISK: [
        re.compile(r"covenant (?:violation|breach|default)"),
        re.compile(r"financial covenants?.*not in compliance"),
    ],
    SurvivalSignal.DEBT_RESTRUCTURING: [
        re.compile(r"debt restructuring"),
        re.compile(r"restructure.*indebtedness"),
        re.compile(r"forbearance agreement"),
    ],
    SurvivalSignal.BANKRUPTCY_RISK: [
        re.compile(r"bankruptcy"),
        re.compile(r"chapter 7"),
        re.compile(r"liquidation"),
    ],
    SurvivalSignal.AUDITOR_WARNING: [
        re.compile(r"auditor.*expressed substantial doubt"),
        re.compile(r"qualified opinion"),
    ],
    SurvivalSignal.NASDAQ_DEFICIENCY: [
        re.compile(r"nasdaq.*deficiency"),
        re.compile(r"minimum bid price requirement"),
        re.compile(r"listing requirements"),
        re.compile(r"delisting"),
    ],
}


POSITIVE_PATTERNS: Dict[PositiveStructureSignal, List[re.Pattern]] = {
    PositiveStructureSignal.DEBT_PAYOFF: [
        re.compile(r"repaid (?:all|in full).*(?:notes?|debt|loan)"),
        re.compile(r"extinguishment of debt"),
        re.compile(r"paid off.*outstanding"),
    ],
    PositiveStructureSignal.INSIDER_BUYING: [
        re.compile(r"director.*purchased.*shares"),
        re.compile(r"chief executive officer.*purchased"),
        re.compile(r"form 4.*acquisition"),
    ],
    PositiveStructureSignal.FINANCING_COMPLETED: [
        re.compile(r"closed.*(?:financing|offering)"),
        re.compile(r"completed (?:the )?(?:private placement|public offering)"),
    ],
    PositiveStructureSignal.WARRANT_CLEANUP: [
        re.compile(r"warrant exchange"),
        re.compile(r"warrants? (?:were )?exercised in full"),
        re.compile(r"cancellation of warrants?"),
    ],
    PositiveStructureSignal.REDUCED_LIABILITIES: [
        re.compile(r"reduced (?:total )?liabilities"),
        re.compile(r"decrease in.*long[\s\-]term debt"),
    ],
    PositiveStructureSignal.IMPROVED_CASH: [
        re.compile(r"cash (?:and cash equivalents )?increased"),
        re.compile(r"strengthened.*balance sheet"),
        re.compile(r"runway (?:into|through) (?:20\d{2})"),
    ],
    PositiveStructureSignal.BUYBACK_AUTHORIZATION: [
        re.compile(r"share (?:re)?purchase program"),
        re.compile(r"stock buyback"),
        re.compile(r"board of directors authorized.*repurchase"),
    ],
}


# ── Structured numeric extractors ───────────────────────────────────────────


_DOLLAR_RE = re.compile(r"\$([\d,]+(?:\.\d+)?)\s*(million|billion|thousand)?", re.IGNORECASE)
_SHARES_RE = re.compile(r"([\d,]+(?:\.\d+)?)\s*(million|billion|thousand)?\s+shares", re.IGNORECASE)
_CASH_BALANCE_RE = re.compile(
    r"cash(?:\s+and\s+cash\s+equivalents)?\s+(?:of|totaled|were|was)\s+\$([\d,]+(?:\.\d+)?)\s*(million|billion|thousand)?",
    re.IGNORECASE,
)


def _scale_to_usd(amount: float, unit: Optional[str]) -> float:
    unit = (unit or "").lower()
    if unit.startswith("billion"):
        return amount * 1_000_000_000
    if unit.startswith("million"):
        return amount * 1_000_000
    if unit.startswith("thousand"):
        return amount * 1_000
    return amount


def _parse_first_dollar(text: str) -> Optional[float]:
    m = _DOLLAR_RE.search(text)
    if not m:
        return None
    try:
        amt = float(m.group(1).replace(",", ""))
    except ValueError:
        return None
    return _scale_to_usd(amt, m.group(2))


def _parse_cash_balance(text: str) -> Optional[float]:
    m = _CASH_BALANCE_RE.search(text)
    if not m:
        return None
    try:
        amt = float(m.group(1).replace(",", ""))
    except ValueError:
        return None
    return _scale_to_usd(amt, m.group(2))


# ── Main analyzer ───────────────────────────────────────────────────────────


@dataclass
class AnalyzerResult:
    dilution_events: List[DilutionEvent]
    survival_signals: List[SurvivalSignal]
    positive_signals: List[PositiveStructureSignal]
    filing_sentiment: FilingSentiment
    filing_materiality_score: float
    offering_amount_usd: Optional[float]
    cash_balance_usd: Optional[float]
    why_it_matters: str


def _detect(patterns: Dict, text: str) -> List:
    found = []
    for key, regexes in patterns.items():
        for rx in regexes:
            if rx.search(text):
                found.append(key)
                break
    return found


def _materiality_score(
    filing_type: FilingType,
    dilution: List[DilutionEvent],
    survival: List[SurvivalSignal],
    positive: List[PositiveStructureSignal],
) -> float:
    """Compute filing materiality 0-100."""
    base = {
        FilingType.S_1: 70.0,
        FilingType.S_3: 60.0,
        FilingType.S_3_ASR: 55.0,
        FilingType.F_424B5: 85.0,
        FilingType.F_424B4: 80.0,
        FilingType.F_424B3: 75.0,
        FilingType.F_424B2: 75.0,
        FilingType.EIGHT_K: 50.0,
        FilingType.TEN_Q: 40.0,
        FilingType.TEN_K: 45.0,
        FilingType.DEF_14A: 35.0,
        FilingType.PRE_14A: 35.0,
        FilingType.FORM_4: 25.0,
        FilingType.SC_13D: 50.0,
        FilingType.SC_13G: 30.0,
        FilingType.NT_10K: 60.0,
        FilingType.NT_10Q: 55.0,
    }.get(filing_type, 30.0)

    # Boost for high-impact signals
    if DilutionEvent.TOXIC_FINANCING in dilution:
        base += 25
    if DilutionEvent.REVERSE_SPLIT in dilution:
        base += 20
    if DilutionEvent.ATM_OFFERING in dilution:
        base += 15
    if DilutionEvent.PIPE in dilution:
        base += 10
    if SurvivalSignal.GOING_CONCERN in survival:
        base += 25
    if SurvivalSignal.BANKRUPTCY_RISK in survival:
        base += 30
    if SurvivalSignal.NASDAQ_DEFICIENCY in survival:
        base += 15

    if PositiveStructureSignal.DEBT_PAYOFF in positive:
        base += 10
    if PositiveStructureSignal.IMPROVED_CASH in positive:
        base += 8

    return float(max(0.0, min(100.0, base)))


def _sentiment(
    dilution: List[DilutionEvent],
    survival: List[SurvivalSignal],
    positive: List[PositiveStructureSignal],
) -> FilingSentiment:
    """Map detected signals to a 5-level sentiment."""
    very_neg_signals = (
        DilutionEvent.TOXIC_FINANCING in dilution
        or SurvivalSignal.GOING_CONCERN in survival
        or SurvivalSignal.BANKRUPTCY_RISK in survival
        or DilutionEvent.REVERSE_SPLIT in dilution
    )
    neg_signals = bool(dilution) or bool(survival)
    very_pos_signals = (
        PositiveStructureSignal.DEBT_PAYOFF in positive
        or PositiveStructureSignal.BUYBACK_AUTHORIZATION in positive
        or PositiveStructureSignal.WARRANT_CLEANUP in positive
    )
    pos_signals = bool(positive)

    if very_neg_signals:
        return FilingSentiment.VERY_NEGATIVE
    if very_pos_signals and not neg_signals:
        return FilingSentiment.VERY_POSITIVE
    if neg_signals and not pos_signals:
        return FilingSentiment.NEGATIVE
    if pos_signals and not neg_signals:
        return FilingSentiment.POSITIVE
    return FilingSentiment.NEUTRAL


def _build_why_it_matters(
    filing_type: FilingType,
    dilution: List[DilutionEvent],
    survival: List[SurvivalSignal],
    positive: List[PositiveStructureSignal],
) -> str:
    """Plain-English explanation for UI / Telegram."""
    parts: List[str] = []
    if SurvivalSignal.GOING_CONCERN in survival:
        parts.append("Auditor flagged going concern — survival risk is real.")
    if DilutionEvent.TOXIC_FINANCING in dilution:
        parts.append("Toxic financing terms detected (variable conversion / reset).")
    if DilutionEvent.ATM_OFFERING in dilution:
        parts.append("Active ATM program — every spike likely sold into.")
    if DilutionEvent.REVERSE_SPLIT in dilution:
        parts.append("Reverse split in motion — almost always negative for momentum.")
    if DilutionEvent.PIPE in dilution:
        parts.append("PIPE financing — expect immediate dilution pressure.")
    if DilutionEvent.SHELF_REGISTRATION in dilution and filing_type == FilingType.S_3:
        parts.append("Shelf registered — company can issue stock at any time.")
    if DilutionEvent.WARRANT_ISSUANCE in dilution:
        parts.append("New warrants issued — overhang caps continuation.")
    if SurvivalSignal.NASDAQ_DEFICIENCY in survival:
        parts.append("Nasdaq listing risk — reverse split likely to follow.")
    if PositiveStructureSignal.DEBT_PAYOFF in positive:
        parts.append("Debt paid off — balance sheet improving.")
    if PositiveStructureSignal.IMPROVED_CASH in positive:
        parts.append("Cash position improved — extended runway.")
    if PositiveStructureSignal.BUYBACK_AUTHORIZATION in positive:
        parts.append("Buyback authorized — shareholder-friendly signal.")
    if PositiveStructureSignal.INSIDER_BUYING in positive:
        parts.append("Insider buying — alignment with shareholders.")
    if not parts:
        return f"{filing_type.value} filing — no major structural signals detected."
    return " ".join(parts)


def analyze_filing_text(filing: SECFiling, text: str) -> AnalyzerResult:
    """Run the full analyzer over the filing's raw text."""
    lower = (text or "").lower()

    dilution = _detect(DILUTION_PATTERNS, lower)
    survival = _detect(SURVIVAL_PATTERNS, lower)
    positive = _detect(POSITIVE_PATTERNS, lower)

    # Filing-type heuristic boosts — even with no text, an S-3 + 424B5 is dilutive
    if filing.filing_type in (FilingType.F_424B5, FilingType.F_424B4):
        if DilutionEvent.PUBLIC_OFFERING not in dilution:
            dilution.append(DilutionEvent.PUBLIC_OFFERING)
    if filing.filing_type == FilingType.S_3 and DilutionEvent.SHELF_REGISTRATION not in dilution:
        dilution.append(DilutionEvent.SHELF_REGISTRATION)

    offering = _parse_first_dollar(lower) if dilution else None
    cash_balance = _parse_cash_balance(lower)

    sentiment = _sentiment(dilution, survival, positive)
    materiality = _materiality_score(filing.filing_type, dilution, survival, positive)
    why = _build_why_it_matters(filing.filing_type, dilution, survival, positive)

    return AnalyzerResult(
        dilution_events=dilution,
        survival_signals=survival,
        positive_signals=positive,
        filing_sentiment=sentiment,
        filing_materiality_score=materiality,
        offering_amount_usd=offering,
        cash_balance_usd=cash_balance,
        why_it_matters=why,
    )


def apply_analysis_to_filing(filing: SECFiling, text: str) -> SECFiling:
    """Run the analyzer and return a populated copy of the filing."""
    result = analyze_filing_text(filing, text)
    filing.dilution_events = result.dilution_events
    filing.survival_signals = result.survival_signals
    filing.positive_signals = result.positive_signals
    filing.filing_sentiment = result.filing_sentiment
    filing.filing_materiality_score = result.filing_materiality_score
    if result.offering_amount_usd is not None:
        filing.offering_amount_usd = result.offering_amount_usd
    if result.cash_balance_usd is not None:
        filing.cash_balance_usd = result.cash_balance_usd
    filing.why_it_matters = result.why_it_matters
    filing.raw_text_excerpt = (text or "")[:3000]
    return filing


__all__ = [
    "AnalyzerResult",
    "analyze_filing_text",
    "apply_analysis_to_filing",
    "DILUTION_PATTERNS",
    "SURVIVAL_PATTERNS",
    "POSITIVE_PATTERNS",
]
