"""
News Momentum — Winner Targeting Layer (V23)

Adds 7 high-leverage filters on top of the base gating logic:
1. Runner-Pattern Filter (low float + cheap + gap + RVOL)
2. ML Win-Probability Tiered Alerts
3. Catalyst × Float Cross-Reference
4. Reaction-Confirmation Window
5. Sector Hype Multiplier (auto-tuned from runner history)
6. Outcome Auto-Resolution helpers
7. Headline NLP Catalyst Strength

These functions are pure / side-effect free where possible, so they can be
called from the gate or the scan loop without changing orchestration shape.
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Deque

from src.core.agentic.news_momentum_models import (
    NewsMomentumCandidate,
    CatalystSubType,
    CatalystCategory,
)
from src.utils.atomic_json import load_json_file, save_json_file

logger = logging.getLogger(__name__)

DATA_DIR = Path("data/agentic")
SECTOR_HYPE_FILE = DATA_DIR / "news_momentum_sector_hype.json"


# ── 1. Runner-Pattern Filter ─────────────────────────────────────────────────

@dataclass
class RunnerProfile:
    """Score 0-4 of the structural traits historical winners share."""
    low_float: bool = False           # < 20M shares
    cheap_price: bool = False         # < $5
    early_gap: bool = False           # premarket / open gap >= 5%
    high_rvol: bool = False           # RVOL >= 3x
    score: int = 0                    # 0-4 sum

    @property
    def is_runner(self) -> bool:
        """Stock structurally capable of a 25%+ move."""
        return self.score >= 3


def compute_runner_profile(c: NewsMomentumCandidate) -> RunnerProfile:
    p = RunnerProfile()
    if c.float_shares is not None and c.float_shares < 20_000_000:
        p.low_float = True
    if c.current_price is not None and c.current_price < 5.0:
        p.cheap_price = True
    if c.move_pct is not None and abs(c.move_pct) >= 5.0:
        p.early_gap = True
    if c.rvol is not None and c.rvol >= 3.0:
        p.high_rvol = True
    p.score = sum([p.low_float, p.cheap_price, p.early_gap, p.high_rvol])
    return p


# ── 2. ML Win-Probability Tiers (percentile-based, V23.1) ────────────────────

@dataclass
class MLTier:
    label: str          # HIGH_CONVICTION / STANDARD / WATCH / VETO
    emoji: str
    threshold_adjust: float  # subtracted from base thresholds
    should_alert: bool       # whether to send immediately


# Cached percentile bands of the trained ML model's historical predictions.
# Precision-first defaults: only top ~15% of scores pass the ML gate, mirroring
# the V23 baseline volume (918 of 11,793 = 7.8%).
_ML_PERCENTILE_BANDS = {
    "p85": 0.20,   # bottom 85% → VETO/WATCH
    "p95": 0.30,   # top 15% → STANDARD
    "p99": 0.40,   # top 5% → HIGH_CONVICTION
}


def set_ml_percentile_bands(p85: float, p95: float, p99: float) -> None:
    """
    Inject calibrated bands. Enforces a minimum spread so the STANDARD /
    HIGH_CONVICTION zones don't collapse when the model produces a tightly
    clustered score distribution (common when the base rate is low).
    """
    if p95 - p85 < 0.02:
        p95 = p85 + 0.02
    if p99 - p95 < 0.02:
        p99 = p95 + 0.02
    _ML_PERCENTILE_BANDS["p85"] = p85
    _ML_PERCENTILE_BANDS["p95"] = p95
    _ML_PERCENTILE_BANDS["p99"] = p99


def classify_ml_tier(win_probability: float, used_model: bool) -> MLTier:
    """
    Bucket the ML win probability using percentile cutoffs of the model's own
    historical score distribution. Precision-first design:

      • Top 5% of scores      → HIGH_CONVICTION
      • Top 5-15% of scores   → STANDARD
      • Top 15-30% of scores  → WATCH (log only, no alert)
      • Bottom 70%            → VETO
    """
    if not used_model:
        return MLTier("STANDARD", "✅", 0.0, True)
    p85 = _ML_PERCENTILE_BANDS["p85"]
    p95 = _ML_PERCENTILE_BANDS["p95"]
    p99 = _ML_PERCENTILE_BANDS["p99"]
    if win_probability >= p99:
        return MLTier("HIGH_CONVICTION", "🚀", 15.0, True)
    if win_probability >= p95:
        return MLTier("STANDARD", "✅", 0.0, True)
    if win_probability >= p85:
        return MLTier("WATCH", "⚠️", -10.0, False)
    return MLTier("VETO", "❌", 0.0, False)


# ── 2b. Catalyst-Specific Auto-Promotion (UPGRADE #3) ───────────────────────

# Narrow list of catalysts that are BOTH rare AND historically high-quality.
# These are allowed to RESCUE alerts from ML veto/watch, but only when
# additional quality gates (news impact, headline strength) are also met.
AUTO_PROMOTE_CATALYSTS = {
    CatalystSubType.FDA_APPROVAL: "HIGH_CONVICTION",     # rare + 67% win
    CatalystSubType.PHASE_3: "HIGH_CONVICTION",          # rare + binary outcome
    CatalystSubType.PDUFA: "HIGH_CONVICTION",            # rare + binary
    CatalystSubType.BREAKTHROUGH_THERAPY: "HIGH_CONVICTION",
    CatalystSubType.GOVERNMENT_CONTRACT: "STANDARD",     # rare + 52%
}

# Minimum news impact score required for a catalyst-based promotion to fire.
# Prevents auto-promoting weak headlines just because they mention "FDA".
AUTO_PROMOTE_MIN_IMPACT = 60.0


def auto_promote_tier(
    current_tier: MLTier,
    catalyst: CatalystSubType,
    is_negative: bool,
    news_impact_score: float = 0.0,
    headline_strength: float = 0.0,
) -> MLTier:
    """
    Promote tier based on catalyst type — but only when the alert is
    independently high-quality (impact + headline strength).
    """
    if is_negative or catalyst not in AUTO_PROMOTE_CATALYSTS:
        return current_tier
    # Quality gates so we don't rescue weak headlines just because they
    # mention a strong catalyst keyword.
    if news_impact_score < AUTO_PROMOTE_MIN_IMPACT:
        return current_tier
    if headline_strength < 50.0:
        return current_tier
    target_label = AUTO_PROMOTE_CATALYSTS[catalyst]
    tier_rank = {"VETO": 0, "WATCH": 1, "STANDARD": 2, "HIGH_CONVICTION": 3}
    if tier_rank.get(target_label, 0) <= tier_rank.get(current_tier.label, 0):
        return current_tier
    if target_label == "HIGH_CONVICTION":
        return MLTier("HIGH_CONVICTION", "🚀", 15.0, True)
    return MLTier("STANDARD", "✅", 0.0, True)


# ── 3. Catalyst × Float Cross-Reference ──────────────────────────────────────

# Built from observation: certain catalysts work best inside specific float /
# market-cap bands. If the combination doesn't match, demand a higher score.
#
# Format: catalyst -> (min_marketcap, max_marketcap) in USD; None = no bound.
CATALYST_MARKET_CAP_BANDS: Dict[CatalystSubType, Tuple[Optional[float], Optional[float]]] = {
    # Biotech needs to be small to actually move on a catalyst
    CatalystSubType.PHASE_1: (None, 500_000_000),
    CatalystSubType.PHASE_2: (None, 1_000_000_000),
    CatalystSubType.PHASE_3: (None, 2_000_000_000),
    CatalystSubType.FDA_APPROVAL: (None, 2_000_000_000),
    CatalystSubType.FDA_CLEARANCE: (None, 1_000_000_000),
    CatalystSubType.TOPLINE_DATA: (None, 1_000_000_000),
    CatalystSubType.BREAKTHROUGH_THERAPY: (None, 1_000_000_000),
    CatalystSubType.PDUFA: (None, 1_000_000_000),

    # Buybacks only meaningful when company is small enough that the buyback
    # is material vs float
    CatalystSubType.SHARE_BUYBACK: (None, 300_000_000),

    # Crypto/AI hype works best on small-caps where one contract reshapes biz
    CatalystSubType.BITCOIN_TREASURY: (None, 500_000_000),
    CatalystSubType.AI_PARTNERSHIP: (None, 2_000_000_000),
    CatalystSubType.NVIDIA_PARTNERSHIP: (None, 5_000_000_000),
    CatalystSubType.OPENAI_PARTNERSHIP: (None, 5_000_000_000),
    CatalystSubType.HYPERSCALER_CONTRACT: (None, 2_000_000_000),

    # Government contracts can work at any cap
    CatalystSubType.GOVERNMENT_CONTRACT: (None, None),

    # Guidance / earnings work best small/mid
    CatalystSubType.GUIDANCE_RAISE: (None, 5_000_000_000),
    CatalystSubType.EARNINGS_BEAT: (None, 5_000_000_000),
    CatalystSubType.PROFITABILITY_INFLECTION: (None, 1_000_000_000),
}


def catalyst_float_match(c: NewsMomentumCandidate) -> bool:
    """True if candidate's market cap fits the catalyst's known winning band."""
    if c.catalyst_sub_type not in CATALYST_MARKET_CAP_BANDS:
        return True  # no rule → accept
    if c.market_cap is None:
        return True  # cannot judge → don't penalize
    lo, hi = CATALYST_MARKET_CAP_BANDS[c.catalyst_sub_type]
    if lo is not None and c.market_cap < lo:
        return False
    if hi is not None and c.market_cap > hi:
        return False
    return True


# ── 4. Reaction-Confirmation Window ──────────────────────────────────────────

@dataclass
class ReactionConfirmation:
    confirmed: bool
    reason: str


def confirm_reaction(c: NewsMomentumCandidate, min_age_seconds: int = 120) -> ReactionConfirmation:
    """
    Confirm that the market is reacting positively before alerting.

    For premarket / after-hours sessions, we use the candidate's `move_pct`
    directly (which tracks change vs prior close).

    For regular session, we expect a recent visible move and rising RVOL.
    """
    if c.detected_at is None:
        return ReactionConfirmation(True, "no_detection_time")

    age = (datetime.now(timezone.utc) - c.detected_at).total_seconds()
    if age < min_age_seconds:
        # Too fresh — let it cook. The orchestrator will revisit on next scan.
        return ReactionConfirmation(False, f"too_fresh({age:.0f}s<{min_age_seconds}s)")

    # Move must agree with sentiment (positive news → positive move)
    if c.move_pct is not None and c.move_pct < 1.5 and not c.is_negative:
        return ReactionConfirmation(False, f"weak_reaction({c.move_pct:.2f}%)")

    # RVOL confirmation (if data available)
    if c.rvol is not None and c.rvol < 1.5:
        return ReactionConfirmation(False, f"no_volume({c.rvol:.1f}x)")

    return ReactionConfirmation(True, "confirmed")


# ── 5. Sector Hype Tracker ───────────────────────────────────────────────────

class SectorHypeTracker:
    """
    Tracks which catalyst sectors are running hot today based on recent
    alert outcomes and price moves. Boosts expected return scores for
    catalysts in currently-hot sectors.
    """

    WINDOW_HOURS = 24
    MIN_SAMPLES = 3

    def __init__(self) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._events: Deque[dict] = deque(maxlen=500)
        self._load()

    def _load(self) -> None:
        raw = load_json_file(SECTOR_HYPE_FILE, default=None)
        if raw:
            for item in raw:
                try:
                    item["ts"] = datetime.fromisoformat(item["ts"])
                    self._events.append(item)
                except Exception:
                    pass

    def _save(self) -> None:
        data = [
            {**e, "ts": e["ts"].isoformat() if isinstance(e["ts"], datetime) else e["ts"]}
            for e in self._events
        ]
        save_json_file(SECTOR_HYPE_FILE, data)

    def record_move(self, category: CatalystCategory, move_pct: float) -> None:
        self._events.append({
            "ts": datetime.now(timezone.utc),
            "category": category.value,
            "move_pct": float(move_pct),
        })
        self._save()

    def get_hype_multiplier(self, category: CatalystCategory) -> float:
        """Return 1.0 (neutral) to 1.2 (hot sector). Multiplies expected return."""
        cutoff = datetime.now(timezone.utc) - timedelta(hours=self.WINDOW_HOURS)
        recent = [e for e in self._events
                  if e["category"] == category.value and e["ts"] >= cutoff]
        if len(recent) < self.MIN_SAMPLES:
            return 1.0
        avg_move = sum(e["move_pct"] for e in recent) / len(recent)
        if avg_move >= 15:
            return 1.20  # very hot
        if avg_move >= 8:
            return 1.10
        if avg_move >= 4:
            return 1.05
        return 1.0


# ── 7. Headline Strength NLP ─────────────────────────────────────────────────

_STRONG_VERBS = re.compile(
    r"\b(acquires?|completes? acquisition|fda approves?|approves|secures?|wins?|"
    r"awarded|granted|delivers? results?|reports? topline|beats? estimates|"
    r"announces? buyback|launches?|signs? definitive|closes? deal|"
    r"breakthrough|fast track designation|orphan drug|"
    r"raises? guidance|increases? guidance|exceeds?)\b",
    re.IGNORECASE,
)
_WEAK_VERBS = re.compile(
    r"\b(to acquire|plans? to|intends? to|exploring|considers?|evaluating|"
    r"may|might|could|expects? to|aims? to|targeting|in talks|rumou?red)\b",
    re.IGNORECASE,
)
_DOLLAR_AMOUNT = re.compile(r"\$\s?[\d.,]+\s?(?:million|billion|m|b)\b", re.IGNORECASE)
_INSIDER_BUYING = re.compile(r"\binsider (?:buy|purchas|acquir)", re.IGNORECASE)
_PERCENTAGE = re.compile(r"\b\d{1,3}\s?%")


def headline_strength_score(headline: str) -> float:
    """
    Score 0-100 of the headline's catalyst strength.
    Higher = more concrete, more material, more likely to drive a move.
    """
    if not headline:
        return 50.0
    score = 50.0
    if _STRONG_VERBS.search(headline):
        score += 20
    if _WEAK_VERBS.search(headline):
        score -= 20
    if _DOLLAR_AMOUNT.search(headline):
        score += 10
    if _INSIDER_BUYING.search(headline):
        score += 15
    if _PERCENTAGE.search(headline):
        score += 5
    # Length sanity: very short or vague titles are usually weak
    word_count = len(headline.split())
    if word_count < 5:
        score -= 10
    return max(0.0, min(100.0, score))


# ── Combined winners gate ────────────────────────────────────────────────────

@dataclass
class WinnerAssessment:
    runner: RunnerProfile
    ml_tier: MLTier
    catalyst_fits_band: bool
    reaction: ReactionConfirmation
    sector_multiplier: float
    headline_strength: float
    # Final composite
    should_alert: bool
    block_reason: Optional[str]
    priority_score: float   # higher = act on this one first


def assess_winner(
    c: NewsMomentumCandidate,
    win_probability: float,
    used_model: bool,
    sector_tracker: SectorHypeTracker,
    require_reaction_confirmation: bool = False,
) -> WinnerAssessment:
    """
    Single integration point. Runs all 7 winner filters PLUS the V23.1
    winner-recovery layer (catalyst auto-promote, runner override on veto,
    velocity promotion, percentile-based ML tiers).
    """
    runner = compute_runner_profile(c)
    base_tier = classify_ml_tier(win_probability, used_model)
    fits_band = catalyst_float_match(c)
    reaction = (confirm_reaction(c) if require_reaction_confirmation
                else ReactionConfirmation(True, "skipped"))
    sector_mult = sector_tracker.get_hype_multiplier(c.catalyst_category)
    headline_str = headline_strength_score(c.headline)

    # ── Tier promotion layer (UPGRADES #2, #3, #5) ───────────────────────
    tier = base_tier
    promotion_reason = ""

    # UPGRADE #3 — Catalyst-specific auto-promotion.
    # Only fires for rare high-quality catalysts WITH supporting quality
    # signals (news_impact >= 60, headline_strength >= 50).
    promoted = auto_promote_tier(
        tier, c.catalyst_sub_type, c.is_negative,
        news_impact_score=c.news_impact_score,
        headline_strength=headline_str,
    )
    if promoted.label != tier.label:
        tier = promoted
        promotion_reason = f"catalyst_{c.catalyst_sub_type.value}"

    # UPGRADE #2 — Runner-score override on ML veto/watch.
    # Strict gate: requires FULL 4/4 runner pattern + strong headline.
    if (tier.label in {"VETO", "WATCH"}
            and runner.score >= 4
            and headline_str >= 70
            and not c.is_negative):
        tier = MLTier("STANDARD", "✅", 0.0, True)
        promotion_reason = f"runner_override({runner.score}/4)"

    # UPGRADE #5 — Multi-source velocity promotion.
    # Requires strong velocity (>= 15) — same story on 4+ sources in minutes.
    if c.velocity_score and c.velocity_score >= 15 and tier.label == "WATCH":
        tier = MLTier("STANDARD", "✅", 0.0, True)
        promotion_reason = f"velocity({c.velocity_score:.0f})"
    elif c.velocity_score and c.velocity_score >= 20 and tier.label == "STANDARD":
        tier = MLTier("HIGH_CONVICTION", "🚀", 15.0, True)
        promotion_reason = f"velocity({c.velocity_score:.0f})"

    # ── Gate decision ────────────────────────────────────────────────────
    block_reason: Optional[str] = None
    should_alert = True

    if tier.label == "VETO":
        should_alert = False
        block_reason = f"ml_veto(win={win_probability:.2f})"
    elif tier.label == "WATCH":
        should_alert = False
        block_reason = f"ml_watch(win={win_probability:.2f})"
    elif not fits_band:
        # Allow override if runner pattern is very strong OR HIGH_CONVICTION
        if runner.is_runner or tier.label == "HIGH_CONVICTION":
            pass
        else:
            should_alert = False
            block_reason = "catalyst_market_cap_mismatch"
    elif not reaction.confirmed:
        should_alert = False
        block_reason = f"reaction_unconfirmed({reaction.reason})"
    elif headline_str < 35:
        should_alert = False
        block_reason = f"weak_headline({headline_str:.0f})"

    # Priority: combines win prob, runner, headline, hype, tier bonus
    tier_bonus = {"HIGH_CONVICTION": 25.0, "STANDARD": 0.0,
                  "WATCH": -15.0, "VETO": -30.0}.get(tier.label, 0.0)
    priority = (
        win_probability * 50.0
        + runner.score * 10.0
        + (headline_str - 50) * 0.4
        + (sector_mult - 1.0) * 50.0
        + tier_bonus
    )

    assessment = WinnerAssessment(
        runner=runner,
        ml_tier=tier,
        catalyst_fits_band=fits_band,
        reaction=reaction,
        sector_multiplier=sector_mult,
        headline_strength=headline_str,
        should_alert=should_alert,
        block_reason=block_reason,
        priority_score=round(priority, 2),
    )
    # Stash promotion reason for telegram / logging
    if promotion_reason:
        assessment.promotion_reason = promotion_reason  # type: ignore[attr-defined]
    return assessment
