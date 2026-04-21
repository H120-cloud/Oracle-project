"""
Risk Scorer — V2

Computes:
  - Risk Score (1–10): higher = riskier
  - Setup Grade (A–F): composite quality grade
  - Confidence (%): calibrated probability of success
"""

import logging
from dataclasses import dataclass
from typing import Optional

from src.models.schemas import (
    DipResult,
    BounceResult,
    ScannedStock,
    StockClassification,
    DipPhase,
)

logger = logging.getLogger(__name__)


@dataclass
class RiskAssessment:
    risk_score: int          # 1 (safest) – 10 (riskiest)
    setup_grade: str         # A (best) – F (worst)
    confidence: float        # 0–100 calibrated %
    risk_factors: list[str]  # human-readable reasons


class RiskScorer:
    """Evaluates the risk profile of a trading signal."""

    def assess(
        self,
        stock: ScannedStock,
        classification: StockClassification,
        dip: Optional[DipResult],
        bounce: Optional[BounceResult],
    ) -> RiskAssessment:
        risk_points = 0.0
        quality_points = 0.0
        factors: list[str] = []

        # ── Risk factors (increase risk_points → higher risk score) ──────

        # 1. Low volume = higher risk
        if stock.volume < 500_000:
            risk_points += 2.0
            factors.append("Low volume")
        elif stock.volume < 1_000_000:
            risk_points += 1.0
            factors.append("Moderate volume")

        # 2. High % change = chasing risk
        if stock.change_percent is not None:
            if stock.change_percent > 15:
                risk_points += 2.5
                factors.append("Extended > 15%")
            elif stock.change_percent > 10:
                risk_points += 1.5
                factors.append("Extended > 10%")

        # 3. Late-phase dip = breakdown risk
        if dip is not None and dip.phase == DipPhase.LATE:
            risk_points += 2.0
            factors.append("Late dip phase")
        elif dip is not None and dip.phase == DipPhase.MID:
            risk_points += 0.5

        # 4. Low bounce probability
        if bounce is not None and bounce.probability < 50:
            risk_points += 1.5
            factors.append(f"Weak bounce ({bounce.probability:.0f}%)")

        # 5. Classification-based risk
        high_risk_classes = {
            StockClassification.BREAKDOWN_RISK: 3.0,
            StockClassification.OVEREXTENDED: 2.0,
            StockClassification.SIDEWAYS: 1.0,
        }
        if classification in high_risk_classes:
            risk_points += high_risk_classes[classification]
            factors.append(f"Classification: {classification.value}")

        # 6. Low RVOL = less conviction
        if stock.rvol is not None and stock.rvol < 1.0:
            risk_points += 1.0
            factors.append("Below-average relative volume")

        # ── Quality factors (increase quality_points → better grade) ─────

        if bounce is not None and bounce.probability >= 65:
            quality_points += 3.0
        if bounce is not None and bounce.entry_ready:
            quality_points += 2.0
        if dip is not None and dip.is_valid_dip:
            quality_points += 1.5
        if dip is not None and dip.phase == DipPhase.MID:
            quality_points += 1.0
        if stock.rvol is not None and stock.rvol >= 2.0:
            quality_points += 1.5
        if stock.volume >= 2_000_000:
            quality_points += 1.0
        if bounce is not None and bounce.features.higher_low_formed:
            quality_points += 1.0
        if bounce is not None and bounce.features.key_level_reclaimed:
            quality_points += 1.0

        # ── Compute final scores ─────────────────────────────────────────

        risk_score = max(1, min(10, round(risk_points)))
        setup_grade = self._compute_grade(quality_points, risk_points)
        confidence = self._compute_confidence(dip, bounce, quality_points, risk_points)

        logger.info(
            "RiskScorer [%s]: risk=%d grade=%s conf=%.1f factors=%s",
            stock.ticker, risk_score, setup_grade, confidence, factors,
        )

        return RiskAssessment(
            risk_score=risk_score,
            setup_grade=setup_grade,
            confidence=round(confidence, 1),
            risk_factors=factors,
        )

    # ── Helpers ──────────────────────────────────────────────────────────

    @staticmethod
    def _compute_grade(quality: float, risk: float) -> str:
        """Map net quality score to A-F."""
        net = quality - risk * 0.5
        if net >= 6:
            return "A"
        if net >= 4:
            return "B"
        if net >= 2:
            return "C"
        if net >= 0:
            return "D"
        return "F"

    @staticmethod
    def _compute_confidence(
        dip: Optional[DipResult],
        bounce: Optional[BounceResult],
        quality: float,
        risk: float,
    ) -> float:
        """Estimate confidence as a % combining probabilities and quality."""
        base = 50.0  # neutral

        if bounce is not None:
            base = bounce.probability * 0.5 + base * 0.5

        if dip is not None and dip.is_valid_dip:
            base += 5.0

        # Quality boost / risk penalty
        base += quality * 2.0
        base -= risk * 3.0

        return max(0.0, min(100.0, base))
