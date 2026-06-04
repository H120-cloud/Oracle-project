"""
Asymmetric Scoring + Hard Rejection Rule Engine.

Design principles:
    - Reward winners modestly  (max boost +12)
    - Punish losers aggressively  (max penalty -20)
    - Hard rules are deterministic, capital-protective, and override scoring
    - Priority: HARD REJECTION -> BASE -> QUALITY SEPARATOR -> ASYMMETRIC -> FINAL
    - All adjustments are fully explainable (per-rule breakdown)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from src.core.agentic.models import (
    AgenticCandidate,
    MomentumState,
    TradingSession,
    EntryQuality,
    FloatCategory,
)

logger = logging.getLogger(__name__)

# ── Asymmetric caps ─────────────────────────────────────────────────────────
MAX_BOOST = 12.0
MAX_PENALTY = -20.0

# ── Hard rule thresholds ────────────────────────────────────────────────────
TRAP_EXTREME_SCORE = 70.0
FAILED_SECOND_LEG_PROB = 40.0
LATE_EXTENDED_PCT = 25.0
LATE_EXTENDED_CONSOLIDATION_BARS = 3
POWER_HOUR_FALSE_ALERT_RATE = 55.0
LOW_LIQUIDITY_VOL_PERSIST = 30.0
NEWS_PRICED_IN_PCT = 40.0


class RejectionRule(str, Enum):
    """Deterministic hard-rejection rule identifiers."""
    TRAP_EXTREME = "trap_extreme"
    FAILED_SECOND_LEG = "failed_second_leg"
    LATE_EXTENDED_MOVE = "late_extended_move"
    POWER_HOUR_WEAKNESS = "power_hour_weakness"
    LOW_LIQUIDITY_HIGH_SPREAD = "low_liquidity_high_spread"
    NEWS_ALREADY_PRICED_IN = "news_already_priced_in"
    DISTRIBUTION_PATTERN = "distribution_pattern"


@dataclass
class RejectionTrigger:
    """One hard-rule trigger with explanation."""
    rule: RejectionRule
    description: str


@dataclass
class ScoreAdjustment:
    """One penalty or boost entry."""
    name: str
    value: float          # negative = penalty, positive = boost
    reason: str


@dataclass
class HardRejectionResult:
    """Deterministic rejection check outcome."""
    triggered: bool = False
    triggers: list[RejectionTrigger] = field(default_factory=list)

    @property
    def rejection_reasons(self) -> list[str]:
        return [f"[{t.rule.value}] {t.description}" for t in self.triggers]

    def to_dict(self) -> dict:
        return {
            "triggered": self.triggered,
            "triggers": [
                {"rule": t.rule.value, "description": t.description}
                for t in self.triggers
            ],
            "rejection_reasons": self.rejection_reasons,
        }


@dataclass
class AsymmetricScoringResult:
    """Asymmetric scoring outcome with full breakdown."""
    penalties: list[ScoreAdjustment] = field(default_factory=list)
    boosts: list[ScoreAdjustment] = field(default_factory=list)
    raw_penalty_sum: float = 0.0
    raw_boost_sum: float = 0.0
    final_penalty: float = 0.0        # capped at MAX_PENALTY
    final_boost: float = 0.0          # capped at MAX_BOOST, zeroed if any major penalty
    final_adjustment: float = 0.0     # penalty + boost (signed)
    base_probability: float = 0.0
    final_probability: float = 0.0

    def to_dict(self) -> dict:
        return {
            "penalties": [{"name": p.name, "value": p.value, "reason": p.reason} for p in self.penalties],
            "boosts": [{"name": b.name, "value": b.value, "reason": b.reason} for b in self.boosts],
            "raw_penalty_sum": round(self.raw_penalty_sum, 2),
            "raw_boost_sum": round(self.raw_boost_sum, 2),
            "final_penalty": round(self.final_penalty, 2),
            "final_boost": round(self.final_boost, 2),
            "final_adjustment": round(self.final_adjustment, 2),
            "base_probability": round(self.base_probability, 2),
            "final_probability": round(self.final_probability, 2),
        }


# ════════════════════════════════════════════════════════════════════════════
# Hard Rejection Engine
# ════════════════════════════════════════════════════════════════════════════


class HardRejectionEngine:
    """
    Deterministic rule engine that runs BEFORE alert decision.
    Any triggered rule blocks the candidate regardless of probability.

    Context dict may contain optional runtime data not present on the candidate:
        - spread_bps: float
        - move_from_base_pct: float
        - distance_from_vwap_pct: float
        - power_hour_false_alert_rate: float (0-100)
        - has_fresh_catalyst: bool
    """

    def evaluate(
        self,
        cand: AgenticCandidate,
        context: Optional[dict] = None,
    ) -> HardRejectionResult:
        ctx = context or {}
        result = HardRejectionResult()

        # Rule 1: TRAP EXTREME
        self._rule_trap_extreme(cand, result)
        # Rule 2: FAILED SECOND LEG STRUCTURE
        self._rule_failed_second_leg(cand, result)
        # Rule 3: LATE EXTENDED MOVE
        self._rule_late_extended_move(cand, ctx, result)
        # Rule 4: POWER HOUR WEAKNESS
        self._rule_power_hour_weakness(cand, ctx, result)
        # Rule 5: LOW LIQUIDITY + HIGH SPREAD
        self._rule_low_liquidity_high_spread(cand, ctx, result)
        # Rule 6: NEWS ALREADY PRICED IN
        self._rule_news_priced_in(cand, ctx, result)
        # Rule 7: DISTRIBUTION PATTERN
        self._rule_distribution_pattern(cand, result)

        result.triggered = len(result.triggers) > 0
        return result

    # ── Rule 1 ─────────────────────────────────────────────────────────────
    def _rule_trap_extreme(self, cand: AgenticCandidate, result: HardRejectionResult):
        trap_risk = cand.trap.trap_risk_score
        has_upper_wick = any(
            t in cand.trap.trap_types
            for t in ("heavy_upper_wicks", "parabolic_exhaustion", "bull_trap")
        )
        if trap_risk > TRAP_EXTREME_SCORE and has_upper_wick:
            result.triggers.append(RejectionTrigger(
                rule=RejectionRule.TRAP_EXTREME,
                description=(
                    f"Trap risk {trap_risk:.0f} > {TRAP_EXTREME_SCORE:.0f} with "
                    f"upper-wick dominance ({', '.join(cand.trap.trap_types)})"
                ),
            ))

    # ── Rule 2 ─────────────────────────────────────────────────────────────
    def _rule_failed_second_leg(self, cand: AgenticCandidate, result: HardRejectionResult):
        declining = cand.momentum.state in (MomentumState.FAILED, MomentumState.DEAD)
        if cand.second_leg.probability < FAILED_SECOND_LEG_PROB and declining:
            result.triggers.append(RejectionTrigger(
                rule=RejectionRule.FAILED_SECOND_LEG,
                description=(
                    f"Second-leg probability {cand.second_leg.probability:.0f} < "
                    f"{FAILED_SECOND_LEG_PROB:.0f} with momentum {cand.momentum.state.value}"
                ),
            ))

    # ── Rule 3 ─────────────────────────────────────────────────────────────
    def _rule_late_extended_move(
        self,
        cand: AgenticCandidate,
        ctx: dict,
        result: HardRejectionResult,
    ):
        # Prefer runtime-supplied distance_from_vwap_pct; fall back to trap types.
        dist_vwap = ctx.get("distance_from_vwap_pct")
        extended_flag = "extreme_extension" in cand.trap.trap_types
        consolidation_bars = cand.momentum.consolidation_bars
        no_consolidation = consolidation_bars < LATE_EXTENDED_CONSOLIDATION_BARS

        extended = False
        detail = ""
        if dist_vwap is not None and dist_vwap > LATE_EXTENDED_PCT:
            extended = True
            detail = f"price {dist_vwap:.0f}% above VWAP/base"
        elif extended_flag:
            extended = True
            detail = "trap detector flagged extreme extension"

        if extended and no_consolidation:
            result.triggers.append(RejectionTrigger(
                rule=RejectionRule.LATE_EXTENDED_MOVE,
                description=(
                    f"Late extended move ({detail}) with only "
                    f"{consolidation_bars} consolidation bar(s)"
                ),
            ))

    # ── Rule 4 ─────────────────────────────────────────────────────────────
    def _rule_power_hour_weakness(
        self,
        cand: AgenticCandidate,
        ctx: dict,
        result: HardRejectionResult,
    ):
        if cand.time_of_day.session != TradingSession.POWER_HOUR:
            return
        rate = ctx.get("power_hour_false_alert_rate")
        # If rate unknown, skip the rule (cannot determine deterministically)
        if rate is None:
            return
        if rate > POWER_HOUR_FALSE_ALERT_RATE:
            result.triggers.append(RejectionTrigger(
                rule=RejectionRule.POWER_HOUR_WEAKNESS,
                description=(
                    f"Power-hour session with historical false-alert rate "
                    f"{rate:.1f}% > {POWER_HOUR_FALSE_ALERT_RATE:.0f}%"
                ),
            ))

    # ── Rule 5 ─────────────────────────────────────────────────────────────
    def _rule_low_liquidity_high_spread(
        self,
        cand: AgenticCandidate,
        ctx: dict,
        result: HardRejectionResult,
    ):
        spread_bps = ctx.get("spread_bps")
        spread_threshold = ctx.get("spread_threshold_bps", 50.0)  # 0.5%
        weak_volume = cand.momentum.volume_persistence_pct < LOW_LIQUIDITY_VOL_PERSIST

        # Rule requires BOTH conditions; spread is optional runtime data
        if spread_bps is not None and spread_bps > spread_threshold and weak_volume:
            result.triggers.append(RejectionTrigger(
                rule=RejectionRule.LOW_LIQUIDITY_HIGH_SPREAD,
                description=(
                    f"Spread {spread_bps:.0f}bps > {spread_threshold:.0f}bps with "
                    f"volume persistence {cand.momentum.volume_persistence_pct:.0f}% "
                    f"< {LOW_LIQUIDITY_VOL_PERSIST:.0f}%"
                ),
            ))

    # ── Rule 6 ─────────────────────────────────────────────────────────────
    def _rule_news_priced_in(
        self,
        cand: AgenticCandidate,
        ctx: dict,
        result: HardRejectionResult,
    ):
        move_pct = ctx.get("move_from_base_pct")
        # Fall back to extreme_extension flag if no explicit move data
        strong_move = False
        detail = ""
        if move_pct is not None and move_pct > NEWS_PRICED_IN_PCT:
            strong_move = True
            detail = f"{move_pct:.0f}% move already printed"
        elif "extreme_extension" in cand.trap.trap_types:
            strong_move = True
            detail = "extreme_extension flagged by trap detector"

        has_fresh_catalyst = ctx.get("has_fresh_catalyst", True)
        if strong_move and not has_fresh_catalyst:
            result.triggers.append(RejectionTrigger(
                rule=RejectionRule.NEWS_ALREADY_PRICED_IN,
                description=f"News already priced in ({detail}) with no fresh catalyst",
            ))

    # ── Rule 7 ─────────────────────────────────────────────────────────────
    def _rule_distribution_pattern(self, cand: AgenticCandidate, result: HardRejectionResult):
        is_distribution = (
            cand.failure_velocity.is_distribution
            or "distribution" in cand.trap.trap_types
        )
        heavy_wicks = "heavy_upper_wicks" in cand.trap.trap_types
        # multiple upper wicks + distribution (falling volume on pushes)
        if is_distribution and heavy_wicks:
            result.triggers.append(RejectionTrigger(
                rule=RejectionRule.DISTRIBUTION_PATTERN,
                description=(
                    "Distribution pattern: multiple upper wicks with decreasing "
                    "volume on upward pushes"
                ),
            ))
        elif cand.failure_velocity.is_distribution and cand.failure_velocity.sell_volume_ratio > 1.5:
            result.triggers.append(RejectionTrigger(
                rule=RejectionRule.DISTRIBUTION_PATTERN,
                description=(
                    f"Distribution detected: sell/buy volume ratio "
                    f"{cand.failure_velocity.sell_volume_ratio:.2f}"
                ),
            ))


# ════════════════════════════════════════════════════════════════════════════
# Asymmetric Scoring Engine
# ════════════════════════════════════════════════════════════════════════════


class AsymmetricScoringEngine:
    """
    Apply asymmetric final scoring:
        - Penalties dominate (-20 max)
        - Boosts modest (+12 max)
        - Boosts are zeroed when any major penalty (<= -10) exists
    """

    # Threshold: any single penalty <= -10 is 'major' and disables boost stack
    MAJOR_PENALTY_THRESHOLD = -10.0

    def score(
        self,
        cand: AgenticCandidate,
        base_probability: float,
        context: Optional[dict] = None,
    ) -> AsymmetricScoringResult:
        ctx = context or {}
        result = AsymmetricScoringResult(base_probability=base_probability)

        # ── Collect penalties ───────────────────────────────────────────────
        self._collect_penalties(cand, ctx, result)
        # ── Collect boosts ──────────────────────────────────────────────────
        self._collect_boosts(cand, ctx, result)

        # ── Aggregate ──────────────────────────────────────────────────────
        result.raw_penalty_sum = sum(p.value for p in result.penalties)
        result.raw_boost_sum = sum(b.value for b in result.boosts)

        # Cap penalty at MAX_PENALTY (more negative floor)
        result.final_penalty = max(result.raw_penalty_sum, MAX_PENALTY)

        # Guardrail: if any major penalty exists, zero out boosts
        has_major_penalty = any(
            p.value <= self.MAJOR_PENALTY_THRESHOLD for p in result.penalties
        )
        if has_major_penalty:
            result.final_boost = 0.0
        else:
            result.final_boost = min(result.raw_boost_sum, MAX_BOOST)

        result.final_adjustment = result.final_penalty + result.final_boost
        result.final_probability = round(
            max(0.0, min(100.0, base_probability + result.final_adjustment)),
            2,
        )
        return result

    # ── Penalty collection ─────────────────────────────────────────────────
    def _collect_penalties(
        self,
        cand: AgenticCandidate,
        ctx: dict,
        result: AsymmetricScoringResult,
    ):
        # Trap risk in 50-70 range
        tr = cand.trap.trap_risk_score
        if 50.0 <= tr <= 70.0:
            # Graduate: 50 -> -10, 70 -> -15
            value = -10.0 - ((tr - 50.0) / 20.0) * 5.0
            result.penalties.append(ScoreAdjustment(
                name="moderate_trap_risk",
                value=round(value, 2),
                reason=f"Trap risk {tr:.0f} (moderate 50-70 range)",
            ))
        elif tr > 70.0:
            # Strong loser zone but not in hard block - still penalise
            result.penalties.append(ScoreAdjustment(
                name="high_trap_risk",
                value=-15.0,
                reason=f"Trap risk {tr:.0f} (severe)",
            ))

        # Weak VWAP hold
        if not cand.momentum.vwap_reclaimed:
            result.penalties.append(ScoreAdjustment(
                name="weak_vwap_hold",
                value=-8.0,
                reason="VWAP not reclaimed",
            ))

        # Fading volume
        vp = cand.momentum.volume_persistence_pct
        if vp < 40.0:
            result.penalties.append(ScoreAdjustment(
                name="fading_volume",
                value=-6.0,
                reason=f"Volume persistence {vp:.0f}% (<40%)",
            ))

        # Mid-day low momentum
        if (
            cand.time_of_day.session == TradingSession.MIDDAY
            and cand.momentum.state in (MomentumState.CONSOLIDATION, MomentumState.SPIKE_PULLBACK)
            and vp < 50.0
        ):
            result.penalties.append(ScoreAdjustment(
                name="midday_low_momentum",
                value=-5.0,
                reason="Mid-day session with low momentum",
            ))

        # Inconsistent order flow (sell_volume_ratio > 1.2 in pullback)
        if cand.failure_velocity.sell_volume_ratio > 1.2:
            result.penalties.append(ScoreAdjustment(
                name="inconsistent_order_flow",
                value=-5.0,
                reason=(
                    f"Sell/buy volume ratio "
                    f"{cand.failure_velocity.sell_volume_ratio:.2f} > 1.2"
                ),
            ))

        # Strong loser signals (compound penalty)
        if cand.failure_velocity.is_distribution and tr >= 60.0:
            result.penalties.append(ScoreAdjustment(
                name="strong_loser_signals",
                value=-15.0,
                reason="Distribution + high trap risk combined",
            ))

    # ── Boost collection ───────────────────────────────────────────────────
    def _collect_boosts(
        self,
        cand: AgenticCandidate,
        ctx: dict,
        result: AsymmetricScoringResult,
    ):
        # Opening session + strong volume + VWAP hold -> +10
        if (
            cand.time_of_day.session == TradingSession.OPEN
            and cand.momentum.volume_persistence_pct >= 60.0
            and cand.momentum.vwap_reclaimed
        ):
            result.boosts.append(ScoreAdjustment(
                name="opening_session_alignment",
                value=10.0,
                reason="Opening session + strong volume + VWAP hold",
            ))

        # Ultra-low float + clean breakout + volume persistence -> +12
        if (
            cand.float_intel.float_category == FloatCategory.ULTRA_LOW
            and cand.momentum.breakout_confirmed
            and cand.momentum.volume_persistence_pct >= 70.0
        ):
            result.boosts.append(ScoreAdjustment(
                name="ultra_low_float_breakout",
                value=12.0,
                reason="Ultra-low float + clean breakout + sustained volume",
            ))

        # Second-leg confirmation + momentum expansion -> +8
        if (
            cand.momentum.state == MomentumState.CONTINUATION_CONFIRMED
            and cand.second_leg.probability >= 70.0
        ):
            result.boosts.append(ScoreAdjustment(
                name="second_leg_confirmed",
                value=8.0,
                reason="Second-leg confirmation with momentum expansion",
            ))

        # Pre-news anomaly + tight consolidation -> +9
        pre_news_matched = bool(ctx.get("pre_news_anomaly_matched"))
        tight_consolidation = (
            cand.momentum.consolidation_bars >= 5
            and cand.momentum.state == MomentumState.CONSOLIDATION
        )
        if pre_news_matched and tight_consolidation:
            result.boosts.append(ScoreAdjustment(
                name="pre_news_tight_consolidation",
                value=9.0,
                reason="Pre-news anomaly + tight consolidation",
            ))


__all__ = [
    "MAX_BOOST",
    "MAX_PENALTY",
    "RejectionRule",
    "RejectionTrigger",
    "ScoreAdjustment",
    "HardRejectionResult",
    "AsymmetricScoringResult",
    "HardRejectionEngine",
    "AsymmetricScoringEngine",
]
