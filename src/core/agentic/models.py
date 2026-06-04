"""
Agentic Catalyst Momentum Mode — Data Models

Extends Oracle with catalyst-driven momentum types.
Reuses existing Oracle schemas where applicable.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


# ── Enums ────────────────────────────────────────────────────────────────────


class CatalystType(str, Enum):
    SEC_FILING = "sec_filing"
    SPAC_EXTENSION = "spac_extension"
    MERGER = "merger"
    LEGAL_PATENT = "legal_patent"
    FDA = "fda"
    FDA_REGULATORY = "fda_regulatory"
    CONTRACT = "contract"
    CONTRACT_LICENSING = "contract_licensing"
    EARNINGS = "earnings"
    OFFERING = "offering"
    OFFERING_DILUTION = "offering_dilution"
    OTHER = "other"
    OTHER_NEWS = "other_news"


class FloatCategory(str, Enum):
    ULTRA_LOW = "ultra_low_float"   # <5M
    LOW = "low_float"               # 5-20M
    NORMAL = "normal"               # >20M


class MomentumState(str, Enum):
    INITIAL_SPIKE = "initial_spike"
    SPIKE_PULLBACK = "spike_pullback"
    CONSOLIDATION = "consolidation"
    SECOND_LEG_FORMING = "second_leg_forming"
    CONTINUATION_CONFIRMED = "continuation_confirmed"
    FAILED = "failed"
    DEAD = "dead"


class EntryQuality(str, Enum):
    EARLY = "early"
    IDEAL = "ideal"
    LATE = "late"


class EntryTimingState(str, Enum):
    TOO_EARLY = "too_early"
    WAITING_FOR_CONFIRMATION = "waiting_for_confirmation"
    IDEAL_ENTRY = "ideal_entry"
    LATE_CHASE = "late_chase"
    INVALID_ENTRY = "invalid_entry"


class ConfidenceLevel(str, Enum):
    LOW = "low"             # <50
    WATCH = "watch"         # 50-65
    HIGH = "high"           # 65-80
    VERY_HIGH = "very_high" # >80


class TradingSession(str, Enum):
    PREMARKET = "premarket"
    OPEN = "open"           # 9:30-10:30 ET
    MIDDAY = "midday"       # 10:30-14:00 ET
    POWER_HOUR = "power_hour"  # 15:00-16:00 ET
    AFTERHOURS = "afterhours"


class OutcomeClass(str, Enum):
    CLEAN_CONTINUATION = "clean_continuation"
    PARTIAL = "partial"
    FAILED = "failed"
    DEAD = "dead"


class ABCDState(str, Enum):
    NO_PATTERN = "no_pattern"
    BASE_FORMING = "base_forming"
    BREAKOUT_CONFIRMED = "breakout_confirmed"
    RETEST_IN_PROGRESS = "retest_in_progress"
    RETEST_CONFIRMED = "retest_confirmed"
    CONTINUATION_READY = "continuation_ready"
    FAILED_PATTERN = "failed_pattern"


class ABCDPhase(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"


class MissedClass(str, Enum):
    NOT_DISCOVERED = "not_discovered"
    TOO_LATE = "too_late"
    REJECTED_WRONG = "rejected_wrong"
    LOW_SCORE = "low_score"
    CORRECTLY_AVOIDED = "correctly_avoided"


# ── Catalyst ─────────────────────────────────────────────────────────────────


class CatalystInfo(BaseModel):
    """Describes the news / SEC catalyst driving the stock."""
    catalyst_type: CatalystType = CatalystType.OTHER
    headline: str = ""
    source: str = ""
    url: str = ""
    discovered_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    freshness_minutes: float = 0.0
    strength_score: float = Field(0.0, ge=0, le=100, description="Catalyst strength 0-100")
    sentiment: str = "neutral"  # bullish / bearish / neutral


# ── Float Intelligence ───────────────────────────────────────────────────────


class FloatIntel(BaseModel):
    """Float and share-structure intelligence for a ticker."""
    float_shares: Optional[float] = None
    float_category: FloatCategory = FloatCategory.NORMAL
    shares_outstanding: Optional[float] = None
    market_cap: Optional[float] = None
    redemption_pct: Optional[float] = None      # SPACs only
    dilution_risk: bool = False
    dilution_risk_reason: Optional[str] = None
    float_score: float = Field(50.0, ge=0, le=100, description="Lower float = higher score (opportunity + risk)")
    calibrated: bool = False


# ── Momentum State ───────────────────────────────────────────────────────────


class MomentumSnapshot(BaseModel):
    """Point-in-time momentum classification for a candidate."""
    state: MomentumState = MomentumState.INITIAL_SPIKE
    vwap: Optional[float] = None
    price: Optional[float] = None
    high_of_day: Optional[float] = None
    post_spike_low: Optional[float] = None
    consolidation_bars: int = 0
    higher_low_formed: bool = False
    vwap_reclaimed: bool = False
    breakout_confirmed: bool = False
    volume_persistence_pct: float = 0.0  # Current vol vs spike vol %


# ── Second Leg Probability ───────────────────────────────────────────────────


class SecondLegResult(BaseModel):
    """Probability estimate for a second-leg continuation."""
    probability: float = Field(0.0, ge=0, le=100)
    confidence_level: ConfidenceLevel = ConfidenceLevel.LOW
    components: dict = Field(default_factory=dict)  # per-factor scores
    reasons: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    calibrated: bool = False


# ── Trap Detection ───────────────────────────────────────────────────────────


class TrapResult(BaseModel):
    """Trap / fake-breakout risk assessment."""
    trap_risk_score: float = Field(0.0, ge=0, le=100)
    is_trap: bool = False
    trap_types: list[str] = Field(default_factory=list)  # parabolic_exhaustion, bull_trap, rug_pull, etc.
    reasons: list[str] = Field(default_factory=list)
    calibrated: bool = False


# ── Entry Timing ─────────────────────────────────────────────────────────────


class EntryTimingResult(BaseModel):
    """Entry quality and timing classification."""
    quality: EntryQuality = EntryQuality.EARLY
    timing_state: EntryTimingState = EntryTimingState.TOO_EARLY
    entry_timing_score: int = Field(0, ge=0, le=100)
    entry_zone_low: Optional[float] = None
    entry_zone_high: Optional[float] = None
    ideal_entry_price: Optional[float] = None
    invalidation_level: Optional[float] = None
    stop_level: Optional[float] = None
    target_1: Optional[float] = None
    target_2: Optional[float] = None
    stretch_target: Optional[float] = None
    risk_reward_ratio: float = 0.0
    next_entry_condition: str = ""
    entry_warnings: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)


# ── ABCD Pattern Confirmation ────────────────────────────────────────────────


class ABCDResult(BaseModel):
    """ABCD pattern confirmation result for micro-cap / low-float setups.

    A = tight base / quiet accumulation
    B = breakout on volume
    C = retest confirmation
    D = continuation potential
    """
    abcd_state: ABCDState = ABCDState.NO_PATTERN
    abcd_score: int = Field(0, ge=0, le=100)
    abcd_phase: ABCDPhase = ABCDPhase.A
    abcd_entry_valid: bool = False
    abcd_reasons: list[str] = Field(default_factory=list)
    abcd_warnings: list[str] = Field(default_factory=list)
    abcd_key_level: Optional[float] = None          # resistance / breakout level
    abcd_retest_level: Optional[float] = None         # support after breakout
    abcd_invalidation_level: Optional[float] = None   # below this = pattern failed
    base_formed: bool = False
    breakout_confirmed: bool = False
    retest_confirmed: bool = False
    continuation_ready: bool = False
    pattern_failed: bool = False
    base_tightness_score: int = Field(0, ge=0, le=100)
    breakout_volume_expansion: float = 0.0
    retest_vwap_hold: bool = False
    retest_selling_pressure_declining: bool = False
    higher_lows_count: int = 0
    lower_highs_count: int = 0
    calibrated: bool = False


# ── ML Advisory Prediction ──────────────────────────────────────────────────


class MLPredictionResult(BaseModel):
    """V19 ML advisory prediction for a candidate."""
    model_config = ConfigDict(protected_namespaces=())

    continuation_prob: float = Field(0.5, ge=0, le=1)
    false_alert_prob: float = Field(0.5, ge=0, le=1)
    expected_mfe: float = 0.0
    expected_mae: float = 0.0
    confidence: str = "LOW"  # HIGH, MEDIUM, LOW
    top_shap_features: list[dict] = Field(default_factory=list)
    model_version: str = ""
    predicted_at: str = ""
    fallback_reason: Optional[str] = None
    is_live: bool = False  # only advisory if model is approved
    # V19.1 — Risk-adjusted score & position sizing
    risk_adjusted_score: float = 0.0
    suggested_position_size: str = "NONE"  # NONE, HALF, FULL


# ── Time of Day ──────────────────────────────────────────────────────────────


class TimeOfDayResult(BaseModel):
    """Time-of-day session classification and probability adjustment."""
    session: TradingSession = TradingSession.MIDDAY
    probability_adjustment: float = 0.0  # +/- applied to second_leg prob
    reason: str = ""
    calibrated: bool = False


# ── Failure Velocity ─────────────────────────────────────────────────────────


class FailureVelocityResult(BaseModel):
    """Speed and character of selloff (distribution vs healthy pullback)."""
    velocity_score: float = Field(0.0, ge=0, le=100, description="0=slow/healthy, 100=fast/distribution")
    is_distribution: bool = False
    red_candle_strength: float = 0.0
    sell_volume_ratio: float = 0.0  # sell vol / buy vol in pullback
    reason: str = ""

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ... (rest of the code remains the same)

class QualitySeparatorResult(BaseModel):
    """Post-scoring winner/loser quality separation."""
    quality_separator_score: float = Field(50.0, ge=0, le=100)
    winner_similarity_score: float = Field(50.0, ge=0, le=100)
    loser_similarity_score: float = Field(50.0, ge=0, le=100)
    quality_decision: str = "allow_neutral"  # boost, allow, downgrade, block, allow_neutral
    base_probability: float = 0.0
    quality_adjustment: float = 0.0
    final_probability_after_quality: float = 0.0
    quality_reasons: list[str] = Field(default_factory=list)


# ── Hard Rejection + Asymmetric Scoring ─────────────────────────────────────


class HardRejectionTriggerModel(BaseModel):
    """Serialisable hard-rejection trigger."""
    rule: str
    description: str


class HardRejectionResultModel(BaseModel):
    """Serialisable hard-rejection result for API/storage."""
    triggered: bool = False
    triggers: list[HardRejectionTriggerModel] = Field(default_factory=list)
    rejection_reasons: list[str] = Field(default_factory=list)


class ScoreAdjustmentModel(BaseModel):
    """One penalty or boost entry."""
    name: str
    value: float  # negative = penalty, positive = boost
    reason: str


class AsymmetricScoringResultModel(BaseModel):
    """Asymmetric scoring output with full breakdown for explainability."""
    penalties: list[ScoreAdjustmentModel] = Field(default_factory=list)
    boosts: list[ScoreAdjustmentModel] = Field(default_factory=list)
    raw_penalty_sum: float = 0.0
    raw_boost_sum: float = 0.0
    final_penalty: float = 0.0
    final_boost: float = 0.0
    final_adjustment: float = 0.0
    base_probability: float = 0.0
    final_probability: float = 0.0


# ── V20 News Catalyst Impact Engine ────────────────────────────────────────


class EstimatedMoveRangeModel(BaseModel):
    """Plausible move ranges for a catalyst (V20)."""
    conservative_move_pct: float = 0.0
    bullish_move_pct: float = 0.0
    extreme_squeeze_pct: float = 0.0
    bearish_move_pct: float = 0.0
    rationale: str = ""


class NewsImpactModel(BaseModel):
    """Serializable News Catalyst Impact result (V20).

    Attached to each AgenticCandidate so the frontend / API can render
    catalyst classification, score, decision, estimated move and
    plain-English bull/bear case explanations.
    """
    has_evaluation: bool = False
    catalyst_type: str = "other"
    catalyst_tier: str = "low"
    news_impact_score: float = Field(0.0, ge=0, le=100)
    news_decision: str = "IGNORE"
    oracle_action: str = "IGNORE"
    component_scores: dict = Field(default_factory=dict)
    estimated_move_range: EstimatedMoveRangeModel = Field(default_factory=EstimatedMoveRangeModel)

    is_dilution: bool = False
    is_parabolic: bool = False
    is_unconfirmed: bool = False
    trap_warning: bool = False
    trap_reasons: list[str] = Field(default_factory=list)

    pre_news_accumulation_detected: bool = False
    pre_news_suspicion_score: float = 0.0

    news_summary: str = ""
    why_it_matters: str = ""
    bull_case: str = ""
    bear_case: str = ""
    key_risks: list[str] = Field(default_factory=list)
    impact_reasons: list[str] = Field(default_factory=list)
    impact_warnings: list[str] = Field(default_factory=list)

    sector_hype_multiplier: float = 1.0
    rvol_at_detection: float = 0.0
    pre_news_runup_pct: float = 0.0
    market_cap_at_detection: Optional[float] = None
    float_shares_at_detection: Optional[float] = None
    evaluated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ── Candidate (main composite object) ───────────────────────────────────────


class AgenticCandidate(BaseModel):
    """
    Full composite view of a catalyst-momentum candidate.
    This is the primary object tracked by the Agentic system.
    """
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    ticker: str
    discovered_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # Sub-models
    catalyst: CatalystInfo = Field(default_factory=CatalystInfo)
    float_intel: FloatIntel = Field(default_factory=FloatIntel)
    momentum: MomentumSnapshot = Field(default_factory=MomentumSnapshot)
    second_leg: SecondLegResult = Field(default_factory=SecondLegResult)
    trap: TrapResult = Field(default_factory=TrapResult)
    entry_timing: EntryTimingResult = Field(default_factory=EntryTimingResult)
    time_of_day: TimeOfDayResult = Field(default_factory=TimeOfDayResult)
    failure_velocity: FailureVelocityResult = Field(default_factory=FailureVelocityResult)

    # V18 ABCD Pattern Confirmation Layer
    abcd: ABCDResult = Field(default_factory=ABCDResult)

    # V19 ML Advisory Layer
    ml_prediction: MLPredictionResult = Field(default_factory=MLPredictionResult)

    # V19.1 Market Regime Context
    spy_trend_5d: float = 0.0
    vix_level: float = 20.0
    sector_rsi: float = 50.0
    market_breadth: float = 50.0

    # V19.1 Pre-News Context
    pre_news_suspicion_score: float = 0.0
    pre_news_has_anomaly: bool = False

    # V20 News Catalyst Impact Engine
    news_impact: NewsImpactModel = Field(default_factory=NewsImpactModel)

    # Composite
    final_probability: float = Field(0.0, ge=0, le=100)
    final_confidence: ConfidenceLevel = ConfidenceLevel.LOW
    alertable: bool = False
    rejected: bool = False
    rejection_reasons: list[str] = Field(default_factory=list)

    # Quality Separator
    quality_separator: QualitySeparatorResult = Field(default_factory=QualitySeparatorResult)

    # Hard Rejection + Asymmetric Scoring
    hard_rejection: HardRejectionResultModel = Field(default_factory=HardRejectionResultModel)
    asymmetric_scoring: AsymmetricScoringResultModel = Field(default_factory=AsymmetricScoringResultModel)

    # Monitoring
    active: bool = True
    last_price: Optional[float] = None
    last_volume: Optional[float] = None

    # V17 Entry Timing Alert State Machine
    entry_alert_state: Optional[dict] = None  # Tracks WATCH/ENTRY/AVOID transitions

    def to_summary(self) -> dict:
        return {
            "id": self.id,
            "ticker": self.ticker,
            "last_price": self.last_price,
            "catalyst": self.catalyst.catalyst_type.value,
            "catalyst_headline": self.catalyst.headline[:80] if self.catalyst.headline else "",
            "state": self.momentum.state.value,
            "probability": round(self.final_probability, 1),
            "confidence": self.final_confidence.value,
            "entry_timing_state": self.entry_timing.timing_state.value,
            "entry_timing_score": self.entry_timing.entry_timing_score,
            "entry_zone_low": round(self.entry_timing.entry_zone_low, 4) if self.entry_timing.entry_zone_low else None,
            "entry_zone_high": round(self.entry_timing.entry_zone_high, 4) if self.entry_timing.entry_zone_high else None,
            "ideal_entry_price": round(self.entry_timing.ideal_entry_price, 4) if self.entry_timing.ideal_entry_price else None,
            "invalidation_level": round(self.entry_timing.invalidation_level, 4) if self.entry_timing.invalidation_level else None,
            "stop_level": round(self.entry_timing.stop_level, 4) if self.entry_timing.stop_level else None,
            "target_1": round(self.entry_timing.target_1, 4) if self.entry_timing.target_1 else None,
            "target_2": round(self.entry_timing.target_2, 4) if self.entry_timing.target_2 else None,
            "stretch_target": round(self.entry_timing.stretch_target, 4) if self.entry_timing.stretch_target else None,
            "risk_reward_ratio": round(self.entry_timing.risk_reward_ratio, 2) if self.entry_timing.risk_reward_ratio else None,
            "next_entry_condition": self.entry_timing.next_entry_condition,
            "entry_warnings": self.entry_timing.entry_warnings,
            "entry_timing": {
                "timing_state": self.entry_timing.timing_state.value,
                "quality": self.entry_timing.quality.value,
                "entry_timing_score": self.entry_timing.entry_timing_score,
                "entry_zone_low": round(self.entry_timing.entry_zone_low, 4) if self.entry_timing.entry_zone_low else None,
                "entry_zone_high": round(self.entry_timing.entry_zone_high, 4) if self.entry_timing.entry_zone_high else None,
                "ideal_entry_price": round(self.entry_timing.ideal_entry_price, 4) if self.entry_timing.ideal_entry_price else None,
                "invalidation_level": round(self.entry_timing.invalidation_level, 4) if self.entry_timing.invalidation_level else None,
                "stop_level": round(self.entry_timing.stop_level, 4) if self.entry_timing.stop_level else None,
                "target_1": round(self.entry_timing.target_1, 4) if self.entry_timing.target_1 else None,
                "target_2": round(self.entry_timing.target_2, 4) if self.entry_timing.target_2 else None,
                "stretch_target": round(self.entry_timing.stretch_target, 4) if self.entry_timing.stretch_target else None,
                "risk_reward_ratio": round(self.entry_timing.risk_reward_ratio, 2) if self.entry_timing.risk_reward_ratio else None,
                "next_entry_condition": self.entry_timing.next_entry_condition,
                "entry_warnings": self.entry_timing.entry_warnings,
                "reasons": self.entry_timing.reasons,
            },
            "trap_risk": round(self.trap.trap_risk_score, 1),
            "entry_quality": self.entry_timing.quality.value,
            "vwap_reclaimed": self.momentum.vwap_reclaimed,
            "higher_low": self.momentum.higher_low_formed,
            "alertable": self.alertable,
            "active": self.active,
            "quality_separator_score": round(self.quality_separator.quality_separator_score, 1),
            "quality_decision": self.quality_separator.quality_decision,
            "winner_similarity": round(self.quality_separator.winner_similarity_score, 1),
            "abcd_state": self.abcd.abcd_state.value,
            "abcd_phase": self.abcd.abcd_phase.value,
            "abcd_score": self.abcd.abcd_score,
            "abcd_entry_valid": self.abcd.abcd_entry_valid,
            "abcd_key_level": round(self.abcd.abcd_key_level, 4) if self.abcd.abcd_key_level else None,
            "abcd_retest_level": round(self.abcd.abcd_retest_level, 4) if self.abcd.abcd_retest_level else None,
            "abcd_invalidation_level": round(self.abcd.abcd_invalidation_level, 4) if self.abcd.abcd_invalidation_level else None,
            "abcd_reasons": self.abcd.abcd_reasons,
            "abcd_warnings": self.abcd.abcd_warnings,
            "loser_similarity": round(self.quality_separator.loser_similarity_score, 1),
            "hard_rejection_triggered": self.hard_rejection.triggered,
            "rejection_reasons": list(self.hard_rejection.rejection_reasons),
            "penalty_count": len(self.asymmetric_scoring.penalties),
            "boost_count": len(self.asymmetric_scoring.boosts),
            "final_adjustment": round(self.asymmetric_scoring.final_adjustment, 2),
            # V19 ML Advisory
            "ml_continuation_prob": round(self.ml_prediction.continuation_prob, 3),
            "ml_false_alert_prob": round(self.ml_prediction.false_alert_prob, 3),
            "ml_expected_mfe": round(self.ml_prediction.expected_mfe, 2),
            "ml_expected_mae": round(self.ml_prediction.expected_mae, 2),
            "ml_confidence": self.ml_prediction.confidence,
            "ml_model_version": self.ml_prediction.model_version,
            "ml_is_live": self.ml_prediction.is_live,
            # V19.1 — Position sizing + risk-adjusted score
            "ml_risk_adjusted_score": round(self.ml_prediction.risk_adjusted_score, 2),
            "ml_suggested_position_size": self.ml_prediction.suggested_position_size,
            # V19.1 — Market regime
            "spy_trend_5d": round(self.spy_trend_5d, 2),
            "vix_level": round(self.vix_level, 1),
            "sector_rsi": round(self.sector_rsi, 1),
            "market_breadth": round(self.market_breadth, 1),
            # V19.1 — Pre-news
            "pre_news_suspicion_score": round(self.pre_news_suspicion_score, 1),
            "pre_news_has_anomaly": self.pre_news_has_anomaly,
            # V20 — News Catalyst Impact Engine
            "news_impact": {
                "has_evaluation": self.news_impact.has_evaluation,
                "catalyst_type": self.news_impact.catalyst_type,
                "catalyst_tier": self.news_impact.catalyst_tier,
                "news_impact_score": round(self.news_impact.news_impact_score, 1),
                "news_decision": self.news_impact.news_decision,
                "oracle_action": self.news_impact.oracle_action,
                "estimated_move_range": {
                    "conservative_move_pct": round(self.news_impact.estimated_move_range.conservative_move_pct, 1),
                    "bullish_move_pct": round(self.news_impact.estimated_move_range.bullish_move_pct, 1),
                    "extreme_squeeze_pct": round(self.news_impact.estimated_move_range.extreme_squeeze_pct, 1),
                    "bearish_move_pct": round(self.news_impact.estimated_move_range.bearish_move_pct, 1),
                    "rationale": self.news_impact.estimated_move_range.rationale,
                },
                "is_dilution": self.news_impact.is_dilution,
                "is_parabolic": self.news_impact.is_parabolic,
                "is_unconfirmed": self.news_impact.is_unconfirmed,
                "trap_warning": self.news_impact.trap_warning,
                "trap_reasons": list(self.news_impact.trap_reasons),
                "pre_news_accumulation_detected": self.news_impact.pre_news_accumulation_detected,
                "news_summary": self.news_impact.news_summary,
                "why_it_matters": self.news_impact.why_it_matters,
                "bull_case": self.news_impact.bull_case,
                "bear_case": self.news_impact.bear_case,
                "key_risks": list(self.news_impact.key_risks),
                "impact_reasons": list(self.news_impact.impact_reasons),
                "impact_warnings": list(self.news_impact.impact_warnings),
                "sector_hype_multiplier": round(self.news_impact.sector_hype_multiplier, 2),
                "rvol_at_detection": round(self.news_impact.rvol_at_detection, 2),
                "pre_news_runup_pct": round(self.news_impact.pre_news_runup_pct, 2),
            },
            "discovered_at": self.discovered_at.isoformat(),
        }


# ── Outcome Tracking ────────────────────────────────────────────────────────


class AgenticOutcome(BaseModel):
    """Post-trade outcome for learning with full candidate snapshot."""
    candidate_id: str
    ticker: str
    outcome_class: OutcomeClass = OutcomeClass.FAILED
    entry_price: Optional[float] = None
    peak_price: Optional[float] = None
    exit_price: Optional[float] = None
    max_favorable_excursion_pct: Optional[float] = None
    max_adverse_excursion_pct: Optional[float] = None
    targets_hit: int = 0
    vwap_held: bool = False

    # ── Feature snapshot at discovery (for correlation analysis) ─────────
    state: Optional[str] = None                        # momentum state
    probability: Optional[float] = None                # second-leg probability
    trap_risk: Optional[float] = None                # trap risk score
    volume_persistence: Optional[float] = None       # volume persistence %
    higher_low_formed: bool = False
    float_category: Optional[str] = None
    catalyst_type: Optional[str] = None
    catalyst_strength: Optional[float] = None
    time_of_day_session: Optional[str] = None
    entry_quality: Optional[str] = None
    rejected: bool = False
    alertable: bool = False
    rejection_reasons: list[str] = Field(default_factory=list)

    recorded_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ── Missed Opportunity ───────────────────────────────────────────────────────


class MissedOpportunity(BaseModel):
    """End-of-day record for a big mover that was missed or rejected."""
    ticker: str
    date: str  # YYYY-MM-DD
    move_pct: float
    high_price: float
    low_price: float
    volume: float
    classification: MissedClass = MissedClass.NOT_DISCOVERED
    was_discovered: bool = False
    was_alerted: bool = False
    was_rejected: bool = False
    rejection_reason: Optional[str] = None
    candidate_probability_at_time: Optional[float] = None
    lessons: list[str] = Field(default_factory=list)


# ── Learning Weights ─────────────────────────────────────────────────────────


class LearningWeights(BaseModel):
    """Adjustable weight configuration for the second-leg probability engine."""
    version: int = 1
    catalyst_strength_w: float = 0.20
    catalyst_freshness_w: float = 0.10
    float_w: float = 0.10
    volume_persistence_w: float = 0.15
    vwap_position_w: float = 0.10
    higher_low_w: float = 0.10
    consolidation_quality_w: float = 0.10
    breakout_strength_w: float = 0.05
    spread_liquidity_w: float = 0.05
    time_of_day_w: float = 0.05
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    sample_size: int = 0


# ── Alert Serialization ───────────────────────────────────────────────────────


class AgenticAlert(BaseModel):
    """
    Serializable alert emitted by the orchestrator.
    Designed for Telegram, webhooks, dashboards.
    V17: enriched with entry timing state, score, zones, targets, R:R.
    """
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    ticker: str
    alert_type: str  # "watch", "entry", "avoid", "trap_warning", "reversal"
    timing_state: str = ""  # V17: too_early, waiting, ideal_entry, late_chase, invalid
    timing_score: int = 0  # V17: 0-100
    headline: str
    probability: float = Field(0.0, ge=0, le=100)
    entry_zone_low: Optional[float] = None
    entry_zone_high: Optional[float] = None
    ideal_entry_price: Optional[float] = None
    invalidation_level: Optional[float] = None
    stop_level: Optional[float] = None
    target_1: Optional[float] = None
    target_2: Optional[float] = None
    stretch_target: Optional[float] = None
    risk_reward_ratio: Optional[float] = None
    next_entry_condition: str = ""  # V17: what to wait for
    warnings: list[str] = Field(default_factory=list)  # V17: entry_warnings
    reasons: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
