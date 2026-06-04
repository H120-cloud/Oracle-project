"""
News Catalyst Impact Engine — V20

Classifies news catalysts into specific types, scores their potential
impact on price (0-100), estimates plausible move ranges, and generates
plain-English bull/bear case explanations.

This engine is *advisory* — it never auto-triggers trades. It feeds
into the existing Agentic pipeline (pre-news → probability → risk
rules → ABCD → entry timing → ML advisory → final alert decision).

Design goals:
- Pure-Python, no external API dependency at scoring time.
- Reuses existing CatalystType enum where possible, extends with
  fine-grained sub-types via NewsCatalystType.
- Deterministic, testable scoring functions.
- Plain-English bull_case / bear_case strings.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from src.core.agentic.models import AgenticCandidate

logger = logging.getLogger(__name__)


# ── Fine-grained catalyst classification ────────────────────────────────────


class NewsCatalystType(str, Enum):
    """Fine-grained catalyst classification used by the Impact Engine.

    These extend (do not replace) the broader CatalystType enum used
    by the Catalyst Scanner.
    """
    FDA_APPROVAL = "fda_approval"
    FDA_CLEARANCE = "fda_clearance"
    PDUFA_DATE = "pdufa_date"
    PHASE_1 = "phase_1"
    PHASE_2 = "phase_2"
    PHASE_3 = "phase_3"
    FAST_TRACK = "fast_track"
    BREAKTHROUGH_THERAPY = "breakthrough_therapy"
    ORPHAN_DRUG = "orphan_drug"
    EARNINGS_BEAT = "earnings_beat"
    GUIDANCE_RAISE = "guidance_raise"
    PROFITABILITY_INFLECTION = "profitability_inflection"
    MAJOR_CONTRACT = "major_contract"
    GOVERNMENT_CONTRACT = "government_contract"
    AI_PARTNERSHIP = "ai_partnership"
    HYPERSCALER_PARTNERSHIP = "hyperscaler_partnership"
    CRYPTO_TREASURY = "crypto_treasury"
    MERGER_ACQUISITION = "merger_acquisition"
    BUYOUT_OFFER = "buyout_offer"
    PATENT_WIN = "patent_win"
    LICENSING_AGREEMENT = "licensing_agreement"
    ANALYST_UPGRADE = "analyst_upgrade"
    NASDAQ_COMPLIANCE = "nasdaq_compliance_regained"
    REVERSE_SPLIT = "reverse_split"
    DELISTING_WARNING = "delisting_warning"
    OFFERING_DILUTION = "offering_dilution"
    ATM_FILING = "atm_filing"
    WARRANT_EXERCISE = "warrant_exercise"
    INSIDER_BUYING = "insider_buying"
    DEBT_RESTRUCTURING = "debt_restructuring"
    STRATEGIC_REVIEW = "strategic_review"
    VAGUE_PR = "vague_pr"
    OTHER = "other"


class NewsDecision(str, Enum):
    """Top-level qualitative decision for a news catalyst."""
    IGNORE = "IGNORE"
    WATCH = "WATCH"
    TRADEABLE = "TRADEABLE"
    HIGH_IMPACT = "HIGH_IMPACT"
    EXPLOSIVE = "EXPLOSIVE"
    DANGEROUS_TRAP = "DANGEROUS_TRAP"


class OracleAction(str, Enum):
    """Recommended user action for a news catalyst."""
    WATCH = "WATCH"
    WAIT_FOR_RETEST = "WAIT_FOR_RETEST"
    TRADEABLE = "TRADEABLE"
    AVOID_TRAP = "AVOID_TRAP"
    AVOID_CHASING = "AVOID_CHASING"
    IGNORE = "IGNORE"


# ── Keyword maps for classification ─────────────────────────────────────────
#
# Order matters: the first regex that matches wins. Keep the most specific
# patterns near the top.

_KEYWORD_PATTERNS: list[tuple[NewsCatalystType, re.Pattern]] = [
    # FDA / biotech
    (NewsCatalystType.FDA_APPROVAL, re.compile(r"\bfda\s+(approve|approval|approves|approved)\b", re.I)),
    (NewsCatalystType.FDA_CLEARANCE, re.compile(r"\bfda\s+(clearance|clears|cleared|510\(k\))\b", re.I)),
    (NewsCatalystType.PDUFA_DATE, re.compile(r"\bpdufa\b", re.I)),
    (NewsCatalystType.BREAKTHROUGH_THERAPY, re.compile(r"\bbreakthrough\s+(therapy|designation)\b", re.I)),
    (NewsCatalystType.FAST_TRACK, re.compile(r"\bfast\s+track\b", re.I)),
    (NewsCatalystType.ORPHAN_DRUG, re.compile(r"\borphan\s+drug\b", re.I)),
    (NewsCatalystType.PHASE_3, re.compile(r"\bphase\s*(?:iii|3)\b", re.I)),
    (NewsCatalystType.PHASE_2, re.compile(r"\bphase\s*(?:ii|2)\b", re.I)),
    (NewsCatalystType.PHASE_1, re.compile(r"\bphase\s*(?:i|1)\b", re.I)),
    # M&A
    (NewsCatalystType.BUYOUT_OFFER, re.compile(r"\b(buyout\s+offer|tender\s+offer|to\s+acquire\s+for|cash\s+offer)\b", re.I)),
    (NewsCatalystType.MERGER_ACQUISITION, re.compile(r"\b(merger|acquisition|acquires|to\s+acquire|acquired\s+by|to\s+merge)\b", re.I)),
    # Earnings
    (NewsCatalystType.GUIDANCE_RAISE, re.compile(r"\b(raises?\s+guidance|raised\s+guidance|increases?\s+guidance|raises?\s+outlook|raises?\s+forecast)\b", re.I)),
    (NewsCatalystType.EARNINGS_BEAT, re.compile(r"\b(beats?\s+(estimates|consensus|expectations)|earnings\s+beat|tops?\s+estimates|exceeds?\s+expectations)\b", re.I)),
    (NewsCatalystType.PROFITABILITY_INFLECTION, re.compile(r"\b(swings?\s+to\s+profit|first\s+profitable\s+quarter|reports?\s+first\s+profit|achieves?\s+profitability)\b", re.I)),
    # Contracts / partnerships
    (NewsCatalystType.GOVERNMENT_CONTRACT, re.compile(r"\b(department\s+of\s+defense|pentagon|dod\s+contract|government\s+contract|federal\s+contract|navy\s+contract|army\s+contract|air\s+force\s+contract)\b", re.I)),
    (NewsCatalystType.HYPERSCALER_PARTNERSHIP, re.compile(r"\b(nvidia|microsoft\s+azure|amazon\s+aws|google\s+cloud|openai|anthropic|hyperscaler)\b.*\b(partnership|deal|agreement|contract|to\s+power|integrates?\s+with)\b", re.I)),
    (NewsCatalystType.AI_PARTNERSHIP, re.compile(r"\bai\b.*\b(partnership|agreement|deal|integration|collaboration)\b", re.I)),
    (NewsCatalystType.MAJOR_CONTRACT, re.compile(r"\b(\$\d+\s*(million|billion|m|b)\s+contract|major\s+contract|awarded\s+contract|contract\s+award)\b", re.I)),
    (NewsCatalystType.LICENSING_AGREEMENT, re.compile(r"\blicensing\s+(agreement|deal)\b", re.I)),
    # Crypto
    (NewsCatalystType.CRYPTO_TREASURY, re.compile(r"\b(bitcoin\s+treasury|btc\s+treasury|adds?\s+bitcoin|crypto\s+treasury|ethereum\s+treasury|adds?\s+\d+\s+bitcoin)\b", re.I)),
    # Patents / legal
    (NewsCatalystType.PATENT_WIN, re.compile(r"\b(patent\s+(win|granted|awarded|infringement\s+ruling)|wins?\s+patent|patent\s+approved)\b", re.I)),
    # Analyst
    (NewsCatalystType.ANALYST_UPGRADE, re.compile(r"\b(analyst\s+upgrade|upgraded\s+to\s+(buy|outperform|overweight)|raised\s+(price\s+target|pt))\b", re.I)),
    # Compliance / structure (often bearish)
    (NewsCatalystType.NASDAQ_COMPLIANCE, re.compile(r"\b(regains?\s+(nasdaq\s+)?compliance|compliance\s+regained)\b", re.I)),
    (NewsCatalystType.DELISTING_WARNING, re.compile(r"\b(delisting\s+(warning|notice)|noncompliance|deficiency\s+notice|minimum\s+bid\s+price)\b", re.I)),
    (NewsCatalystType.REVERSE_SPLIT, re.compile(r"\breverse\s+(stock\s+)?split\b", re.I)),
    # Dilution
    (NewsCatalystType.ATM_FILING, re.compile(r"\b(at-?the-?market|atm\s+offering|atm\s+facility)\b", re.I)),
    (NewsCatalystType.OFFERING_DILUTION, re.compile(r"\b(public\s+offering|secondary\s+offering|registered\s+direct|pipe\s+(financing|deal)|priced\s+offering|shelf\s+registration|share\s+offering|pricing\s+of)\b", re.I)),
    (NewsCatalystType.WARRANT_EXERCISE, re.compile(r"\bwarrant\s+(exercise|inducement|repricing)\b", re.I)),
    # Insider / debt
    (NewsCatalystType.INSIDER_BUYING, re.compile(r"\b(insider\s+(buy|buying|purchase)|director\s+buys?|ceo\s+buys?)\b", re.I)),
    (NewsCatalystType.DEBT_RESTRUCTURING, re.compile(r"\b(debt\s+restructur|refinanc|debt\s+exchange|note\s+exchange)\b", re.I)),
    (NewsCatalystType.STRATEGIC_REVIEW, re.compile(r"\b(strategic\s+(review|alternatives)|exploring\s+alternatives)\b", re.I)),
    # Vague/promotional
    (NewsCatalystType.VAGUE_PR, re.compile(r"\b(announces?\s+update|provides?\s+update|corporate\s+update|attends?\s+conference|to\s+present\s+at|investor\s+conference|comments?\s+on|congratulates?)\b", re.I)),
]


# ── Sector hype multipliers ─────────────────────────────────────────────────


SECTOR_HYPE_MULTIPLIER: dict[str, float] = {
    "biotech": 1.20,
    "pharmaceutical": 1.18,
    "ai": 1.20,
    "artificial intelligence": 1.20,
    "quantum": 1.25,
    "crypto": 1.18,
    "blockchain": 1.15,
    "defense": 1.12,
    "uranium": 1.18,
    "nuclear": 1.15,
    "obesity": 1.15,
    "weight loss": 1.15,
    "energy": 1.05,
    "solar": 1.05,
    "ev": 1.05,
}


# ── Catalyst tiers ──────────────────────────────────────────────────────────
#
# Each catalyst type maps to a "materiality" score (0-100). This represents
# the *raw* impact a catalyst can have on a company's outlook before any
# context (float, market cap, sector, position) is applied.

CATALYST_MATERIALITY: dict[NewsCatalystType, int] = {
    NewsCatalystType.FDA_APPROVAL: 95,
    NewsCatalystType.PHASE_3: 90,
    NewsCatalystType.BUYOUT_OFFER: 90,
    NewsCatalystType.MERGER_ACQUISITION: 85,
    NewsCatalystType.PHASE_2: 80,
    NewsCatalystType.BREAKTHROUGH_THERAPY: 80,
    NewsCatalystType.FDA_CLEARANCE: 70,
    NewsCatalystType.PDUFA_DATE: 70,
    NewsCatalystType.GUIDANCE_RAISE: 75,
    NewsCatalystType.EARNINGS_BEAT: 70,
    NewsCatalystType.PROFITABILITY_INFLECTION: 80,
    NewsCatalystType.GOVERNMENT_CONTRACT: 75,
    NewsCatalystType.HYPERSCALER_PARTNERSHIP: 80,
    NewsCatalystType.AI_PARTNERSHIP: 65,
    NewsCatalystType.MAJOR_CONTRACT: 65,
    NewsCatalystType.CRYPTO_TREASURY: 60,
    NewsCatalystType.PATENT_WIN: 55,
    NewsCatalystType.LICENSING_AGREEMENT: 55,
    NewsCatalystType.FAST_TRACK: 60,
    NewsCatalystType.ORPHAN_DRUG: 55,
    NewsCatalystType.PHASE_1: 50,
    NewsCatalystType.ANALYST_UPGRADE: 45,
    NewsCatalystType.NASDAQ_COMPLIANCE: 40,
    NewsCatalystType.INSIDER_BUYING: 50,
    NewsCatalystType.DEBT_RESTRUCTURING: 40,
    NewsCatalystType.STRATEGIC_REVIEW: 50,
    NewsCatalystType.WARRANT_EXERCISE: 25,
    NewsCatalystType.OFFERING_DILUTION: 20,
    NewsCatalystType.ATM_FILING: 20,
    NewsCatalystType.REVERSE_SPLIT: 15,
    NewsCatalystType.DELISTING_WARNING: 15,
    NewsCatalystType.VAGUE_PR: 20,
    NewsCatalystType.OTHER: 35,
}


# Catalyst types that are intrinsically bearish (price-negative)
BEARISH_CATALYSTS = {
    NewsCatalystType.OFFERING_DILUTION,
    NewsCatalystType.ATM_FILING,
    NewsCatalystType.WARRANT_EXERCISE,
    NewsCatalystType.REVERSE_SPLIT,
    NewsCatalystType.DELISTING_WARNING,
}


# ── Result dataclasses ──────────────────────────────────────────────────────


@dataclass
class EstimatedMoveRange:
    """Plausible move ranges based on catalyst + context.

    All values are percent (e.g. 30.0 = +30%). Negative values for bearish
    catalysts. extreme_squeeze_pct is reserved for low-float / no-dilution
    explosive setups.
    """
    conservative_move_pct: float = 0.0
    bullish_move_pct: float = 0.0
    extreme_squeeze_pct: float = 0.0
    bearish_move_pct: float = 0.0  # used for offering / dilution / trap
    rationale: str = ""

    def to_dict(self) -> dict:
        return {
            "conservative_move_pct": round(self.conservative_move_pct, 1),
            "bullish_move_pct": round(self.bullish_move_pct, 1),
            "extreme_squeeze_pct": round(self.extreme_squeeze_pct, 1),
            "bearish_move_pct": round(self.bearish_move_pct, 1),
            "rationale": self.rationale,
        }


@dataclass
class NewsImpactResult:
    """Full output of the News Catalyst Impact Engine."""

    ticker: str = ""
    headline: str = ""
    source: str = ""
    detected_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # Classification
    catalyst_type: NewsCatalystType = NewsCatalystType.OTHER
    catalyst_tier: str = "low"  # low / medium / high / extreme

    # Scoring
    news_impact_score: float = 0.0  # 0-100
    component_scores: dict = field(default_factory=dict)

    # Decision
    news_decision: NewsDecision = NewsDecision.IGNORE
    oracle_action: OracleAction = OracleAction.IGNORE

    # Estimated move range
    estimated_move_range: EstimatedMoveRange = field(default_factory=EstimatedMoveRange)

    # Trap / risk flags
    is_dilution: bool = False
    is_parabolic: bool = False
    is_unconfirmed: bool = False
    trap_warning: bool = False
    trap_reasons: list[str] = field(default_factory=list)

    # Pre-news linkage
    pre_news_accumulation_detected: bool = False
    pre_news_suspicion_score: float = 0.0

    # Explanations
    news_summary: str = ""
    why_it_matters: str = ""
    bull_case: str = ""
    bear_case: str = ""
    key_risks: list[str] = field(default_factory=list)
    impact_reasons: list[str] = field(default_factory=list)
    impact_warnings: list[str] = field(default_factory=list)

    # Context snapshot at evaluation time
    market_cap_at_detection: Optional[float] = None
    float_shares_at_detection: Optional[float] = None
    rvol_at_detection: float = 0.0
    price_at_detection: Optional[float] = None
    pre_news_runup_pct: float = 0.0
    sector_hype_multiplier: float = 1.0

    def to_dict(self) -> dict:
        return {
            "ticker": self.ticker,
            "headline": self.headline,
            "source": self.source,
            "detected_at": self.detected_at.isoformat(),
            "catalyst_type": self.catalyst_type.value,
            "catalyst_tier": self.catalyst_tier,
            "news_impact_score": round(self.news_impact_score, 1),
            "component_scores": {k: round(v, 1) for k, v in self.component_scores.items()},
            "news_decision": self.news_decision.value,
            "oracle_action": self.oracle_action.value,
            "estimated_move_range": self.estimated_move_range.to_dict(),
            "is_dilution": self.is_dilution,
            "is_parabolic": self.is_parabolic,
            "is_unconfirmed": self.is_unconfirmed,
            "trap_warning": self.trap_warning,
            "trap_reasons": list(self.trap_reasons),
            "pre_news_accumulation_detected": self.pre_news_accumulation_detected,
            "pre_news_suspicion_score": round(self.pre_news_suspicion_score, 1),
            "news_summary": self.news_summary,
            "why_it_matters": self.why_it_matters,
            "bull_case": self.bull_case,
            "bear_case": self.bear_case,
            "key_risks": list(self.key_risks),
            "impact_reasons": list(self.impact_reasons),
            "impact_warnings": list(self.impact_warnings),
            "market_cap_at_detection": self.market_cap_at_detection,
            "float_shares_at_detection": self.float_shares_at_detection,
            "rvol_at_detection": round(self.rvol_at_detection, 2),
            "price_at_detection": self.price_at_detection,
            "pre_news_runup_pct": round(self.pre_news_runup_pct, 2),
            "sector_hype_multiplier": round(self.sector_hype_multiplier, 2),
        }


# ── Classifier ──────────────────────────────────────────────────────────────


def classify_news_catalyst(headline: str) -> NewsCatalystType:
    """Classify a headline into a fine-grained NewsCatalystType."""
    if not headline:
        return NewsCatalystType.OTHER
    for catalyst, pattern in _KEYWORD_PATTERNS:
        if pattern.search(headline):
            return catalyst
    return NewsCatalystType.OTHER


def detect_sector_hype(headline: str, ticker_keywords: str = "") -> tuple[str, float]:
    """Return (sector_name, multiplier) for the strongest sector match."""
    text = f"{headline} {ticker_keywords}".lower()
    best_sector = ""
    best_mult = 1.0
    for sector, mult in SECTOR_HYPE_MULTIPLIER.items():
        if sector in text and mult > best_mult:
            best_sector = sector
            best_mult = mult
    return best_sector, best_mult


# ── Component scoring functions ─────────────────────────────────────────────


def _score_materiality(catalyst: NewsCatalystType) -> float:
    return float(CATALYST_MATERIALITY.get(catalyst, 35))


def _score_market_cap(market_cap: Optional[float]) -> float:
    """Smaller cap → higher score (more sensitive to catalysts)."""
    if not market_cap or market_cap <= 0:
        return 50.0
    if market_cap < 50_000_000:
        return 95.0
    if market_cap < 200_000_000:
        return 85.0
    if market_cap < 1_000_000_000:
        return 70.0
    if market_cap < 10_000_000_000:
        return 50.0
    if market_cap < 50_000_000_000:
        return 35.0
    return 20.0


def _score_float(float_shares: Optional[float]) -> float:
    """Lower float → higher score (more momentum potential)."""
    if not float_shares or float_shares <= 0:
        return 50.0
    if float_shares < 5_000_000:
        return 95.0
    if float_shares < 20_000_000:
        return 80.0
    if float_shares < 50_000_000:
        return 65.0
    if float_shares < 200_000_000:
        return 45.0
    return 25.0


def _score_volume_confirmation(rvol: float) -> float:
    """RVOL expansion confirmation."""
    if rvol <= 0:
        return 30.0
    if rvol < 1.5:
        return 25.0
    if rvol < 3:
        return 50.0
    if rvol < 6:
        return 70.0
    if rvol < 10:
        return 85.0
    return 95.0


def _score_price_position(runup_pct: float) -> float:
    """Downgrade already-parabolic moves."""
    if runup_pct < 20:
        return 80.0
    if runup_pct < 50:
        return 65.0
    if runup_pct < 100:
        return 45.0
    if runup_pct < 200:
        return 25.0
    return 10.0


def _score_dilution_risk(catalyst: NewsCatalystType, has_offering: bool, has_warrants: bool) -> float:
    """Returns a score (high = clean, low = dilution risk)."""
    if catalyst in BEARISH_CATALYSTS:
        return 5.0
    if has_offering and has_warrants:
        return 10.0
    if has_offering:
        return 25.0
    if has_warrants:
        return 40.0
    return 85.0


def _score_pre_news(suspicion: float) -> float:
    """Direct mapping (0-100)."""
    return max(0.0, min(100.0, suspicion))


def _score_surprise(catalyst: NewsCatalystType, runup_pct: float) -> float:
    """Was the catalyst already priced in?"""
    if runup_pct > 50:
        return 25.0
    if runup_pct > 20:
        return 50.0
    return 80.0


def _score_short_squeeze(short_interest_pct: Optional[float]) -> float:
    if not short_interest_pct or short_interest_pct <= 0:
        return 30.0
    if short_interest_pct < 10:
        return 35.0
    if short_interest_pct < 20:
        return 55.0
    if short_interest_pct < 30:
        return 75.0
    return 90.0


# ── Estimated move range generation ─────────────────────────────────────────


def _estimated_move_for(
    catalyst: NewsCatalystType,
    market_cap: Optional[float],
    float_shares: Optional[float],
    sector_mult: float,
    pre_news_accumulation: bool,
) -> EstimatedMoveRange:
    """Produce a plausible move range based on catalyst + context.

    Bearish catalysts produce negative bearish_move_pct only.
    """
    rng = EstimatedMoveRange()

    # Bearish catalysts
    if catalyst in BEARISH_CATALYSTS:
        if catalyst in (NewsCatalystType.OFFERING_DILUTION, NewsCatalystType.ATM_FILING):
            rng.conservative_move_pct = -10.0
            rng.bearish_move_pct = -30.0
            if float_shares and float_shares < 20_000_000:
                rng.bearish_move_pct = -50.0
            rng.rationale = "Dilutive offering — primary risk is supply expansion"
        elif catalyst == NewsCatalystType.WARRANT_EXERCISE:
            rng.conservative_move_pct = -8.0
            rng.bearish_move_pct = -25.0
            rng.rationale = "Warrant inducement — potential overhead supply"
        elif catalyst in (NewsCatalystType.REVERSE_SPLIT, NewsCatalystType.DELISTING_WARNING):
            rng.conservative_move_pct = -15.0
            rng.bearish_move_pct = -40.0
            rng.rationale = "Compliance / structural action — historically bearish"
        return rng

    # Tier 1: explosive (FDA approval, P3, buyout)
    is_micro = (market_cap and market_cap < 50_000_000) or (float_shares and float_shares < 5_000_000)
    is_small = (market_cap and market_cap < 250_000_000) or (float_shares and float_shares < 20_000_000)

    if catalyst in (NewsCatalystType.FDA_APPROVAL, NewsCatalystType.BUYOUT_OFFER, NewsCatalystType.PHASE_3):
        if is_micro:
            rng.conservative_move_pct = 30.0
            rng.bullish_move_pct = 100.0
            rng.extreme_squeeze_pct = 300.0
            rng.rationale = "Tier-1 catalyst on micro-cap — explosive potential"
        elif is_small:
            rng.conservative_move_pct = 20.0
            rng.bullish_move_pct = 60.0
            rng.extreme_squeeze_pct = 150.0
            rng.rationale = "Tier-1 catalyst on small-cap"
        else:
            rng.conservative_move_pct = 10.0
            rng.bullish_move_pct = 25.0
            rng.extreme_squeeze_pct = 50.0
            rng.rationale = "Tier-1 catalyst on mid/large-cap"
    elif catalyst in (
        NewsCatalystType.PHASE_2,
        NewsCatalystType.BREAKTHROUGH_THERAPY,
        NewsCatalystType.MERGER_ACQUISITION,
        NewsCatalystType.PROFITABILITY_INFLECTION,
        NewsCatalystType.HYPERSCALER_PARTNERSHIP,
    ):
        if is_micro or is_small:
            rng.conservative_move_pct = 15.0
            rng.bullish_move_pct = 50.0
            rng.extreme_squeeze_pct = 120.0
        else:
            rng.conservative_move_pct = 8.0
            rng.bullish_move_pct = 20.0
            rng.extreme_squeeze_pct = 40.0
        rng.rationale = "Tier-2 high-impact catalyst"
    elif catalyst in (
        NewsCatalystType.GUIDANCE_RAISE,
        NewsCatalystType.EARNINGS_BEAT,
        NewsCatalystType.GOVERNMENT_CONTRACT,
        NewsCatalystType.MAJOR_CONTRACT,
        NewsCatalystType.AI_PARTNERSHIP,
        NewsCatalystType.PDUFA_DATE,
        NewsCatalystType.FDA_CLEARANCE,
    ):
        if is_small:
            rng.conservative_move_pct = 10.0
            rng.bullish_move_pct = 30.0
            rng.extreme_squeeze_pct = 80.0
        else:
            rng.conservative_move_pct = 5.0
            rng.bullish_move_pct = 12.0
            rng.extreme_squeeze_pct = 25.0
        rng.rationale = "Tier-3 tradeable catalyst"
    elif catalyst in (
        NewsCatalystType.CRYPTO_TREASURY,
        NewsCatalystType.PATENT_WIN,
        NewsCatalystType.LICENSING_AGREEMENT,
        NewsCatalystType.FAST_TRACK,
        NewsCatalystType.ORPHAN_DRUG,
        NewsCatalystType.PHASE_1,
        NewsCatalystType.ANALYST_UPGRADE,
        NewsCatalystType.INSIDER_BUYING,
    ):
        if is_small:
            rng.conservative_move_pct = 5.0
            rng.bullish_move_pct = 18.0
            rng.extreme_squeeze_pct = 50.0
        else:
            rng.conservative_move_pct = 2.0
            rng.bullish_move_pct = 8.0
            rng.extreme_squeeze_pct = 18.0
        rng.rationale = "Tier-4 secondary catalyst"
    else:
        rng.conservative_move_pct = 2.0
        rng.bullish_move_pct = 6.0
        rng.extreme_squeeze_pct = 12.0
        rng.rationale = "Low-tier or unclassified catalyst"

    # Apply sector hype multiplier
    if sector_mult > 1.0 and rng.bullish_move_pct > 0:
        rng.conservative_move_pct *= sector_mult
        rng.bullish_move_pct *= sector_mult
        rng.extreme_squeeze_pct *= sector_mult
        rng.rationale += f" · sector hype ×{sector_mult:.2f}"

    # Pre-news accumulation boost
    if pre_news_accumulation and rng.bullish_move_pct > 0:
        rng.conservative_move_pct *= 1.10
        rng.bullish_move_pct *= 1.20
        rng.extreme_squeeze_pct *= 1.25
        rng.rationale += " · pre-news accumulation boost"

    return rng


# ── Decision logic ──────────────────────────────────────────────────────────


def _decide_decision_and_action(
    score: float,
    catalyst: NewsCatalystType,
    is_parabolic: bool,
    is_dilution: bool,
    is_unconfirmed: bool,
    pre_news_acc: bool,
    rvol: float,
) -> tuple[NewsDecision, OracleAction]:
    """Map score + flags → final decision + action."""
    # Hard trap conditions
    if catalyst in BEARISH_CATALYSTS or is_dilution:
        return NewsDecision.DANGEROUS_TRAP, OracleAction.AVOID_TRAP

    if is_parabolic and catalyst not in (
        NewsCatalystType.FDA_APPROVAL,
        NewsCatalystType.BUYOUT_OFFER,
        NewsCatalystType.PHASE_3,
    ):
        return NewsDecision.DANGEROUS_TRAP, OracleAction.AVOID_CHASING

    if catalyst == NewsCatalystType.VAGUE_PR:
        return NewsDecision.IGNORE, OracleAction.IGNORE

    if is_unconfirmed and score < 60:
        return NewsDecision.WATCH, OracleAction.WATCH

    # Score-based gating
    if score >= 85 and rvol >= 3 and pre_news_acc:
        return NewsDecision.EXPLOSIVE, OracleAction.WAIT_FOR_RETEST

    if score >= 80 and rvol >= 2:
        return NewsDecision.EXPLOSIVE, OracleAction.WAIT_FOR_RETEST

    if score >= 70:
        return NewsDecision.HIGH_IMPACT, OracleAction.WAIT_FOR_RETEST

    if score >= 55:
        return NewsDecision.TRADEABLE, OracleAction.WATCH

    if score >= 35:
        return NewsDecision.WATCH, OracleAction.WATCH

    return NewsDecision.IGNORE, OracleAction.IGNORE


def _tier_for_score(score: float) -> str:
    if score >= 85:
        return "extreme"
    if score >= 70:
        return "high"
    if score >= 50:
        return "medium"
    return "low"


# ── Explanation builders ────────────────────────────────────────────────────


_CATALYST_SUMMARIES: dict[NewsCatalystType, str] = {
    NewsCatalystType.FDA_APPROVAL: "FDA approval grants commercial authorization for a drug or device.",
    NewsCatalystType.FDA_CLEARANCE: "FDA clearance allows the company to market a device for its intended use.",
    NewsCatalystType.PDUFA_DATE: "PDUFA date is the FDA's target decision date for a pending drug application.",
    NewsCatalystType.PHASE_3: "Phase 3 trial data is the final efficacy/safety readout before FDA submission.",
    NewsCatalystType.PHASE_2: "Phase 2 trial data establishes efficacy and dosing on a focused patient population.",
    NewsCatalystType.PHASE_1: "Phase 1 trial data is preliminary safety/PK information.",
    NewsCatalystType.BREAKTHROUGH_THERAPY: "Breakthrough Therapy Designation accelerates FDA review for promising therapies.",
    NewsCatalystType.FAST_TRACK: "Fast Track designation enables more frequent FDA interaction during development.",
    NewsCatalystType.ORPHAN_DRUG: "Orphan Drug Designation grants market exclusivity for rare-disease therapies.",
    NewsCatalystType.EARNINGS_BEAT: "Earnings beat indicates the company outperformed Wall Street estimates.",
    NewsCatalystType.GUIDANCE_RAISE: "Raised forward guidance signals improving fundamentals and analyst upgrades likely to follow.",
    NewsCatalystType.PROFITABILITY_INFLECTION: "First-time profitability is a major narrative shift for the company.",
    NewsCatalystType.MAJOR_CONTRACT: "A material contract win adds revenue visibility and validates the business.",
    NewsCatalystType.GOVERNMENT_CONTRACT: "A government contract is a high-quality, long-duration revenue stream.",
    NewsCatalystType.AI_PARTNERSHIP: "AI partnership leverages a hot sector narrative.",
    NewsCatalystType.HYPERSCALER_PARTNERSHIP: "A hyperscaler/Nvidia/OpenAI partnership signals validated demand.",
    NewsCatalystType.CRYPTO_TREASURY: "Adopting a crypto treasury reframes the company as a digital-asset proxy.",
    NewsCatalystType.MERGER_ACQUISITION: "M&A activity typically pegs the stock to deal terms.",
    NewsCatalystType.BUYOUT_OFFER: "A buyout offer caps upside near deal price absent counter-bids.",
    NewsCatalystType.PATENT_WIN: "A patent win strengthens IP moat and may settle ongoing litigation.",
    NewsCatalystType.LICENSING_AGREEMENT: "Licensing creates upfront cash + downstream royalty optionality.",
    NewsCatalystType.ANALYST_UPGRADE: "Sell-side upgrades can spark short-term momentum and inflows.",
    NewsCatalystType.NASDAQ_COMPLIANCE: "Regaining Nasdaq compliance removes an overhang but isn't fundamentally bullish.",
    NewsCatalystType.REVERSE_SPLIT: "Reverse splits historically precede further weakness; the share count action does not change fundamentals.",
    NewsCatalystType.DELISTING_WARNING: "A delisting warning signals balance-sheet stress and overhead supply pressure.",
    NewsCatalystType.OFFERING_DILUTION: "An equity offering increases share count and pressures price.",
    NewsCatalystType.ATM_FILING: "An ATM facility lets the company sell stock into strength, capping rallies.",
    NewsCatalystType.WARRANT_EXERCISE: "Warrant inducement deals dilute existing shareholders and add overhead supply.",
    NewsCatalystType.INSIDER_BUYING: "Material insider buying is a meaningful confidence signal.",
    NewsCatalystType.DEBT_RESTRUCTURING: "Debt restructuring may reduce default risk but often dilutes equity.",
    NewsCatalystType.STRATEGIC_REVIEW: "A strategic review typically precedes M&A, sale, or restructuring.",
    NewsCatalystType.VAGUE_PR: "Promotional or vague headline with no clear fundamental impact.",
    NewsCatalystType.OTHER: "Unclassified news item.",
}


def _build_explanations(
    result: NewsImpactResult,
    catalyst: NewsCatalystType,
    pre_news_acc: bool,
    rvol: float,
    runup_pct: float,
    is_dilution: bool,
    is_parabolic: bool,
    market_cap: Optional[float],
    float_shares: Optional[float],
) -> None:
    """Populate news_summary / why_it_matters / bull / bear / risks."""
    ticker = result.ticker
    headline = result.headline

    # Summary — one sentence
    result.news_summary = f"{ticker}: {headline[:140]}"

    # Why it matters
    result.why_it_matters = _CATALYST_SUMMARIES.get(catalyst, "Unclassified catalyst.")

    # Bull case
    bull_lines: list[str] = []
    bear_lines: list[str] = []
    risks: list[str] = []
    reasons: list[str] = []
    warnings: list[str] = []

    # Bullish factors
    if catalyst not in BEARISH_CATALYSTS:
        if float_shares and float_shares < 20_000_000:
            bull_lines.append("low float means even modest demand can drive outsized moves")
            reasons.append(f"Low float ({float_shares/1e6:.1f}M)")
        if market_cap and market_cap < 250_000_000:
            bull_lines.append("small market cap is highly sensitive to fundamental news")
            reasons.append(f"Small market cap (${market_cap/1e6:.0f}M)")
        if rvol >= 3:
            bull_lines.append(f"volume confirms ({rvol:.1f}x normal)")
            reasons.append(f"RVOL {rvol:.1f}x")
        if pre_news_acc:
            bull_lines.append("pre-news accumulation suggests informed buying ahead of headline")
            reasons.append("Pre-news accumulation detected")
        if result.sector_hype_multiplier > 1.05:
            bull_lines.append("sector tailwind in play")
            reasons.append(f"Sector hype ×{result.sector_hype_multiplier:.2f}")

    # Bearish factors
    if is_dilution:
        bear_lines.append("offering or warrant filing creates supply pressure")
        warnings.append("Dilution risk active")
        risks.append("dilution")
    if is_parabolic:
        bear_lines.append(f"stock already +{runup_pct:.0f}% before news — much of the move may be priced in")
        warnings.append("Already-parabolic move")
        risks.append("overextended move")
    if rvol < 1.5 and catalyst not in BEARISH_CATALYSTS:
        bear_lines.append("volume not yet confirming the move")
        warnings.append("Weak volume confirmation")
    if catalyst == NewsCatalystType.VAGUE_PR:
        bear_lines.append("headline is promotional with no clear fundamental impact")
        warnings.append("Low-quality PR")
        risks.append("no revenue impact")
    if catalyst in BEARISH_CATALYSTS:
        bear_lines.append(_CATALYST_SUMMARIES.get(catalyst, "bearish catalyst"))
        warnings.append("Bearish catalyst type")

    # Generic risk overlays
    if market_cap and market_cap < 50_000_000:
        risks.append("low liquidity")
    if result.is_unconfirmed:
        risks.append("unverified source")
        warnings.append("Source unconfirmed")

    # Compose
    result.bull_case = (
        ("Bullish: " + "; ".join(bull_lines) + ".") if bull_lines else
        "Bullish: limited evidence of imminent continuation; monitor volume + retest."
    )
    result.bear_case = (
        ("Bearish: " + "; ".join(bear_lines) + ".") if bear_lines else
        "Bearish: no specific red flags detected, but always size accordingly."
    )
    result.key_risks = risks
    result.impact_reasons = reasons
    result.impact_warnings = warnings


# ── Main engine ─────────────────────────────────────────────────────────────


class NewsImpactEngine:
    """The News Catalyst Impact Engine.

    Usage:
        engine = NewsImpactEngine()
        result = engine.evaluate(
            ticker="ABCD",
            headline="ABCD receives FDA approval for ...",
            source="Finviz",
            market_cap=45_000_000,
            float_shares=4_500_000,
            rvol=8.2,
            current_price=3.40,
            pre_news_runup_pct=15.0,
            pre_news_suspicion_score=82,
        )
        # result.news_decision == NewsDecision.EXPLOSIVE
    """

    def __init__(self):
        # Component weights — must sum to ~1.0
        self.weights = {
            "materiality": 0.28,
            "market_cap": 0.10,
            "float": 0.10,
            "volume": 0.13,
            "price_position": 0.10,
            "dilution": 0.10,
            "pre_news": 0.08,
            "surprise": 0.06,
            "short_squeeze": 0.05,
        }

    # ── Public API ──────────────────────────────────────────────────────

    def evaluate(
        self,
        ticker: str,
        headline: str,
        source: str = "",
        market_cap: Optional[float] = None,
        float_shares: Optional[float] = None,
        rvol: float = 0.0,
        current_price: Optional[float] = None,
        pre_news_runup_pct: float = 0.0,
        pre_news_suspicion_score: float = 0.0,
        pre_news_has_anomaly: bool = False,
        short_interest_pct: Optional[float] = None,
        has_offering_filing: bool = False,
        has_warrants: bool = False,
        is_unconfirmed: bool = False,
    ) -> NewsImpactResult:
        """Run the full impact-engine pipeline on a single news item."""
        result = NewsImpactResult(
            ticker=(ticker or "").upper(),
            headline=headline or "",
            source=source or "",
            market_cap_at_detection=market_cap,
            float_shares_at_detection=float_shares,
            rvol_at_detection=rvol,
            price_at_detection=current_price,
            pre_news_runup_pct=pre_news_runup_pct,
            pre_news_suspicion_score=pre_news_suspicion_score,
            pre_news_accumulation_detected=pre_news_has_anomaly or pre_news_suspicion_score >= 60,
            is_unconfirmed=is_unconfirmed,
        )

        # Classify
        catalyst = classify_news_catalyst(headline)
        result.catalyst_type = catalyst

        # Sector
        sector_name, sector_mult = detect_sector_hype(headline)
        result.sector_hype_multiplier = sector_mult

        # Trap flags
        result.is_dilution = (
            catalyst in BEARISH_CATALYSTS or has_offering_filing or has_warrants
        )
        result.is_parabolic = pre_news_runup_pct >= 80.0

        # ── Component scoring ─────────────────────────────────────────
        comp = {
            "materiality": _score_materiality(catalyst),
            "market_cap": _score_market_cap(market_cap),
            "float": _score_float(float_shares),
            "volume": _score_volume_confirmation(rvol),
            "price_position": _score_price_position(pre_news_runup_pct),
            "dilution": _score_dilution_risk(catalyst, has_offering_filing, has_warrants),
            "pre_news": _score_pre_news(pre_news_suspicion_score),
            "surprise": _score_surprise(catalyst, pre_news_runup_pct),
            "short_squeeze": _score_short_squeeze(short_interest_pct),
        }

        # ── Composite score ───────────────────────────────────────────
        score = sum(self.weights[k] * comp[k] for k in self.weights)

        # Sector hype overlay (multiplier on the bullish components)
        if catalyst not in BEARISH_CATALYSTS and sector_mult > 1.0:
            score = score * sector_mult
            score = min(100.0, score)

        # Bearish floor: hard cap if it's a bearish catalyst
        if catalyst in BEARISH_CATALYSTS:
            score = min(score, 35.0)
        if catalyst == NewsCatalystType.VAGUE_PR:
            score = min(score, 25.0)
        if is_unconfirmed:
            score = score * 0.85

        result.news_impact_score = max(0.0, min(100.0, score))
        result.component_scores = comp

        # ── Estimated move range ──────────────────────────────────────
        result.estimated_move_range = _estimated_move_for(
            catalyst, market_cap, float_shares, sector_mult,
            result.pre_news_accumulation_detected,
        )

        # ── Decision + action ─────────────────────────────────────────
        decision, action = _decide_decision_and_action(
            result.news_impact_score, catalyst,
            result.is_parabolic, result.is_dilution, is_unconfirmed,
            result.pre_news_accumulation_detected, rvol,
        )
        result.news_decision = decision
        result.oracle_action = action
        result.catalyst_tier = _tier_for_score(result.news_impact_score)

        # Trap warning details
        if decision == NewsDecision.DANGEROUS_TRAP:
            result.trap_warning = True
            if result.is_dilution:
                result.trap_reasons.append("Dilution / offering filing detected")
            if result.is_parabolic:
                result.trap_reasons.append(
                    f"Parabolic exhaustion (runup +{pre_news_runup_pct:.0f}%)"
                )
            if catalyst in BEARISH_CATALYSTS:
                result.trap_reasons.append(f"Bearish catalyst type: {catalyst.value}")
            if rvol < 1.0:
                result.trap_reasons.append("Volume not confirming")

        # ── Explanations ──────────────────────────────────────────────
        _build_explanations(
            result, catalyst,
            result.pre_news_accumulation_detected,
            rvol, pre_news_runup_pct,
            result.is_dilution, result.is_parabolic,
            market_cap, float_shares,
        )

        return result

    # ── Convenience wrapper for AgenticCandidate ────────────────────────

    def evaluate_for_candidate(self, cand: AgenticCandidate) -> NewsImpactResult:
        """Run impact-engine evaluation against an AgenticCandidate.

        Pulls the needed context fields off the candidate so callers do not
        have to assemble them manually.
        """
        headline = (cand.catalyst.headline or "")
        source = cand.catalyst.source or ""

        market_cap = cand.float_intel.market_cap
        float_shares = cand.float_intel.float_shares
        price = cand.last_price
        # Approximate RVOL from volume_persistence — better-than-nothing heuristic.
        rvol_proxy = max(
            (cand.momentum.volume_persistence_pct or 0) / 50.0,
            0.0,
        )

        # Estimate pre-news runup via momentum.high_of_day vs current price /
        # previous close — fall back to 0 when missing.
        runup = 0.0
        try:
            if cand.momentum.high_of_day and price:
                runup = max(0.0, (cand.momentum.high_of_day - price) / max(price, 0.01) * 100)
        except Exception:
            pass

        result = self.evaluate(
            ticker=cand.ticker,
            headline=headline,
            source=source,
            market_cap=market_cap,
            float_shares=float_shares,
            rvol=rvol_proxy,
            current_price=price,
            pre_news_runup_pct=runup,
            pre_news_suspicion_score=cand.pre_news_suspicion_score,
            pre_news_has_anomaly=cand.pre_news_has_anomaly,
            has_offering_filing=cand.float_intel.dilution_risk,
            has_warrants=False,
            is_unconfirmed=False,
        )
        return result


__all__ = [
    "NewsCatalystType",
    "NewsDecision",
    "OracleAction",
    "NewsImpactResult",
    "NewsImpactEngine",
    "EstimatedMoveRange",
    "classify_news_catalyst",
    "detect_sector_hype",
    "CATALYST_MATERIALITY",
    "BEARISH_CATALYSTS",
    "SECTOR_HYPE_MULTIPLIER",
]
