"""Agentic Float Intelligence Engine — Part 3

Classifies float size, detects dilution risk, computes float score.
"""

import logging
from typing import Optional

import yfinance as yf

from src.core.agentic.models import FloatIntel, FloatCategory, AgenticCandidate
from src.core.agentic.calibration_provider import get_calibration_weights

logger = logging.getLogger(__name__)

MAX_MULTIPLIER = 1.15
MIN_MULTIPLIER = 0.85


def _clamp_multiplier(m: float) -> float:
    return max(MIN_MULTIPLIER, min(MAX_MULTIPLIER, m))


def classify_float(float_shares: Optional[float]) -> FloatCategory:
    if float_shares is None:
        return FloatCategory.NORMAL
    if float_shares < 5_000_000:
        return FloatCategory.ULTRA_LOW
    if float_shares < 20_000_000:
        return FloatCategory.LOW
    return FloatCategory.NORMAL


def compute_float_score(float_shares: Optional[float], dilution_risk: bool) -> float:
    """Lower float → higher opportunity score (but also higher risk)."""
    if float_shares is None:
        return 50.0
    if float_shares < 1_000_000:
        score = 95.0
    elif float_shares < 5_000_000:
        score = 85.0
    elif float_shares < 10_000_000:
        score = 70.0
    elif float_shares < 20_000_000:
        score = 55.0
    elif float_shares < 50_000_000:
        score = 40.0
    else:
        score = 25.0

    if dilution_risk:
        score *= 0.6  # 40% penalty for dilution risk
    return round(score, 1)


class FloatIntelEngine:
    """Enrich candidates with float / dilution intelligence."""

    def __init__(self):
        self.cw = get_calibration_weights()
        if self.cw:
            logger.info("FloatIntelEngine loaded calibration v%s", self.cw.version)

    def enrich(self, candidate: AgenticCandidate) -> AgenticCandidate:
        """Fetch float data and classify."""
        ticker = candidate.ticker
        try:
            tkr = yf.Ticker(ticker)
            info = tkr.info or {}

            float_shares = info.get("floatShares")
            shares_out = info.get("sharesOutstanding") or candidate.float_intel.shares_outstanding
            market_cap = info.get("marketCap") or candidate.float_intel.market_cap

            # Detect dilution risk keywords in recent news / description
            dilution_risk = False
            dilution_reason = None
            desc = (info.get("longBusinessSummary") or "").lower()
            title = candidate.catalyst.headline.lower()
            for keyword in ["offering", "dilution", "atm program", "shelf registration", "shares registered"]:
                if keyword in title or keyword in desc:
                    dilution_risk = True
                    dilution_reason = f"Keyword detected: {keyword}"
                    break

            # Offering catalyst type also flags dilution
            from src.core.agentic.models import CatalystType
            if candidate.catalyst.catalyst_type == CatalystType.OFFERING:
                dilution_risk = True
                dilution_reason = dilution_reason or "Catalyst is an offering"

            float_cat = classify_float(float_shares)
            float_score = compute_float_score(float_shares, dilution_risk)

            # Apply float_bucket_w calibration multiplier (max 15% drift)
            calibrated = False
            if self.cw and self.cw.float_bucket_w != 1.0:
                mult = _clamp_multiplier(self.cw.float_bucket_w)
                float_score = round(min(100, float_score * mult), 1)
                calibrated = True
                logger.info("FloatIntelEngine applied float_bucket_w=%s -> score=%s", mult, float_score)

            candidate.float_intel = FloatIntel(
                float_shares=float_shares,
                float_category=float_cat,
                shares_outstanding=shares_out,
                market_cap=market_cap,
                dilution_risk=dilution_risk,
                dilution_risk_reason=dilution_reason,
                float_score=float_score,
                calibrated=calibrated,
            )

        except Exception as e:
            logger.warning("FloatIntelEngine failed for %s: %s", ticker, e)

        return candidate
