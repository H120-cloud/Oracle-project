"""
News Momentum Impact Scorer (V22)

Scores news catalysts 0-100 based on materiality, float sensitivity,
sector hype, volume expansion, and risk factors.
"""

from __future__ import annotations

import logging
from typing import Optional

from src.core.agentic.news_momentum_models import (
    CatalystSubType,
    CatalystCategory,
    FloatCategory,
    MarketCapCategory,
    NewsImpactScore,
)

logger = logging.getLogger(__name__)


# ── Base Materiality Scores ───────────────────────────────────────────────────

CATALYST_MATERIALITY: dict[CatalystSubType, float] = {
    # Biotech — highest impact
    CatalystSubType.FDA_APPROVAL: 100.0,
    CatalystSubType.FDA_CLEARANCE: 90.0,
    CatalystSubType.PDUFA: 85.0,
    CatalystSubType.BREAKTHROUGH_THERAPY: 88.0,
    CatalystSubType.FAST_TRACK: 75.0,
    CatalystSubType.ORPHAN_DRUG: 72.0,
    CatalystSubType.PHASE_3: 80.0,
    CatalystSubType.PHASE_2: 65.0,
    CatalystSubType.PHASE_1: 50.0,
    CatalystSubType.TOPLINE_DATA: 78.0,
    CatalystSubType.SNDA_SUBMISSION: 75.0,
    CatalystSubType.NDA_APPROVAL: 92.0,
    CatalystSubType.LABEL_EXPANSION: 80.0,
    CatalystSubType.DRUG_LAUNCH: 85.0,
    CatalystSubType.COMMERCIALIZATION: 78.0,

    # AI/Tech
    CatalystSubType.AI_PARTNERSHIP: 82.0,
    CatalystSubType.NVIDIA_PARTNERSHIP: 88.0,
    CatalystSubType.OPENAI_PARTNERSHIP: 85.0,
    CatalystSubType.HYPERSCALER_CONTRACT: 80.0,
    CatalystSubType.INFRASTRUCTURE_AGREEMENT: 72.0,
    CatalystSubType.NEW_PRODUCT_LAUNCH: 72.0,
    CatalystSubType.PRODUCT_UPGRADE: 65.0,
    CatalystSubType.PLATFORM_EXPANSION: 68.0,
    CatalystSubType.NEW_MARKET_ENTRY: 65.0,

    # Financial
    CatalystSubType.EARNINGS_BEAT: 78.0,
    CatalystSubType.GUIDANCE_RAISE: 75.0,
    CatalystSubType.PROFITABILITY_INFLECTION: 82.0,
    CatalystSubType.INSIDER_BUYING: 55.0,
    CatalystSubType.DEBT_RESTRUCTURING: 60.0,
    CatalystSubType.DIVIDEND_INCREASE: 70.0,
    CatalystSubType.STOCK_SPLIT_FORWARD: 60.0,
    CatalystSubType.CREDIT_UPGRADE: 65.0,
    CatalystSubType.FINANCING_POSITIVE: 60.0,
    CatalystSubType.DEBT_DOWNGRADE: 20.0,
    CatalystSubType.GUIDANCE_CUT: 22.0,
    CatalystSubType.EARNINGS_MISS: 20.0,
    CatalystSubType.DIVIDEND_CUT: 15.0,

    # Crypto / Green
    CatalystSubType.BITCOIN_TREASURY: 72.0,
    CatalystSubType.CRYPTO_MINING: 65.0,
    CatalystSubType.BLOCKCHAIN_PARTNERSHIP: 60.0,
    CatalystSubType.EV_BATTERY: 70.0,
    CatalystSubType.RENEWABLE_ENERGY: 65.0,
    CatalystSubType.CARBON_CREDIT: 55.0,

    # Corporate
    CatalystSubType.BUYOUT: 95.0,
    CatalystSubType.ACQUISITION: 88.0,
    CatalystSubType.MERGER: 85.0,
    CatalystSubType.STRATEGIC_REVIEW: 70.0,
    CatalystSubType.LICENSING_AGREEMENT: 68.0,
    CatalystSubType.PATENT_APPROVAL: 65.0,
    CatalystSubType.GOVERNMENT_CONTRACT: 78.0,
    CatalystSubType.MAJOR_PARTNERSHIP: 72.0,
    CatalystSubType.SUPPLY_AGREEMENT: 70.0,
    CatalystSubType.OEM_PARTNERSHIP: 75.0,
    CatalystSubType.SHARE_BUYBACK: 85.0,
    CatalystSubType.SPIN_OFF: 75.0,
    CatalystSubType.JOINT_VENTURE: 70.0,
    CatalystSubType.MANAGEMENT_CHANGE_POSITIVE: 60.0,
    CatalystSubType.ANALYST_UPGRADE: 70.0,
    CatalystSubType.TARIFF_EXEMPTION: 65.0,
    CatalystSubType.TRADE_DEAL: 70.0,
    CatalystSubType.SUBSIDY_AWARD: 68.0,
    CatalystSubType.WARRANT_OVERHANG_REMOVAL: 72.0,
    CatalystSubType.LISTING_COMPLIANCE: 65.0,

    # Negative
    CatalystSubType.OFFERING: 15.0,
    CatalystSubType.ATM_FILING: 10.0,
    CatalystSubType.WARRANT_EXERCISE: 8.0,
    CatalystSubType.REVERSE_SPLIT: 5.0,
    CatalystSubType.DELISTING_NOTICE: 12.0,
    CatalystSubType.TOXIC_FINANCING: 5.0,
    CatalystSubType.VAGUE_PR: 3.0,
    CatalystSubType.CLINICAL_HOLD: 20.0,
    CatalystSubType.TRIAL_FAILURE: 15.0,
    CatalystSubType.SAFETY_SIGNAL: 18.0,
    CatalystSubType.ADVERSE_EVENT: 18.0,
    CatalystSubType.INVESTIGATION: 20.0,
    CatalystSubType.ACCOUNTING_IRREGULARITIES: 15.0,
    CatalystSubType.MARGIN_PRESSURE: 25.0,
    CatalystSubType.ANALYST_DOWNGRADE: 20.0,
    CatalystSubType.SHORT_SELLER_REPORT: 25.0,

    CatalystSubType.OTHER: 40.0,
}


SECTOR_HYPE_MULTIPLIER: dict[CatalystCategory, float] = {
    CatalystCategory.BIOTECH: 1.15,
    CatalystCategory.AI_TECH: 1.20,
    CatalystCategory.CRYPTO: 1.10,
    CatalystCategory.FINANCIAL: 1.05,
    CatalystCategory.CORPORATE: 1.08,
    CatalystCategory.NEGATIVE: 0.70,
    CatalystCategory.UNKNOWN: 1.0,
}


def score_news_impact(
    catalyst_sub_type: CatalystSubType,
    catalyst_category: CatalystCategory,
    float_cat: FloatCategory,
    market_cap_cat: MarketCapCategory,
    rvol: Optional[float] = None,
    spread_pct: Optional[float] = None,
    move_pct: float = 0.0,
    vwap_distance_pct: Optional[float] = None,
    upper_wick_pct: Optional[float] = None,
    is_pre_news_accumulation: bool = False,
    is_negative: bool = False,
    is_vague: bool = False,
    short_interest: Optional[float] = None,
) -> NewsImpactScore:
    """
    Compute a comprehensive news impact score (0-100).
    """
    score = NewsImpactScore()

    # 1. Catalyst materiality base
    base = CATALYST_MATERIALITY.get(catalyst_sub_type, 40.0)
    score.catalyst_materiality = base

    # 2. Surprise factor — bigger surprise = bigger move potential
    # For biotech/catalyst-driven moves, a large premarket gap IS the surprise
    # Penalize only extreme extended midday pumps (no-news parabolic moves)
    is_biotech = catalyst_category == CatalystCategory.BIOTECH
    if move_pct > 300:
        score.surprise_factor = 30.0 if is_biotech else 15.0
    elif move_pct > 150:
        score.surprise_factor = 65.0 if is_biotech else 35.0
    elif move_pct > 80:
        score.surprise_factor = 80.0 if is_biotech else 55.0
    elif move_pct > 40:
        score.surprise_factor = 85.0
    elif move_pct > 15:
        score.surprise_factor = 90.0
    else:
        score.surprise_factor = 65.0

    # 3. Float sensitivity — lower float = bigger potential move
    float_map = {
        FloatCategory.ULTRA_LOW: 100.0,
        FloatCategory.LOW: 80.0,
        FloatCategory.MEDIUM: 50.0,
        FloatCategory.HIGH: 25.0,
    }
    score.float_sensitivity = float_map.get(float_cat, 50.0)

    # 4. Market cap sensitivity
    mc_map = {
        MarketCapCategory.NANO: 100.0,
        MarketCapCategory.MICRO: 80.0,
        MarketCapCategory.SMALL: 50.0,
        MarketCapCategory.ALL: 30.0,
    }
    score.market_cap_sensitivity = mc_map.get(market_cap_cat, 50.0)

    # 5. Sector hype multiplier
    score.sector_hype_multiplier = SECTOR_HYPE_MULTIPLIER.get(catalyst_category, 1.0)

    # 6. Short squeeze potential
    if short_interest and short_interest > 20:
        score.short_squeeze_potential = 85.0
    elif short_interest and short_interest > 10:
        score.short_squeeze_potential = 65.0
    else:
        score.short_squeeze_potential = 35.0

    # 7. Volume expansion
    if rvol and rvol > 5:
        score.volume_expansion = 100.0
    elif rvol and rvol > 3:
        score.volume_expansion = 85.0
    elif rvol and rvol > 1.5:
        score.volume_expansion = 60.0
    else:
        score.volume_expansion = 30.0

    # 8. Spread quality (lower spread = better)
    if spread_pct and spread_pct < 1.0:
        score.spread_quality = 90.0
    elif spread_pct and spread_pct < 3.0:
        score.spread_quality = 65.0
    else:
        score.spread_quality = 30.0

    # 9. VWAP behavior
    if vwap_distance_pct is not None:
        if vwap_distance_pct > 5:
            score.vwap_behavior = 85.0  # Strongly above VWAP
        elif vwap_distance_pct > 0:
            score.vwap_behavior = 70.0
        elif vwap_distance_pct > -3:
            score.vwap_behavior = 50.0
        else:
            score.vwap_behavior = 25.0  # Below VWAP
    else:
        score.vwap_behavior = 50.0

    # 10. Pre-news accumulation
    score.pre_news_accumulation = 70.0 if is_pre_news_accumulation else 35.0

    # 11. Dilution risk
    if catalyst_sub_type in (
        CatalystSubType.OFFERING,
        CatalystSubType.ATM_FILING,
        CatalystSubType.WARRANT_EXERCISE,
        CatalystSubType.TOXIC_FINANCING,
    ):
        score.dilution_risk = 95.0
    else:
        score.dilution_risk = 15.0

    # 12. Trap risk — biotech premarket catalyst gaps are not traps
    trap = 0.0
    if upper_wick_pct and upper_wick_pct > 30:
        trap += 30.0
    # Only penalize large moves as "traps" for non-biotech or when already extremely extended
    if not is_biotech:
        if move_pct > 100:
            trap += 25.0
        if move_pct > 200:
            trap += 25.0
    else:
        # Biotech: only penalize extreme parabolic moves without upper wick confirmation
        if move_pct > 250:
            trap += 15.0
        if move_pct > 400:
            trap += 20.0
    if vwap_distance_pct is not None and vwap_distance_pct < -2:
        trap += 20.0
    score.trap_risk = min(trap, 100.0)

    # 13. Price extension risk — be less aggressive for biotech catalysts
    if is_biotech:
        if move_pct > 400:
            score.price_extension_risk = 80.0
        elif move_pct > 250:
            score.price_extension_risk = 55.0
        elif move_pct > 150:
            score.price_extension_risk = 35.0
        elif move_pct > 60:
            score.price_extension_risk = 20.0
        else:
            score.price_extension_risk = 10.0
    else:
        if move_pct > 200:
            score.price_extension_risk = 95.0
        elif move_pct > 120:
            score.price_extension_risk = 75.0
        elif move_pct > 60:
            score.price_extension_risk = 50.0
        else:
            score.price_extension_risk = 20.0

    # ── Composite Score ─────────────────────────────────────────────────────
    weights = {
        "catalyst_materiality": 0.20,
        "surprise_factor": 0.10,
        "float_sensitivity": 0.12,
        "market_cap_sensitivity": 0.06,
        "short_squeeze_potential": 0.08,
        "volume_expansion": 0.12,
        "spread_quality": 0.05,
        "vwap_behavior": 0.08,
        "pre_news_accumulation": 0.05,
        "dilution_risk": -0.10,
        "trap_risk": -0.08,
        "price_extension_risk": -0.06,
    }

    composite = 0.0
    for field_name, weight in weights.items():
        value = getattr(score, field_name)
        composite += value * weight

    # Apply sector multiplier (capped)
    composite *= score.sector_hype_multiplier

    # Biotech catalyst confirmation bonus: high RVOL + low float + positive catalyst
    if is_biotech and not is_negative and rvol and rvol > 10 and float_cat in (FloatCategory.ULTRA_LOW, FloatCategory.LOW):
        composite += 12.0

    # High RVOL confirmation bonus across all sectors
    if rvol and rvol > 15 and not is_negative:
        composite += 6.0

    composite = max(0.0, min(100.0, composite))

    # Harsh penalty for negative / vague
    if is_negative:
        composite *= 0.3
    if is_vague:
        composite *= 0.5

    score.composite_score = round(max(0.0, min(100.0, composite)), 1)
    return score
