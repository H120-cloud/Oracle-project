"""Fast bullish-catalyst triage for first Telegram alerts.

This layer is intentionally simple and local-first. It only decides whether a
fresh headline is bullish enough to flash immediately; the slower ML and
winner-scoring layers can still analyze the candidate after the alert.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from src.core.agentic.news_momentum_models import (
    CatalystCategory,
    CatalystSubType,
    NewsMomentumCandidate,
    NewsMomentumConfig,
)


@dataclass(frozen=True)
class BullishFlashAssessment:
    should_flash: bool
    score: float = 0.0
    reasons: list[str] = field(default_factory=list)
    block_reason: Optional[str] = None
    suggested_category: Optional[CatalystCategory] = None
    suggested_sub_type: Optional[CatalystSubType] = None


_BEARISH_PATTERNS: tuple[tuple[str, str], ...] = (
    ("offering", r"\boffering\b|registered direct|public offering|atm offering|at-the-market"),
    ("dilution", r"\bdilution\b|dilutive|convertible note|toxic financing|warrant exercise"),
    ("reverse_split", r"reverse split|stock split.*reverse|1-for-\d+"),
    ("delisting", r"delisting|nasdaq notice|bid price deficiency|non-compliance"),
    ("bankruptcy", r"bankruptcy|chapter 11|going concern|liquidation"),
    ("lawsuit", r"lawsuit|litigation|class action|shareholder suit"),
    ("investigation", r"investigation|subpoena|wells notice|fraud|short seller|hindenburg"),
    ("bad_results", r"misses|missed|guidance cut|lowers outlook|trial failure|clinical hold"),
    ("downgrade", r"downgrade|downgraded|cuts price target|sell rating"),
)

_BULLISH_PATTERNS: tuple[tuple[str, str, float, CatalystCategory, CatalystSubType], ...] = (
    ("lunar", r"\blunar\b|moon[- ]based|space[- ]based|in[- ]space|orbital", 22.0, CatalystCategory.AI_TECH, CatalystSubType.AI_PARTNERSHIP),
    ("quantum", r"\bquantum\b|quantum computing|quantum computer", 20.0, CatalystCategory.AI_TECH, CatalystSubType.AI_PARTNERSHIP),
    ("semiconductor", r"semiconductor|chip manufacturing|chip fab|foundry", 16.0, CatalystCategory.AI_TECH, CatalystSubType.INFRASTRUCTURE_AGREEMENT),
    ("ai", r"\bai\b|artificial intelligence|machine learning|gpu|nvidia|openai", 14.0, CatalystCategory.AI_TECH, CatalystSubType.AI_PARTNERSHIP),
    ("approval", r"approves|approved|approval|clearance|clears|granted", 12.0, CatalystCategory.CORPORATE, CatalystSubType.STRATEGIC_REVIEW),
    ("contract", r"wins|awarded|secures|contract|government|nasa|dod|defense", 18.0, CatalystCategory.CORPORATE, CatalystSubType.GOVERNMENT_CONTRACT),
    ("partnership", r"partnership|collaboration|agreement|alliance|joint venture", 14.0, CatalystCategory.CORPORATE, CatalystSubType.MAJOR_PARTNERSHIP),
    ("strategic", r"strategic initiative|strategic plan|strategic review|strategic expansion", 10.0, CatalystCategory.CORPORATE, CatalystSubType.STRATEGIC_REVIEW),
    ("infrastructure", r"infrastructure|manufacturing|facility|production|resource", 10.0, CatalystCategory.AI_TECH, CatalystSubType.INFRASTRUCTURE_AGREEMENT),
    ("biotech", r"fda|phase 1|phase 2|phase 3|topline|orphan drug|fast track", 18.0, CatalystCategory.BIOTECH, CatalystSubType.FDA_APPROVAL),
    ("financial", r"raises guidance|beats|record revenue|profitability|buyback|dividend increase", 16.0, CatalystCategory.FINANCIAL, CatalystSubType.EARNINGS_BEAT),
    ("crypto", r"bitcoin treasury|digital asset treasury|crypto treasury|blockchain", 16.0, CatalystCategory.CRYPTO, CatalystSubType.BITCOIN_TREASURY),
)


def assess_bullish_flash(
    candidate: NewsMomentumCandidate,
    config: NewsMomentumConfig,
    *,
    now: Optional[datetime] = None,
) -> BullishFlashAssessment:
    """Return whether a fresh headline should bypass slow scoring gates."""
    if not getattr(config, "bullish_flash_enabled", True):
        return BullishFlashAssessment(False, block_reason="flash_disabled")

    text = (candidate.headline or "").lower()
    for label, pattern in _BEARISH_PATTERNS:
        if re.search(pattern, text):
            return BullishFlashAssessment(False, block_reason=f"bearish_keyword:{label}")
    if candidate.is_negative:
        return BullishFlashAssessment(False, block_reason="negative_classification")

    now = now or datetime.now(timezone.utc)
    published = candidate.published_at
    detected = candidate.detected_at
    if published is None:
        return BullishFlashAssessment(False, block_reason="missing_published_at")
    if published.tzinfo is None:
        published = published.replace(tzinfo=timezone.utc)
    if detected is None:
        detected = published
    if detected.tzinfo is None:
        detected = detected.replace(tzinfo=timezone.utc)
    max_age = float(getattr(config, "bullish_flash_max_age_seconds", 180))
    published_age = (now - published).total_seconds()
    detected_age = (now - detected).total_seconds()
    if published_age < 0 or detected_age < 0:
        return BullishFlashAssessment(False, block_reason="future_flash_candidate")
    if published_age > max_age or detected_age > max_age:
        return BullishFlashAssessment(False, block_reason="stale_flash_candidate")

    if (candidate.trap_risk or 0.0) >= float(getattr(config, "high_trap_block_threshold", 70.0)):
        return BullishFlashAssessment(False, block_reason="trap_risk")
    if (candidate.dilution_risk or 0.0) >= float(getattr(config, "high_dilution_block_threshold", 70.0)):
        return BullishFlashAssessment(False, block_reason="dilution_risk")

    score = 0.0
    reasons: list[str] = []
    suggested_category: Optional[CatalystCategory] = None
    suggested_sub_type: Optional[CatalystSubType] = None
    for reason, pattern, weight, category, sub_type in _BULLISH_PATTERNS:
        if re.search(pattern, text):
            score += weight
            reasons.append(reason)
            suggested_category = suggested_category or category
            suggested_sub_type = suggested_sub_type or sub_type

    if candidate.catalyst_category != CatalystCategory.UNKNOWN:
        score += 8.0
    if candidate.catalyst_sub_type not in {CatalystSubType.OTHER, CatalystSubType.VAGUE_PR}:
        score += 8.0
    if (candidate.current_price or 0.0) < 10.0:
        score += 5.0
    if (candidate.move_pct or 0.0) > 0.0:
        score += min(10.0, max(0.0, candidate.move_pct) / 2.0)
    if (candidate.rvol or 0.0) >= 2.0:
        score += 5.0

    min_score = float(getattr(config, "bullish_flash_min_score", 55.0))
    if score < min_score:
        return BullishFlashAssessment(
            False,
            score=round(score, 1),
            reasons=reasons,
            block_reason=f"flash_score({score:.1f}<{min_score:.1f})",
        )

    return BullishFlashAssessment(
        True,
        score=round(score, 1),
        reasons=reasons,
        suggested_category=suggested_category,
        suggested_sub_type=suggested_sub_type,
    )
