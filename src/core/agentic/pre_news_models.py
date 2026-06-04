"""
Pre-News Volume Anomaly Detector — Data Models

Defines all types for volume anomaly detection, classification,
scoring, news-lag tracking, and learning.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# ── Enums ─────────────────────────────────────────────────────────────────────


class AnomalyType(str, Enum):
    UNUSUAL_VOLUME_NO_NEWS = "unusual_volume_no_news"
    VOLUME_BEFORE_NEWS = "volume_before_news"
    HIDDEN_ACCUMULATION = "hidden_accumulation"
    EARLY_BREAKOUT_POSITIONING = "early_breakout_positioning"
    SUSPICIOUS_PUMP_RISK = "suspicious_pump_risk"
    QUIET_VOLUME_BUILD = "quiet_volume_build"  # V2: rising volume + minimal price move, highest-value early signal


class TimingStage(str, Enum):
    """V2: Where in the move lifecycle this anomaly sits."""
    EARLY = "early"              # Volume building, price has not moved yet
    DEVELOPING = "developing"    # Volume confirmed, early price confirmation
    LATE = "late"                # Move already visible, momentum established
    EXHAUSTED = "exhausted"      # Volume fading after move — likely distribution


class MoveType(str, Enum):
    """V2: Predicted move type based on pattern signature."""
    NEWS_BREAKOUT = "news_breakout"                    # Accumulation before news drop
    MOMENTUM_CONTINUATION = "momentum_continuation"    # Existing trend continuing
    LOW_FLOAT_SQUEEZE = "low_float_squeeze"            # Low-float compression signal
    GRADUAL_ACCUMULATION = "gradual_accumulation"      # Slow steady buying
    PUMP_AND_DUMP = "pump_and_dump"                    # High risk manipulation signature
    UNKNOWN = "unknown"


class SessionQuality(str, Enum):
    """V2: Current session liquidity / noise profile."""
    PREMARKET = "premarket"
    OPEN = "open"                # 9:30–10:30 ET — high quality
    MORNING = "morning"          # 10:30–12:00 ET — good
    MIDDAY = "midday"            # 12:00–14:00 ET — chop, low quality
    POWER_HOUR = "power_hour"    # 14:00–15:30 ET — good
    CLOSE = "close"              # 15:30–16:00 ET — noisy
    AFTERHOURS = "afterhours"


class PriceBehaviour(str, Enum):
    QUIET_ACCUMULATION = "quiet_accumulation"
    CONTROLLED_MOVE = "controlled_move"
    BREAKOUT_BUILDING = "breakout_building"
    ALREADY_EXTENDED = "already_extended"
    REJECTION = "rejection"
    FAILED_SPIKE = "failed_spike"
    DISTRIBUTION = "distribution"


class NewsStatus(str, Enum):
    # Legacy aliases preserved for backward compatibility
    NO_NEWS_FOUND = "no_news_found"
    NEWS_ALREADY_VISIBLE = "news_already_visible"
    SEC_FILING_VISIBLE = "sec_filing_visible"
    NEWS_LAG_CONFIRMED = "news_lag_confirmed"
    UNKNOWN_NEWS_STATUS = "unknown_news_status"
    # V3 — granular catalyst visibility
    NO_PUBLIC_NEWS_FOUND_IN_SOURCES = "no_public_news_found_in_sources"
    PUBLIC_CATALYST_ALREADY_VISIBLE = "public_catalyst_already_visible"
    NEWS_APPEARED_AFTER_DETECTION = "news_appeared_after_detection"
    UNVERIFIED_CATALYST = "unverified_catalyst"
    OLD_CATALYST_PRESENT = "old_catalyst_present"


class SuspicionLevel(str, Enum):
    LOW = "low"           # < 45
    WATCH = "watch"       # 45–60
    HIGH = "high"         # 60–75
    EXTREME = "extreme"   # > 75


class DataQuality(str, Enum):
    FULL = "full"
    PARTIAL = "partial"
    DEGRADED = "degraded"
    STALE = "stale"


class PreNewsState(str, Enum):
    """Current monitoring state for a pre-news anomaly."""
    PRE_NEWS_WATCH = "pre_news_watch"
    CATALYST_CONFIRMED = "catalyst_confirmed"
    VOLUME_FADED = "volume_faded"
    REJECTED = "rejected"
    EXPIRED = "expired"


class MissedAnomalyClass(str, Enum):
    CAUGHT_EARLY = "caught_early"
    CAUGHT_LATE = "caught_late"
    MISSED_NO_VOLUME_SIGNAL = "missed_no_volume_signal"
    MISSED_NOT_IN_UNIVERSE = "missed_not_in_universe"
    MISSED_DATA_UNAVAILABLE = "missed_data_unavailable"
    CORRECTLY_IGNORED = "correctly_ignored"


class AlertQuality(str, Enum):
    """V3: Signal quality based on VWAP distance and price structure."""
    EARLY = "early"              # 0-8% above VWAP, best zone
    CAUTION = "caution"          # 8-15% above VWAP, still valid but late
    LATE = "late"                # >15% above VWAP or already extended
    TRAP_RISK = "trap_risk"      # rejection, distribution, failed spike
    SUPPRESSED = "suppressed"    # filtered out by safety checks


class CatalystAgeBucket(str, Enum):
    """V3: How old the matched catalyst is."""
    WITHIN_2H = "within_2h"
    WITHIN_24H = "within_24h"
    WITHIN_7D = "within_7d"
    WITHIN_30D = "within_30d"
    OLDER_THAN_30D = "older_than_30d"
    UNKNOWN = "unknown"


class FinalOutcomeLabel(str, Enum):
    """V3: Labeled outcome after the move plays out."""
    CLEAN_PRE_NEWS_WINNER = "clean_pre_news_winner"
    NEWS_LAG_CONFIRMED_WINNER = "news_lag_confirmed_winner"
    OLD_NEWS_CONTINUATION = "old_news_continuation"
    FAILED_SPIKE = "failed_spike"
    DISTRIBUTION_TRAP = "distribution_trap"
    NO_FOLLOW_THROUGH = "no_follow_through"
    LATE_CHASE_SIGNAL = "late_chase_signal"
    UNRESOLVED = "unresolved"


class WyckoffStage(str, Enum):
    """V3: Wyckoff market-cycle stage interpretation."""
    ACCUMULATION_PHASE_C = "accumulation_phase_c"
    ACCUMULATION_PHASE_D = "accumulation_phase_d"
    MARKUP_PHASE_D = "markup_phase_d"
    MARKUP_PHASE_E = "markup_phase_e"
    BUYING_CLIMAX = "buying_climax"
    DISTRIBUTION = "distribution"
    EARLY_MARKDOWN = "early_markdown"
    UNKNOWN = "unknown"


class CandidateType(str, Enum):
    """V3.1: What kind of discovery path this anomaly came from."""
    QUIET_ACCUMULATION = "quiet_accumulation"
    EARLY_BREAKOUT = "early_breakout"
    LATE_CHASE = "late_chase"
    TRAP_RISK = "trap_risk"
    GENERAL = "general"


# ── Volume Metrics ────────────────────────────────────────────────────────────


class VolumeMetrics(BaseModel):
    """Computed volume statistics for anomaly scoring."""
    rvol_current: Optional[float] = None
    rvol_5min: Optional[float] = None
    rvol_15min: Optional[float] = None
    volume_acceleration: float = 0.0
    volume_z_score: float = 0.0
    abnormal_volume_score: float = Field(0.0, ge=0, le=100)
    avg_volume: Optional[float] = None
    current_volume: Optional[float] = None

    # V2 additions — non-breaking
    volume_acceleration_score: float = Field(0.0, ge=0, le=100, description="V2: acceleration normalized to 0-100")
    mtf_1m_rvol: Optional[float] = None
    mtf_5m_rvol: Optional[float] = None
    mtf_15m_rvol: Optional[float] = None
    mtf_alignment_score: float = Field(0.0, ge=0, le=100, description="V2: multi-timeframe RVOL alignment score")
    accel_trend: str = "stable"  # "accelerating" | "stable" | "decelerating"

    # V3 — time-of-day adjusted volume metrics
    time_of_day_rvol: Optional[float] = Field(None, description="V3: RVOL adjusted for time-of-day expected volume curve")
    intraday_volume_curve_deviation: Optional[float] = Field(None, description="V3: deviation from normal intraday volume curve (%)")
    current_5m_volume_zscore: Optional[float] = Field(None, description="V3: z-score of current 5m bar vs same historical 5m slot")
    session_progress_adjusted_volume_score: float = Field(0.0, ge=0, le=100, description="V3: volume score adjusted for how far into session we are")


# ── Price Behaviour Detail ────────────────────────────────────────────────────


class PriceBehaviourDetail(BaseModel):
    """Detailed price action classification supporting anomaly scoring."""
    behaviour: PriceBehaviour = PriceBehaviour.QUIET_ACCUMULATION
    price_change_pct: float = 0.0
    vwap_distance_pct: float = 0.0
    distance_from_hod_pct: float = 0.0
    distance_from_open_pct: float = 0.0
    upper_wick_pct: float = 0.0
    lower_wick_pct: float = 0.0
    range_tightening: bool = False
    score: float = Field(50.0, ge=0, le=100, description="Price quality score 0-100")

    # V3 — latest 5-candle quality summary
    latest_5candle_buying_pressure: float = Field(50.0, ge=0, le=100, description="V3: buying pressure in last 5 candles")
    latest_5candle_selling_pressure: float = Field(50.0, ge=0, le=100, description="V3: selling pressure in last 5 candles")
    latest_5candle_wick_dominance: str = "neutral"  # "upper" | "lower" | "neutral" | "mixed"
    latest_5candle_summary: str = ""  # e.g. "accumulation", "breakout", "rejection", "distribution", "failed_spike"

    # V3.1 — absorption quality score (VWAP hold + tight range + low rejection + demand absorption)
    absorption_quality_score: float = Field(50.0, ge=0, le=100, description="V3.1: composite absorption quality score")


# ── Core Anomaly Record ──────────────────────────────────────────────────────


class PreNewsAnomaly(BaseModel):
    """Single detected pre-news volume anomaly."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    ticker: str
    price: float = 0.0
    detected_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # Volume
    volume_metrics: VolumeMetrics = Field(default_factory=VolumeMetrics)
    volume_anomaly_score: float = Field(0.0, ge=0, le=100)

    # Price
    price_behaviour: PriceBehaviourDetail = Field(default_factory=PriceBehaviourDetail)

    # News
    news_status: NewsStatus = NewsStatus.UNKNOWN_NEWS_STATUS
    first_news_timestamp: Optional[datetime] = None
    first_news_headline: Optional[str] = None
    time_gap_minutes: Optional[float] = None
    news_confirmed_at: Optional[datetime] = None  # when news became confirmed

    # High-price tracking (reset buckets)
    high_price_pre_news: Optional[float] = None   # highest price seen before news confirmed
    high_price_post_news: Optional[float] = None  # highest price seen after news confirmed

    # V3 — catalyst visibility confidence
    catalyst_age_minutes: Optional[float] = None
    catalyst_age_bucket: CatalystAgeBucket = CatalystAgeBucket.UNKNOWN
    catalyst_relevance_score: float = Field(0.0, ge=0, le=100, description="V3: 0=irrelevant/old, 100=fresh direct catalyst")
    catalyst_source: str = ""  # e.g. "finviz_global", "finviz_ticker", "stocktitan"
    matched_headline: Optional[str] = None
    matched_headline_time: Optional[datetime] = None

    # V3 — Wyckoff + alert quality
    wyckoff_stage: WyckoffStage = WyckoffStage.UNKNOWN
    alert_quality: AlertQuality = AlertQuality.EARLY
    alert_suppression_reasons: list[str] = Field(default_factory=list)

    # V3.1 — candidate type + tape read
    candidate_type: CandidateType = CandidateType.GENERAL
    tape_read: str = ""  # one-sentence explanation of current tape structure

    # V3 — outcome tracking fields (populated after detection)
    detection_price: Optional[float] = None
    max_price_30m: Optional[float] = None
    max_price_1h: Optional[float] = None
    max_price_2h: Optional[float] = None
    max_price_same_day: Optional[float] = None
    drawdown_before_max_move: Optional[float] = None
    vwap_hold_after_detection: Optional[bool] = None
    first_vwap_loss_time: Optional[datetime] = None
    time_gap_detection_to_news: Optional[float] = None
    pre_news_high: Optional[float] = None
    post_news_high: Optional[float] = None
    final_outcome_label: FinalOutcomeLabel = FinalOutcomeLabel.UNRESOLVED

    # Classification / scoring
    anomaly_type: AnomalyType = AnomalyType.UNUSUAL_VOLUME_NO_NEWS
    pre_news_suspicion_score: float = Field(0.0, ge=0, le=100)
    classification: SuspicionLevel = SuspicionLevel.LOW
    state: PreNewsState = PreNewsState.PRE_NEWS_WATCH

    # Context
    next_condition_needed: str = ""
    risk_notes: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
    data_quality_state: DataQuality = DataQuality.FULL

    # Outcome tracking
    outcome_recorded: bool = False

    # Float / market cap (may be None)
    float_shares: Optional[float] = None
    market_cap: Optional[float] = None
    spread_quality: Optional[str] = None

    # StockTwits social signals
    stocktwits_trending: bool = False
    stocktwits_rank: Optional[int] = None
    stocktwits_watchers: Optional[int] = None
    stocktwits_message_volume: Optional[int] = None
    stocktwits_sentiment_bullish_pct: Optional[float] = None

    # Alert tracking
    alert_sent: bool = False
    alert_sent_at: Optional[datetime] = None
    last_alert_score: float = 0.0
    news_confirmed_alert_sent: bool = False
    news_confirmed_alert_at: Optional[datetime] = None

    # ── V2 ADDITIONS — Informed-Positioning Scoring ──────────────────────────
    # All default to neutral/safe values so existing persisted anomalies load cleanly.

    # Composite signals
    smart_money_score: float = Field(0.0, ge=0, le=100, description="V2: composite informed-positioning footprint")
    buy_pressure_score: float = Field(50.0, ge=0, le=100, description="V2: green vs red vol + uptick dominance")
    float_pressure_score: float = Field(50.0, ge=0, le=100, description="V2: volume normalized by float")
    offering_risk_score: float = Field(0.0, ge=0, le=100, description="V2: dilution / ATM / S-3 risk")
    session_quality_score: float = Field(50.0, ge=0, le=100, description="V2: liquidity / noise profile of current session")

    # Pattern memory (populated after 100 historical outcomes exist)
    winner_similarity_score: float = Field(50.0, ge=0, le=100, description="V2: similarity to historical winners")
    loser_similarity_score: float = Field(50.0, ge=0, le=100, description="V2: similarity to historical losers")

    # Timing + move-type classification
    timing_stage: TimingStage = TimingStage.EARLY
    late_detection_flag: bool = False
    move_type_prediction: MoveType = MoveType.UNKNOWN
    session: SessionQuality = SessionQuality.OPEN

    # Decay
    confidence_decay_factor: float = Field(1.0, ge=0, le=1.0, description="V2: 1.0=fresh, decays as signal ages without follow-through")

    # Pre-news discovery source tag (how this ticker entered the universe)
    discovery_source: str = "finviz_gainers"

    # ── V2 INTEGRATION — Agentic handoff ────────────────────────────────────
    agentic_candidate_id: Optional[str] = None  # set when converted to AgenticCandidate

    def to_summary(self) -> dict:
        return {
            "id": self.id,
            "ticker": self.ticker,
            "price": self.price,
            "rvol": self.volume_metrics.rvol_current,
            "volume_acceleration": round(self.volume_metrics.volume_acceleration, 2),
            "volume_anomaly_score": round(self.volume_anomaly_score, 1),
            "price_behaviour": self.price_behaviour.behaviour.value,
            "news_status": self.news_status.value,
            "first_news_headline": self.first_news_headline,
            "first_news_timestamp": (
                self.first_news_timestamp.isoformat() if self.first_news_timestamp else None
            ),
            "news_confirmed_at": (
                self.news_confirmed_at.isoformat() if self.news_confirmed_at else None
            ),
            "time_gap_minutes": self.time_gap_minutes,
            "high_price_pre_news": self.high_price_pre_news,
            "high_price_post_news": self.high_price_post_news,
            "suspicion_score": round(self.pre_news_suspicion_score, 1),
            "classification": self.classification.value,
            "state": self.state.value,
            "anomaly_type": self.anomaly_type.value,
            "next_condition_needed": self.next_condition_needed,
            "detected_at": self.detected_at.isoformat(),
            "data_quality": self.data_quality_state.value,
            "stocktwits_trending": self.stocktwits_trending,
            "stocktwits_rank": self.stocktwits_rank,
            "stocktwits_watchers": self.stocktwits_watchers,
            "stocktwits_message_volume": self.stocktwits_message_volume,
            "stocktwits_sentiment_bullish_pct": self.stocktwits_sentiment_bullish_pct,
            # V2 — informed-positioning fields
            "smart_money_score": round(self.smart_money_score, 1),
            "buy_pressure_score": round(self.buy_pressure_score, 1),
            "float_pressure_score": round(self.float_pressure_score, 1),
            "offering_risk_score": round(self.offering_risk_score, 1),
            "session_quality_score": round(self.session_quality_score, 1),
            "winner_similarity_score": round(self.winner_similarity_score, 1),
            "loser_similarity_score": round(self.loser_similarity_score, 1),
            "volume_acceleration_score": round(self.volume_metrics.volume_acceleration_score, 1),
            "mtf_alignment_score": round(self.volume_metrics.mtf_alignment_score, 1),
            "accel_trend": self.volume_metrics.accel_trend,
            "timing_stage": self.timing_stage.value,
            "late_detection_flag": self.late_detection_flag,
            "move_type_prediction": self.move_type_prediction.value,
            "session": self.session.value,
            "confidence_decay_factor": round(self.confidence_decay_factor, 3),
            "discovery_source": self.discovery_source,
            # V3 — time-of-day volume
            "time_of_day_rvol": self.volume_metrics.time_of_day_rvol,
            "intraday_volume_curve_deviation": self.volume_metrics.intraday_volume_curve_deviation,
            "current_5m_volume_zscore": self.volume_metrics.current_5m_volume_zscore,
            "session_progress_adjusted_volume_score": round(self.volume_metrics.session_progress_adjusted_volume_score, 1),
            # V3 — candle quality
            "latest_5candle_buying_pressure": round(self.price_behaviour.latest_5candle_buying_pressure, 1),
            "latest_5candle_selling_pressure": round(self.price_behaviour.latest_5candle_selling_pressure, 1),
            "latest_5candle_wick_dominance": self.price_behaviour.latest_5candle_wick_dominance,
            "latest_5candle_summary": self.price_behaviour.latest_5candle_summary,
            "absorption_quality_score": round(self.price_behaviour.absorption_quality_score, 1),
            # V3 — catalyst relevance
            "catalyst_age_minutes": self.catalyst_age_minutes,
            "catalyst_age_bucket": self.catalyst_age_bucket.value,
            "catalyst_relevance_score": round(self.catalyst_relevance_score, 1),
            "catalyst_source": self.catalyst_source,
            "matched_headline": self.matched_headline,
            "matched_headline_time": (
                self.matched_headline_time.isoformat() if self.matched_headline_time else None
            ),
            # V3 — Wyckoff + alert quality
            "wyckoff_stage": self.wyckoff_stage.value,
            "alert_quality": self.alert_quality.value,
            "alert_suppression_reasons": self.alert_suppression_reasons,
            # V3 — outcome tracking
            "detection_price": self.detection_price,
            "final_outcome_label": self.final_outcome_label.value,
            "vwap_distance_pct": round(self.price_behaviour.vwap_distance_pct, 2),
            # V3.1
            "candidate_type": self.candidate_type.value,
            "tape_read": self.tape_read,
        }


# ── Learning / Outcome ───────────────────────────────────────────────────────


class PreNewsOutcome(BaseModel):
    """Post-anomaly outcome for learning."""
    anomaly_id: str
    ticker: str
    anomaly_type: AnomalyType = AnomalyType.UNUSUAL_VOLUME_NO_NEWS
    suspicion_score: float = 0.0
    price_behaviour: PriceBehaviour = PriceBehaviour.QUIET_ACCUMULATION
    news_status: NewsStatus = NewsStatus.UNKNOWN_NEWS_STATUS

    # Did news actually appear?
    news_appeared: bool = False
    news_appeared_minutes_after: Optional[float] = None

    # Price outcomes
    entry_price: Optional[float] = None
    peak_price: Optional[float] = None
    exit_price: Optional[float] = None
    max_favorable_excursion_pct: Optional[float] = None
    max_adverse_excursion_pct: Optional[float] = None

    # Classification
    was_real_move: bool = False
    was_pump: bool = False
    was_false_alarm: bool = False

    # V2 outcome tracking — non-breaking (all optional / defaulted)
    time_to_peak_minutes: Optional[float] = None
    move_type_actual: MoveType = MoveType.UNKNOWN
    news_type_classification: Optional[str] = None  # e.g. "earnings", "fda", "contract", "sec_filing"
    failure_or_continuation: Optional[str] = None   # "failure" | "continuation" | "neutral"

    # Feature snapshot at detection time (used by pattern memory)
    smart_money_score_at_detection: Optional[float] = None
    buy_pressure_score_at_detection: Optional[float] = None
    float_pressure_score_at_detection: Optional[float] = None
    timing_stage_at_detection: Optional[TimingStage] = None
    rvol_at_detection: Optional[float] = None
    float_shares_at_detection: Optional[float] = None
    session_at_detection: Optional[SessionQuality] = None

    recorded_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class PreNewsMissedReview(BaseModel):
    """EOD review: did we catch the big mover or miss it?"""
    ticker: str
    change_pct: float = 0.0
    rvol: Optional[float] = None
    classification: MissedAnomalyClass = MissedAnomalyClass.CORRECTLY_IGNORED
    flagged_by_detector: bool = False
    flag_lead_time_minutes: Optional[float] = None
    reason: str = ""
    reviewed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class PreNewsDetectionSnapshot(BaseModel):
    """V3 Evaluation: immutable snapshot of what the detector knew at detection time."""

    # Core identity
    ticker: str
    detection_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    detection_time: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    session_date: str = ""
    detection_source: str = ""
    discovery_bucket: str = ""

    # Price at detection
    detection_price: float = 0.0
    open_price: Optional[float] = None
    previous_close: Optional[float] = None
    day_high_at_detection: Optional[float] = None
    day_low_at_detection: Optional[float] = None
    vwap_at_detection: Optional[float] = None
    vwap_distance: float = 0.0
    price_change_pct: float = 0.0
    price_change_from_open_pct: float = 0.0

    # Volume at detection
    current_volume: Optional[float] = None
    average_volume: Optional[float] = None
    relative_volume: Optional[float] = None
    time_of_day_rvol: Optional[float] = None
    intraday_volume_curve_deviation: Optional[float] = None
    current_5m_volume_zscore: Optional[float] = None
    session_progress_adjusted_volume_score: float = 0.0
    volume_acceleration_score: float = 0.0
    abnormal_volume_score: float = 0.0
    float_rotation: Optional[float] = None
    float_pressure: float = 0.0

    # Classification
    pre_news_suspicion_score: float = 0.0
    anomaly_type: str = ""
    price_behaviour: str = ""
    wyckoff_stage: str = ""
    alert_quality: str = ""
    candidate_type: str = ""
    quiet_accumulation_candidate: bool = False
    early_breakout_candidate: bool = False

    # 5-candle tape read
    latest_5candle_summary: str = ""
    buying_pressure: float = 0.0
    selling_pressure: float = 0.0
    wick_dominance: str = ""
    upper_wick_pct: float = 0.0
    lower_wick_pct: float = 0.0
    absorption_quality_score: float = 0.0
    absorption_score: float = 0.0
    supply_rejection_score: float = 0.0
    vwap_hold_count: int = 0
    vwap_loss_count: int = 0

    # News / catalyst
    news_status: str = ""
    catalyst_age_bucket: str = ""
    catalyst_relevance_score: float = 0.0
    catalyst_source: str = ""
    matched_headline: Optional[str] = None
    matched_headline_time: Optional[datetime] = None
    catalyst_age_minutes: Optional[float] = None

    # Risk
    offering_risk_score: float = 0.0
    dilution_risk_tag: str = ""
    market_cap: Optional[float] = None
    float_shares: Optional[float] = None
    liquidity_score: Optional[float] = None
    data_quality_score: float = 0.0
    suppression_reasons: list[str] = Field(default_factory=list)
    was_alert_suppressed: bool = False
    alert_sent: bool = False

    # Forward tracking (updated after detection)
    max_price_30m: Optional[float] = None
    max_price_1h: Optional[float] = None
    max_price_2h: Optional[float] = None
    max_price_same_day: Optional[float] = None
    min_price_after_detection: Optional[float] = None
    drawdown_before_max_move: Optional[float] = None
    drawdown_before_max_move_pct: Optional[float] = None
    first_vwap_loss_time: Optional[datetime] = None
    vwap_hold_after_detection: Optional[bool] = None
    time_gap_detection_to_news: Optional[float] = None
    pre_news_high: Optional[float] = None
    post_news_high: Optional[float] = None
    final_outcome_label: str = "unresolved"
    outcome_notes: list[str] = Field(default_factory=list)

    # Computed outcome fields
    max_move_30m_pct: Optional[float] = None
    max_move_1h_pct: Optional[float] = None
    max_move_2h_pct: Optional[float] = None
    max_move_same_day_pct: Optional[float] = None
    lowest_price_before_max: Optional[float] = None
    efficiency_ratio: Optional[float] = None
    vwap_closes_below_count: int = 0
    vwap_reclaimed: bool = False
    clean_or_choppy: str = ""

    recorded_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def model_dump(self, **kwargs):
        # Override to handle datetime serialization cleanly
        data = super().model_dump(**kwargs)
        for key in list(data.keys()):
            if isinstance(data[key], datetime):
                data[key] = data[key].isoformat()
        return data
