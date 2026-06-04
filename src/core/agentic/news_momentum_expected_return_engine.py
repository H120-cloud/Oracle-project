"""
News Momentum Expected Return ML Engine (V22)

Predicts which catalyst-driven stocks have the best expected return.
Uses a rule-based weighted scoring system that can be upgraded to
a trained ML model once sufficient historical outcomes are collected.
"""

from __future__ import annotations

import logging
from typing import Optional, List

from src.core.agentic.news_momentum_models import (
    NewsMomentumCandidate,
    ExpectedReturnMLScore,
    CatalystCategory,
    CatalystSubType,
    FloatCategory,
)

logger = logging.getLogger(__name__)


# ── Feature Weights ──────────────────────────────────────────────────────────

FEATURE_WEIGHTS = {
    "news_impact_score": 0.18,
    "news_reaction_score": 0.14,
    "float_sensitivity": 0.12,
    "market_cap_sensitivity": 0.06,
    "volume_expansion": 0.12,
    "vwap_behavior": 0.10,
    "continuation_quality": 0.10,
    "trap_risk": -0.10,
    "dilution_risk": -0.08,
    "price_extension_risk": -0.06,
    "spread_quality": 0.06,
}

CATALYST_RETURN_MULTIPLIERS = {
    # Biotech — highest multipliers
    CatalystSubType.FDA_APPROVAL: 1.25,
    CatalystSubType.NDA_APPROVAL: 1.25,
    CatalystSubType.DRUG_LAUNCH: 1.20,
    CatalystSubType.BREAKTHROUGH_THERAPY: 1.20,
    CatalystSubType.PDUFA: 1.18,
    CatalystSubType.TOPLINE_DATA: 1.15,
    CatalystSubType.SNDA_SUBMISSION: 1.12,
    CatalystSubType.LABEL_EXPANSION: 1.15,
    CatalystSubType.COMMERCIALIZATION: 1.12,

    # Corporate — high multipliers
    CatalystSubType.BUYOUT: 1.30,
    CatalystSubType.ACQUISITION: 1.20,
    CatalystSubType.SHARE_BUYBACK: 1.15,
    CatalystSubType.GOVERNMENT_CONTRACT: 1.15,
    CatalystSubType.ANALYST_UPGRADE: 1.15,
    CatalystSubType.STRATEGIC_REVIEW: 1.10,
    CatalystSubType.SPIN_OFF: 1.12,
    CatalystSubType.JOINT_VENTURE: 1.10,
    CatalystSubType.MAJOR_PARTNERSHIP: 1.12,
    CatalystSubType.SUPPLY_AGREEMENT: 1.10,
    CatalystSubType.OEM_PARTNERSHIP: 1.12,
    CatalystSubType.LICENSING_AGREEMENT: 1.10,
    CatalystSubType.PATENT_APPROVAL: 1.08,
    CatalystSubType.TARIFF_EXEMPTION: 1.08,
    CatalystSubType.TRADE_DEAL: 1.10,
    CatalystSubType.SUBSIDY_AWARD: 1.08,
    CatalystSubType.WARRANT_OVERHANG_REMOVAL: 1.15,
    CatalystSubType.LISTING_COMPLIANCE: 1.10,

    # AI/Tech
    CatalystSubType.AI_PARTNERSHIP: 1.15,
    CatalystSubType.NVIDIA_PARTNERSHIP: 1.20,
    CatalystSubType.OPENAI_PARTNERSHIP: 1.18,
    CatalystSubType.HYPERSCALER_CONTRACT: 1.15,
    CatalystSubType.NEW_PRODUCT_LAUNCH: 1.12,
    CatalystSubType.PRODUCT_UPGRADE: 1.08,
    CatalystSubType.PLATFORM_EXPANSION: 1.10,
    CatalystSubType.NEW_MARKET_ENTRY: 1.08,

    # Financial
    CatalystSubType.EARNINGS_BEAT: 1.10,
    CatalystSubType.GUIDANCE_RAISE: 1.08,
    CatalystSubType.PROFITABILITY_INFLECTION: 1.12,
    CatalystSubType.DIVIDEND_INCREASE: 1.08,
    CatalystSubType.CREDIT_UPGRADE: 1.08,
    CatalystSubType.FINANCING_POSITIVE: 1.06,
    CatalystSubType.STOCK_SPLIT_FORWARD: 1.06,

    # Crypto / Green
    CatalystSubType.BITCOIN_TREASURY: 1.12,
    CatalystSubType.EV_BATTERY: 1.10,
    CatalystSubType.RENEWABLE_ENERGY: 1.08,

    # Negative — suppress
    CatalystSubType.VAGUE_PR: 0.40,
    CatalystSubType.OFFERING: 0.30,
    CatalystSubType.ATM_FILING: 0.25,
    CatalystSubType.DEBT_DOWNGRADE: 0.60,
    CatalystSubType.GUIDANCE_CUT: 0.55,
    CatalystSubType.EARNINGS_MISS: 0.50,
    CatalystSubType.DIVIDEND_CUT: 0.45,
    CatalystSubType.ANALYST_DOWNGRADE: 0.55,
    CatalystSubType.SHORT_SELLER_REPORT: 0.60,
    CatalystSubType.CLINICAL_HOLD: 0.55,
    CatalystSubType.TRIAL_FAILURE: 0.45,
    CatalystSubType.SAFETY_SIGNAL: 0.50,
    CatalystSubType.ADVERSE_EVENT: 0.50,
    CatalystSubType.INVESTIGATION: 0.55,
    CatalystSubType.ACCOUNTING_IRREGULARITIES: 0.45,
    CatalystSubType.MARGIN_PRESSURE: 0.65,
}


def compute_expected_return_score(
    candidate: NewsMomentumCandidate,
    historical_stats: Optional[dict] = None,
) -> ExpectedReturnMLScore:
    """
    Compute expected return score (0-100) for a candidate.
    Uses weighted features + catalyst-specific multipliers.
    """
    score = ExpectedReturnMLScore()

    # Build feature vector
    features = {
        "news_impact_score": candidate.news_impact_score,
        "news_reaction_score": candidate.news_reaction_score,
        "float_sensitivity": _float_to_score(candidate.float_category),
        "market_cap_sensitivity": _mcap_to_score(candidate.market_cap_category),
        "volume_expansion": min((candidate.rvol or 1.0) * 15, 100.0),
        "vwap_behavior": candidate.news_impact_score * 0.8 if candidate.dilution_risk < 50 else 30.0,
        "continuation_quality": candidate.continuation_probability,
        "trap_risk": candidate.trap_risk,
        "dilution_risk": candidate.dilution_risk,
        "price_extension_risk": min(candidate.move_pct * 0.5, 100.0) if candidate.move_pct > 60 else 20.0,
        "spread_quality": 100.0 - (candidate.trap_risk * 0.5),
    }

    # Apply historical stats if available
    if historical_stats:
        cat = candidate.catalyst_sub_type.value
        if cat in historical_stats:
            stats = historical_stats[cat]
            hist_cont = stats.get("continuation_rate", 50.0)
            hist_mfe = stats.get("avg_mfe_pct", 30.0)
            features["historical_continuation"] = hist_cont
            features["historical_mfe"] = min(hist_mfe * 2, 100.0)
            FEATURE_WEIGHTS_LOCAL = {**FEATURE_WEIGHTS, "historical_continuation": 0.10, "historical_mfe": 0.08}
        else:
            FEATURE_WEIGHTS_LOCAL = FEATURE_WEIGHTS
    else:
        FEATURE_WEIGHTS_LOCAL = FEATURE_WEIGHTS

    # Weighted sum
    total = 0.0
    total_weight = 0.0
    for feat_name, weight in FEATURE_WEIGHTS_LOCAL.items():
        if feat_name in features:
            total += features[feat_name] * weight
            total_weight += abs(weight)

    if total_weight > 0:
        raw_score = total / total_weight
    else:
        raw_score = 50.0

    # Apply catalyst multiplier
    multiplier = CATALYST_RETURN_MULTIPLIERS.get(candidate.catalyst_sub_type, 1.0)
    raw_score *= multiplier

    # Apply session adjustments
    if candidate.session.value == "premarket":
        raw_score *= 1.05
    elif candidate.session.value == "after_hours":
        raw_score *= 1.02

    score.score = round(max(0.0, min(100.0, raw_score)), 1)
    score.confidence = _compute_confidence(candidate, features)
    score.feature_vector = {k: round(v, 2) for k, v in features.items()}
    score.top_features = _top_features(features, FEATURE_WEIGHTS_LOCAL, n=5)
    return score


def _float_to_score(float_cat: FloatCategory) -> float:
    return {"ultra_low": 100.0, "low": 80.0, "medium": 50.0, "high": 25.0}.get(float_cat.value, 50.0)


def _mcap_to_score(mcap_cat) -> float:
    return {"nano": 100.0, "micro": 80.0, "small": 50.0, "all": 30.0}.get(mcap_cat.value, 50.0)


def _compute_confidence(candidate: NewsMomentumCandidate, features: dict) -> float:
    """Higher confidence when we have more data points."""
    conf = 50.0
    if candidate.rvol is not None:
        conf += 15.0
    if candidate.float_shares is not None:
        conf += 10.0
    if candidate.market_cap is not None:
        conf += 10.0
    if candidate.spread_pct is not None:
        conf += 5.0
    if candidate.short_interest is not None:
        conf += 10.0
    return min(conf, 100.0)


def _top_features(features: dict, weights: dict, n: int = 5) -> List[str]:
    """Return top N features by absolute weighted contribution."""
    scored = [(name, abs(features.get(name, 0) * weight)) for name, weight in weights.items() if name in features]
    scored.sort(key=lambda x: x[1], reverse=True)
    return [name for name, _ in scored[:n]]
