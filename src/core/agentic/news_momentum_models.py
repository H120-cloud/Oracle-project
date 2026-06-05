"""
News Momentum Intelligence System — Data Models (V22)

All data types for the full-market news momentum engine:
- catalyst classification
- news impact scoring
- price/volume reaction tracking
- expected return ML ranking
- continuation probability
- multi-day continuation
- adaptive Telegram learning
- alert outcomes
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional, Dict, List, Any
from pydantic import BaseModel, ConfigDict, Field, field_validator


def _aware_utc_datetime(value):
    if value is None:
        return value
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    return value


def _whole_number_int(value):
    if value is None:
        return value
    if isinstance(value, bool):
        return value
    try:
        number = float(value)
    except (TypeError, ValueError):
        return value
    if number.is_integer():
        return int(number)
    return value


# ── Enums ────────────────────────────────────────────────────────────────────


class CatalystCategory(str, Enum):
    BIOTECH = "biotech"
    AI_TECH = "ai_tech"
    FINANCIAL = "financial"
    CRYPTO = "crypto"
    CORPORATE = "corporate"
    NEGATIVE = "negative"
    UNKNOWN = "unknown"


class CatalystSubType(str, Enum):
    FDA_APPROVAL = "fda_approval"
    FDA_CLEARANCE = "fda_clearance"
    PHASE_1 = "phase_1"
    PHASE_2 = "phase_2"
    PHASE_3 = "phase_3"
    FAST_TRACK = "fast_track"
    BREAKTHROUGH_THERAPY = "breakthrough_therapy"
    ORPHAN_DRUG = "orphan_drug"
    PDUFA = "pdufa"
    TOPLINE_DATA = "topline_data"
    AI_PARTNERSHIP = "ai_partnership"
    NVIDIA_PARTNERSHIP = "nvidia_partnership"
    OPENAI_PARTNERSHIP = "openai_partnership"
    HYPERSCALER_CONTRACT = "hyperscaler_contract"
    INFRASTRUCTURE_AGREEMENT = "infrastructure_agreement"
    EARNINGS_BEAT = "earnings_beat"
    GUIDANCE_RAISE = "guidance_raise"
    PROFITABILITY_INFLECTION = "profitability_inflection"
    DEBT_RESTRUCTURING = "debt_restructuring"
    INSIDER_BUYING = "insider_buying"
    BITCOIN_TREASURY = "bitcoin_treasury"
    CRYPTO_MINING = "crypto_mining"
    BLOCKCHAIN_PARTNERSHIP = "blockchain_partnership"
    MERGER = "merger"
    ACQUISITION = "acquisition"
    BUYOUT = "buyout"
    STRATEGIC_REVIEW = "strategic_review"
    LICENSING_AGREEMENT = "licensing_agreement"
    PATENT_APPROVAL = "patent_approval"
    GOVERNMENT_CONTRACT = "government_contract"
    MAJOR_PARTNERSHIP = "major_partnership"
    SUPPLY_AGREEMENT = "supply_agreement"
    OEM_PARTNERSHIP = "oem_partnership"
    SHARE_BUYBACK = "share_buyback"
    OFFERING = "offering"
    ATM_FILING = "atm_filing"
    WARRANT_EXERCISE = "warrant_exercise"
    REVERSE_SPLIT = "reverse_split"
    DELISTING_NOTICE = "delisting_notice"
    TOXIC_FINANCING = "toxic_financing"
    VAGUE_PR = "vague_pr"
    OTHER = "other"

    # ── Biotech additions ─────────────────────────────────────────────────────
    SNDA_SUBMISSION = "snda_submission"
    NDA_APPROVAL = "nda_approval"
    LABEL_EXPANSION = "label_expansion"
    DRUG_LAUNCH = "drug_launch"
    COMMERCIALIZATION = "commercialization"
    CLINICAL_HOLD = "clinical_hold"
    TRIAL_FAILURE = "trial_failure"
    SAFETY_SIGNAL = "safety_signal"
    ADVERSE_EVENT = "adverse_event"

    # ── Tech / product ───────────────────────────────────────────────────────
    NEW_PRODUCT_LAUNCH = "new_product_launch"
    PRODUCT_UPGRADE = "product_upgrade"
    PLATFORM_EXPANSION = "platform_expansion"
    NEW_MARKET_ENTRY = "new_market_entry"

    # ── Corporate additions ──────────────────────────────────────────────────
    SPIN_OFF = "spin_off"
    JOINT_VENTURE = "joint_venture"
    MANAGEMENT_CHANGE_POSITIVE = "management_change_positive"
    ANALYST_UPGRADE = "analyst_upgrade"
    INVESTIGATION = "investigation"
    ACCOUNTING_IRREGULARITIES = "accounting_irregularities"
    MARGIN_PRESSURE = "margin_pressure"
    GUIDANCE_CUT = "guidance_cut"
    EARNINGS_MISS = "earnings_miss"
    DIVIDEND_CUT = "dividend_cut"
    ANALYST_DOWNGRADE = "analyst_downgrade"
    SHORT_SELLER_REPORT = "short_seller_report"

    # ── Financial additions ──────────────────────────────────────────────────
    DIVIDEND_INCREASE = "dividend_increase"
    STOCK_SPLIT_FORWARD = "stock_split_forward"
    CREDIT_UPGRADE = "credit_upgrade"
    FINANCING_POSITIVE = "financing_positive"
    DEBT_DOWNGRADE = "debt_downgrade"

    # ── Energy / EV / Green ──────────────────────────────────────────────────
    EV_BATTERY = "ev_battery"
    RENEWABLE_ENERGY = "renewable_energy"
    CARBON_CREDIT = "carbon_credit"

    # ── Macro / policy ───────────────────────────────────────────────────────
    TARIFF_EXEMPTION = "tariff_exemption"
    TRADE_DEAL = "trade_deal"
    SUBSIDY_AWARD = "subsidy_award"

    # ── Overhang removal / compliance ──────────────────────────────────────
    WARRANT_OVERHANG_REMOVAL = "warrant_overhang_removal"
    LISTING_COMPLIANCE = "listing_compliance"


class SessionType(str, Enum):
    PREMARKET = "premarket"
    REGULAR = "regular"
    AFTER_HOURS = "after_hours"


class PriceBucket(str, Enum):
    SUB_PENNY = "sub_penny"
    UNDER_1 = "under_1"
    UNDER_5 = "under_5"
    UNDER_10 = "under_10"
    MID_CAP = "mid_cap"


class MarketCapCategory(str, Enum):
    NANO = "nano"
    MICRO = "micro"
    SMALL = "small"
    ALL = "all"


class FloatCategory(str, Enum):
    ULTRA_LOW = "ultra_low"      # <5M
    LOW = "low"                  # 5-20M
    MEDIUM = "medium"            # 20-100M
    HIGH = "high"                # >100M


class OracleAction(str, Enum):
    WATCH = "WATCH"
    WAIT_FOR_RETEST = "WAIT_FOR_RETEST"
    TRADEABLE = "TRADEABLE"
    AVOID_CHASE = "AVOID_CHASE"
    AVOID_TRAP = "AVOID_TRAP"
    SWING_WATCH = "SWING_WATCH"


class MultiDayClass(str, Enum):
    ONE_DAY_SPIKE_ONLY = "ONE_DAY_SPIKE_ONLY"
    POSSIBLE_CONTINUATION = "POSSIBLE_CONTINUATION"
    STRONG_MULTI_DAY_CANDIDATE = "STRONG_MULTI_DAY_CANDIDATE"
    SWING_RUNNER = "SWING_RUNNER"
    LIKELY_FADE = "LIKELY_FADE"
    EXHAUSTED = "EXHAUSTED"


class AlertOutcome(str, Enum):
    GREAT_ALERT = "GREAT_ALERT"
    GOOD_ALERT = "GOOD_ALERT"
    LATE_ALERT = "LATE_ALERT"
    TRAP_ALERT = "TRAP_ALERT"
    NO_FOLLOW_THROUGH = "NO_FOLLOW_THROUGH"
    MISSED_RUNNER = "MISSED_RUNNER"


class NewsSource(str, Enum):
    STOCKTITAN = "stocktitan"
    FINVIZ = "finviz"
    ALPACA = "alpaca"  # Real-time Alpaca news WebSocket (Benzinga-sourced)
    NASDAQ = "nasdaq"
    SEC = "sec"
    GLOBE_NEWSWIRE = "globenewswire"
    BUSINESS_WIRE = "businesswire"
    PR_NEWSWIRE = "prnewswire"
    SHARECAST = "sharecast"
    ACCESSWIRE = "accesswire"
    NEWSFILE = "newsfile"
    COMPANY_PRESS = "company_press"
    ORACLE_SCANNER = "oracle_scanner"


# ── Core Models ──────────────────────────────────────────────────────────────


class NewsVelocity(BaseModel):
    """Cross-source news velocity tracking."""
    first_detected_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    sources_seen: List[NewsSource] = Field(default_factory=list)
    velocity_ms: float = 0.0  # time between first and last source in milliseconds
    source_count: int = 0
    confidence_boost: float = 0.0  # 0-20 bonus based on how fast news spread

    @field_validator("first_detected_at")
    @classmethod
    def _normalize_first_detected_at(cls, value):
        return _aware_utc_datetime(value)

    @field_validator("source_count", mode="before")
    @classmethod
    def _normalize_int_fields(cls, value):
        return _whole_number_int(value)


class NewsEvent(BaseModel):
    """A detected news headline with metadata."""
    ticker: str
    headline: str
    source: NewsSource
    source_url: Optional[str] = None
    raw_text: str = ""
    published_at: datetime
    timestamp_confidence: str = "HIGH"
    detected_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    fetched_at: Optional[datetime] = None
    parsed_at: Optional[datetime] = None
    classified_at: Optional[datetime] = None
    catalyst_category: CatalystCategory = CatalystCategory.UNKNOWN
    catalyst_sub_type: CatalystSubType = CatalystSubType.OTHER
    is_negative: bool = False
    is_vague: bool = False
    # Cross-source velocity
    velocity: NewsVelocity = Field(default_factory=NewsVelocity)
    duplicate_of_id: Optional[str] = None  # If this is a duplicate of an earlier event

    @field_validator("published_at", "detected_at", "fetched_at", "parsed_at", "classified_at")
    @classmethod
    def _normalize_datetimes(cls, value):
        return _aware_utc_datetime(value)


class PriceSnapshot(BaseModel):
    """Price/volume snapshot at a point in time."""
    timestamp: datetime
    price: float
    volume: int
    bid: Optional[float] = None
    ask: Optional[float] = None
    vwap: Optional[float] = None

    @field_validator("timestamp")
    @classmethod
    def _normalize_timestamp(cls, value):
        return _aware_utc_datetime(value)

    @field_validator("volume", mode="before")
    @classmethod
    def _normalize_volume(cls, value):
        return _whole_number_int(value)


class NewsReactionMetrics(BaseModel):
    """Price and volume reaction to a news event."""
    price_before_news: Optional[float] = None
    price_after_news: Optional[float] = None
    price_current: Optional[float] = None
    move_pct: float = 0.0
    volume_before: Optional[int] = None
    volume_after: Optional[int] = None
    rvol: Optional[float] = None
    spread_pct: Optional[float] = None
    vwap_distance_pct: Optional[float] = None
    halt_count: int = 0
    upper_wick_pct: Optional[float] = None
    lower_wick_pct: Optional[float] = None
    holding_vwap: bool = False
    higher_lows: bool = False
    consolidation_quality: Optional[float] = None   # 0-100
    breakout_quality: Optional[float] = None        # 0-100

    @field_validator("volume_before", "volume_after", "halt_count", mode="before")
    @classmethod
    def _normalize_int_fields(cls, value):
        return _whole_number_int(value)


class NewsImpactScore(BaseModel):
    """Comprehensive news impact assessment."""
    catalyst_materiality: float = 0.0       # 0-100
    surprise_factor: float = 0.0            # 0-100
    float_sensitivity: float = 0.0        # 0-100
    market_cap_sensitivity: float = 0.0   # 0-100
    sector_hype_multiplier: float = 1.0
    short_squeeze_potential: float = 0.0   # 0-100
    volume_expansion: float = 0.0           # 0-100
    spread_quality: float = 0.0             # 0-100
    vwap_behavior: float = 0.0              # 0-100
    pre_news_accumulation: float = 0.0      # 0-100
    dilution_risk: float = 0.0              # 0-100
    trap_risk: float = 0.0                  # 0-100
    price_extension_risk: float = 0.0         # 0-100
    composite_score: float = 0.0            # 0-100 final


class NewsReactionScore(BaseModel):
    """Score of how the market reacted to the news."""
    price_reaction_strength: float = 0.0    # 0-100
    volume_reaction_strength: float = 0.0   # 0-100
    rvol_score: float = 0.0                 # 0-100
    spread_score: float = 0.0               # 0-100
    vwap_behavior_score: float = 0.0        # 0-100
    continuation_quality: float = 0.0       # 0-100
    halt_impact: float = 0.0                # 0-100
    composite_score: float = 0.0            # 0-100 final


class ExpectedReturnMLScore(BaseModel):
    """ML-predicted expected return ranking."""
    model_config = ConfigDict(protected_namespaces=())

    score: float = 0.0                      # 0-100
    confidence: float = 0.0                   # 0-100
    model_version: str = "v1"
    feature_vector: Dict[str, float] = Field(default_factory=dict)
    top_features: List[str] = Field(default_factory=list)


class ContinuationProbability(BaseModel):
    """Probability estimates for continuation."""
    same_day_continuation: float = 0.0        # 0-100
    second_leg_probability: float = 0.0       # 0-100
    continuation_tomorrow: float = 0.0         # 0-100
    gap_up_next_session: float = 0.0           # 0-100
    fade_probability: float = 0.0              # 0-100


class MultiDayContinuation(BaseModel):
    """Multi-day continuation prediction."""
    multi_day_score: float = 0.0               # 0-100
    next_day_continuation_probability: float = 0.0
    two_day_continuation_probability: float = 0.0
    five_day_continuation_probability: float = 0.0
    next_day_gap_up_probability: float = 0.0
    multi_day_fade_probability: float = 0.0
    exhaustion_probability: float = 0.0
    swing_trade_quality_score: float = 0.0
    classification: MultiDayClass = MultiDayClass.ONE_DAY_SPIKE_ONLY


class EstimatedMoveRange(BaseModel):
    """AI-estimated price move ranges."""
    conservative_pct: float = 0.0
    bullish_pct: float = 0.0
    extreme_pct: float = 0.0
    conservative_target: Optional[float] = None
    bullish_target: Optional[float] = None
    extreme_target: Optional[float] = None


class TrapAssessment(BaseModel):
    """Trap risk assessment."""
    parabolic_exhaustion: float = 0.0
    bull_trap_risk: float = 0.0
    fake_breakout_risk: float = 0.0
    vwap_failure_risk: float = 0.0
    distribution_risk: float = 0.0
    composite_trap_risk: float = 0.0


class BullBearCase(BaseModel):
    """Bull and bear case summaries."""
    bull_case: str = ""
    bear_case: str = ""
    why_it_matters: str = ""


class TelegramAlertRecord(BaseModel):
    """Record of a sent Telegram alert for outcome tracking and ML training."""
    alert_id: str
    ticker: str
    sent_at: datetime
    headline: Optional[str] = None
    source: Optional[str] = None
    published_at: Optional[datetime] = None
    catalyst_type: CatalystSubType
    session_type: SessionType
    price_at_alert: float
    news_impact_score: float
    expected_return_score: float
    continuation_probability: float
    multi_day_score: float

    # Extended features captured at alert time (for ML training)
    catalyst_category: Optional[str] = None
    float_category: Optional[str] = None
    market_cap_category: Optional[str] = None
    move_pct_at_alert: Optional[float] = None
    rvol_at_alert: Optional[float] = None
    volume_at_alert: Optional[int] = None
    spread_pct_at_alert: Optional[float] = None
    trap_risk_at_alert: Optional[float] = None
    dilution_risk_at_alert: Optional[float] = None
    velocity_score_at_alert: Optional[float] = None
    sources_seen_count: Optional[int] = None
    is_negative: Optional[bool] = None
    is_vague: Optional[bool] = None
    is_delayed_reaction: Optional[bool] = None
    prenews_anomaly_score: Optional[float] = None  # Bridge from pre-news system
    ml_predicted_win_prob: Optional[float] = None  # What the ML predicted before send
    ml_model_version: Optional[str] = None

    # SEC structural features (captured at alert time for the learning loop)
    sec_dilution_probability: Optional[float] = None
    sec_toxic_financing_score: Optional[float] = None
    sec_warrant_overhang_score: Optional[float] = None
    sec_cash_runway_score: Optional[float] = None
    sec_survival_risk_score: Optional[float] = None
    sec_balance_sheet_quality_score: Optional[float] = None
    sec_offering_risk_score: Optional[float] = None
    sec_reverse_split_risk_score: Optional[float] = None
    sec_structural_trap_risk_score: Optional[float] = None
    sec_historical_dilution_behavior_score: Optional[float] = None
    sec_dilution_behavior: Optional[str] = None
    sec_oracle_action: Optional[str] = None
    sec_atm_active: Optional[bool] = None
    sec_going_concern_active: Optional[bool] = None

    # Outcomes (filled in later by resolver)
    price_15m_later: Optional[float] = None
    price_1h_later: Optional[float] = None
    price_4h_later: Optional[float] = None
    next_day_open: Optional[float] = None
    next_day_high: Optional[float] = None
    next_day_close: Optional[float] = None
    two_day_high: Optional[float] = None
    five_day_high: Optional[float] = None
    mfe_pct: Optional[float] = None
    mae_pct: Optional[float] = None
    # Forward returns at multiple horizons. Computed by the outcome resolver
    # whenever it sets the corresponding price_* field. Stored explicitly so
    # the ML retrain pipeline can label trades by MAGNITUDE (e.g. +200% at
    # 1d) rather than the binary win/loss it currently uses. This is what
    # separates "system that catches winners" from "system that catches
    # rockets" — the strength of the signal matters.
    return_15m_pct: Optional[float] = None
    return_1h_pct: Optional[float] = None
    return_4h_pct: Optional[float] = None
    return_next_day_close_pct: Optional[float] = None
    return_next_day_high_pct: Optional[float] = None  # captures intraday peak
    return_two_day_high_pct: Optional[float] = None
    return_five_day_high_pct: Optional[float] = None
    outcome: Optional[AlertOutcome] = None
    user_watched: bool = False
    user_entered: bool = False
    user_ignored: bool = False
    user_marked_useful: bool = False
    user_marked_poor: bool = False
    resolved_at: Optional[datetime] = None

    @field_validator("sent_at", "published_at", "resolved_at")
    @classmethod
    def _normalize_datetimes(cls, value):
        return _aware_utc_datetime(value)

    # Shadow-logging fields: when True, this record was NOT actually sent to
    # Telegram (it was blocked by the gate). Captured anyway for ML training
    # so the model can learn from "what would have happened" outcomes too.
    was_blocked: bool = False
    block_reason: Optional[str] = None

    @field_validator("volume_at_alert", "sources_seen_count", mode="before")
    @classmethod
    def _normalize_int_fields(cls, value):
        return _whole_number_int(value)


class TelegramAlertQuality(BaseModel):
    """Aggregate quality metrics for Telegram alerts."""
    total_alerts: int = 0
    great_alerts: int = 0
    good_alerts: int = 0
    late_alerts: int = 0
    trap_alerts: int = 0
    no_follow_through: int = 0
    missed_runners: int = 0
    avg_mfe_pct: Optional[float] = None
    avg_mae_pct: Optional[float] = None
    quality_score: float = 0.0  # 0-100
    by_catalyst_type: Dict[str, Dict[str, Any]] = Field(default_factory=dict)

    @field_validator(
        "total_alerts",
        "great_alerts",
        "good_alerts",
        "late_alerts",
        "trap_alerts",
        "no_follow_through",
        "missed_runners",
        mode="before",
    )
    @classmethod
    def _normalize_int_fields(cls, value):
        return _whole_number_int(value)


class CatalystLearningStats(BaseModel):
    """Learning statistics for a catalyst type."""
    catalyst_type: str
    total_occurrences: int = 0
    continuation_rate: Optional[float] = None
    avg_mfe_pct: Optional[float] = None
    fade_rate: Optional[float] = None
    trap_rate: Optional[float] = None
    avg_move_pct: Optional[float] = None
    best_time_of_day: Optional[str] = None
    best_session: Optional[str] = None
    telegram_alert_quality: Optional[float] = None

    @field_validator("total_occurrences", mode="before")
    @classmethod
    def _normalize_total_occurrences(cls, value):
        return _whole_number_int(value)


# ── Main Candidate Model ───────────────────────────────────────────────────


class NewsMomentumCandidate(BaseModel):
    """Full news momentum candidate with all AI scores."""
    id: str = Field(default_factory=lambda: str(datetime.now(timezone.utc).timestamp()))
    ticker: str
    headline: str
    source: NewsSource
    source_url: Optional[str] = None
    raw_text: str = ""
    published_at: datetime
    detected_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    session: SessionType
    catalyst_category: CatalystCategory
    catalyst_sub_type: CatalystSubType
    is_negative: bool = False
    is_vague: bool = False

    # Price / Market Data
    prior_price: Optional[float] = None
    current_price: Optional[float] = None
    move_pct: float = 0.0
    volume: Optional[int] = None
    rvol: Optional[float] = None
    float_shares: Optional[float] = None
    market_cap: Optional[float] = None
    price_bucket: PriceBucket = PriceBucket.UNDER_5
    float_category: FloatCategory = FloatCategory.LOW
    market_cap_category: MarketCapCategory = MarketCapCategory.MICRO
    short_interest: Optional[float] = None
    spread_pct: Optional[float] = None
    price_status: str = "unknown"

    # Scores
    news_impact_score: float = 0.0
    news_reaction_score: float = 0.0
    expected_return_score: float = 0.0
    continuation_probability: float = 0.0
    multi_day_continuation_score: float = 0.0
    next_day_continuation_probability: float = 0.0
    two_day_continuation_probability: float = 0.0
    five_day_continuation_probability: float = 0.0
    next_day_gap_up_probability: float = 0.0
    swing_trade_quality_score: float = 0.0
    exhaustion_probability: float = 0.0
    telegram_alert_quality_score: float = 0.0
    trap_risk: float = 0.0
    dilution_risk: float = 0.0

    # Derived
    estimated_move: EstimatedMoveRange = Field(default_factory=EstimatedMoveRange)
    oracle_action: OracleAction = OracleAction.WATCH
    multi_day_class: MultiDayClass = MultiDayClass.ONE_DAY_SPIKE_ONLY
    bull_bear: BullBearCase = Field(default_factory=BullBearCase)
    adaptive_reason: str = ""
    rank: int = 0

    # Cross-source velocity
    velocity_score: float = 0.0  # 0-20 bonus from fast multi-source coverage
    sources_seen_count: int = 1
    first_detected_at: Optional[datetime] = None
    fetched_at: Optional[datetime] = None
    parsed_at: Optional[datetime] = None
    candidate_created_at: Optional[datetime] = None
    classified_at: Optional[datetime] = None
    scored_at: Optional[datetime] = None
    gate_decision_at: Optional[datetime] = None
    telegram_enqueue_at: Optional[datetime] = None
    telegram_sent_at: Optional[datetime] = None
    published_age_seconds: Optional[float] = None
    detected_age_seconds: Optional[float] = None
    freshness_confidence: str = "UNKNOWN"
    timestamp_confidence: str = "HIGH"

    # News-to-price lag detection
    first_volume_reaction_at: Optional[datetime] = None  # When price/volume actually moved
    news_to_price_lag_seconds: Optional[float] = None
    is_delayed_reaction: bool = False  # True if move happened > 5 min after news
    aggressive_refresh_until: Optional[datetime] = None  # Refresh every 15s instead of 45s

    # Duplicate suppression
    is_duplicate: bool = False
    primary_event_id: Optional[str] = None

    # State
    is_active: bool = True
    telegram_sent: bool = False
    fast_path_watch_sent: bool = False
    fast_path_watch_sent_at: Optional[datetime] = None
    telegram_alert_id: Optional[str] = None
    resolved: bool = False
    resolution_price: Optional[float] = None
    resolution_time: Optional[datetime] = None
    last_refresh: Optional[datetime] = None  # Persisted to avoid immediate re-fetch after restart

    @field_validator(
        "published_at",
        "detected_at",
        "first_detected_at",
        "fetched_at",
        "parsed_at",
        "candidate_created_at",
        "classified_at",
        "scored_at",
        "gate_decision_at",
        "telegram_enqueue_at",
        "telegram_sent_at",
        "fast_path_watch_sent_at",
        "first_volume_reaction_at",
        "aggressive_refresh_until",
        "resolution_time",
        "last_refresh",
    )
    @classmethod
    def _normalize_datetimes(cls, value):
        return _aware_utc_datetime(value)

    @field_validator("volume", "rank", "sources_seen_count", mode="before")
    @classmethod
    def _normalize_int_fields(cls, value):
        return _whole_number_int(value)


class MissedWinnerReason(str, Enum):
    """Why Oracle missed a positive catalyst."""
    NEWS_IMPACT_TOO_LOW = "news_impact_too_low"
    EXPECTED_RETURN_TOO_LOW = "expected_return_too_low"
    CONTINUATION_TOO_LOW = "continuation_too_low"
    MULTI_DAY_TOO_LOW = "multi_day_too_low"
    TRAP_RISK_TOO_HIGH = "trap_risk_too_high"
    DILUTION_RISK_BLOCKED = "dilution_risk_blocked"
    PRICE_FILTER_EXCLUDED = "price_filter_excluded"
    NEGATIVE_CLASSIFIED = "negative_classified"
    VAGUE_CLASSIFIED = "vague_classified"
    COOLDOWN_ACTIVE = "cooldown_active"
    SOURCE_DETECTED_LATE = "source_detected_late"
    HEADLINE_MISCLASSIFIED = "headline_misclassified"
    CATALYST_TYPE_WRONG = "catalyst_type_wrong"
    VOLUME_CONFIRMATION_MISSED = "volume_confirmation_missed"
    PREMARKET_MOVE_MISSED = "premarket_move_missed"
    TELEGRAM_DISABLED = "telegram_disabled"
    UNKNOWN = "unknown"


class MissedWinnerRecord(BaseModel):
    """Record of a missed positive catalyst that became a winner."""
    id: str = ""
    ticker: str
    headline: str
    catalyst_category: CatalystCategory
    catalyst_sub_type: CatalystSubType
    source: NewsSource
    news_time: datetime
    detected_time: Optional[datetime] = None
    alert_time: Optional[datetime] = None  # If alert was late
    price_at_news: Optional[float] = None
    price_at_alert_scan: Optional[float] = None
    max_price_after_news: Optional[float] = None
    price_1h: Optional[float] = None
    price_same_day: Optional[float] = None
    price_2day: Optional[float] = None
    price_5day: Optional[float] = None
    move_1h_pct: Optional[float] = None
    move_same_day_pct: Optional[float] = None
    move_2day_pct: Optional[float] = None
    move_5day_pct: Optional[float] = None
    missed: bool = True
    missed_reasons: List[MissedWinnerReason] = Field(default_factory=list)
    missed_reason: str = ""  # Primary reason string
    blocking_rule: str = ""
    score_gap: float = 0.0  # How far below threshold
    news_impact_score: float = 0.0
    expected_return_score: float = 0.0
    continuation_probability: float = 0.0
    multi_day_score: float = 0.0
    trap_risk: float = 0.0
    dilution_risk: float = 0.0
    oracle_action: OracleAction = OracleAction.WATCH
    alert_sent_late: bool = False
    late_by_minutes: Optional[float] = None
    recommendation: str = ""
    shadow_adjustment_applied: bool = False
    similar_historical_winners: int = 0
    status: str = "pending"  # pending, approved, rejected, shadow_applied
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    resolved_at: Optional[datetime] = None

    @field_validator("similar_historical_winners", mode="before")
    @classmethod
    def _normalize_int_fields(cls, value):
        return _whole_number_int(value)


class MissedWinnerLearningReport(BaseModel):
    """Summary report of missed winner learning."""
    total_missed: int = 0
    total_detected: int = 0
    by_reason: Dict[str, int] = Field(default_factory=dict)
    by_catalyst: Dict[str, int] = Field(default_factory=dict)
    avg_move_missed: float = 0.0
    avg_move_alerted: float = 0.0
    recommendations_pending: int = 0
    recommendations_applied: int = 0
    shadow_adjustments_active: int = 0
    top_missed_movers: List[Dict] = Field(default_factory=list)
    recent_missed: List[MissedWinnerRecord] = Field(default_factory=list)

    @field_validator(
        "total_missed",
        "total_detected",
        "recommendations_pending",
        "recommendations_applied",
        "shadow_adjustments_active",
        mode="before",
    )
    @classmethod
    def _normalize_int_fields(cls, value):
        return _whole_number_int(value)


class NewsMomentumConfig(BaseModel):
    """Configuration for the news momentum system."""
    enabled: bool = True
    min_price: float = 0.20
    max_price: float = 50.00   # rockets often run past $10; don't block winners
    market_cap_filter: MarketCapCategory = MarketCapCategory.MICRO
    float_filter: FloatCategory = FloatCategory.LOW
    price_buckets: List[PriceBucket] = Field(default_factory=lambda: [PriceBucket.UNDER_5])

    # Score thresholds (default / regular hours)
    news_impact_threshold: float = 70.0
    expected_return_threshold: float = 75.0
    continuation_threshold: float = 70.0
    multi_day_threshold: float = 70.0

    # Session-based thresholds (premarket = lower, midday = higher)
    premarket_impact_threshold: float = 60.0
    premarket_expected_return_threshold: float = 65.0
    premarket_continuation_threshold: float = 55.0
    open_impact_threshold: float = 55.0
    open_expected_return_threshold: float = 60.0
    open_continuation_threshold: float = 50.0
    midday_impact_threshold: float = 75.0
    midday_expected_return_threshold: float = 80.0
    midday_continuation_threshold: float = 70.0
    power_hour_impact_threshold: float = 70.0
    power_hour_expected_return_threshold: float = 75.0
    power_hour_continuation_threshold: float = 65.0

    # Velocity settings
    velocity_bonus_max: float = 12.0  # Max score boost for fast multi-source news
    velocity_time_window_seconds: int = 300  # 5 min window to count cross-source

    # Scanning — tightened for faster news-to-alert latency.
    # Most Finviz / StockTitan headlines settle within 30–60s of publication;
    # a 20s scan ensures we catch them within ~1 minute of going live and
    # alert the user before the price has fully run.
    scan_interval_seconds: int = 20
    low_activity_interval_seconds: int = 60
    premarket_start: str = "04:00"
    regular_start: str = "09:30"
    after_hours_start: str = "16:00"
    after_hours_end: str = "20:00"

    # Telegram
    telegram_enabled: bool = True
    telegram_min_score: float = 70.0
    # Ticker cooldown must cover the full news-freshness window so a single
    # catalyst alerts ONCE. At 240 (4h) the same news re-alerted every ~4-6h as
    # cooldowns expired (reworded headlines from different sources dodged the
    # headline-hash dedup). 1080 (18h) > news_max_age_hours (12h) guarantees one
    # alert per catalyst window. A genuinely new same-ticker catalyst next day
    # still alerts. (User intent: repeating a ticker = it's not exploding.)
    telegram_cooldown_minutes: int = 1080

    # ── Catalyst-quality precision filter (V24, backtest-driven) ──────────
    # Backtest of 11,785 resolved alerts: RECOGNIZED catalysts (fda/phase/
    # contract/partnership/M&A...) win 59%; the unrecognized "other"/vague
    # bucket (96% of volume) wins only 3.8%. When enabled, suppress
    # unrecognized catalysts UNLESS corroborated by a real market signal
    # (volume surge / price move / pre-news anomaly / velocity) or a speed
    # tier — that corroboration is exactly how the rare "other"-bucket
    # monsters (e.g. VSA +1083%) actually reveal themselves, so this raises
    # precision WITHOUT killing the explosion-catching.
    # DEFAULT OFF — backtest proved this is a precision-vs-monsters TRADE-OFF,
    # not a free win: enabling it lifts win-rate 5.5%->39.8% but loses 23 of 25
    # explosive movers (>=100%), because at alert time those monsters had rvol=0,
    # move=0, anomaly=0 — indistinguishable from noise. Turn ON only for a
    # high-precision "reliable modest plays" mode; leave OFF to keep hunting the
    # PRFX/VSA-style explosions (accepting the 96% noise that comes with them).
    require_catalyst_or_confirmation: bool = False
    weak_catalyst_min_rvol: float = 3.0
    weak_catalyst_min_move_pct: float = 10.0
    weak_catalyst_min_anomaly: float = 60.0
    under_1_only: bool = True  # Only alert on stocks priced under $10

    # News freshness: ignore headlines published more than this many hours ago.
    # News feeds (Finviz, StockTitan RSS) carry 24-48h of items; without this
    # filter a stale story that lingers in the feed is repeatedly re-detected as
    # "new" (detected_at defaults to now) and re-alerted every cooldown cycle.
    # 12h preserves overnight/premarket plays while killing day-old re-pings.
    news_max_age_hours: float = 12.0

    # Bullish Catalyst Flash: immediate local-first alerts for fresh bullish
    # headlines. These bypass slow score/ML gates but still respect hard
    # bearish, risk, price, cooldown, and SEC veto checks.
    bullish_flash_enabled: bool = True
    # Raised from 180 → 300s (V23.4): observed median alert-time move was
    # 22.7% because the speed tier rarely qualified. With 60-90s of detection
    # latency baked into the scan loop, 180s leaves almost no headroom.
    bullish_flash_max_age_seconds: int = 300
    bullish_flash_min_score: float = 55.0
    bullish_flash_min_impact: float = 20.0
    bullish_flash_min_return: float = 20.0
    bullish_flash_min_continuation: float = 15.0
    bullish_flash_min_multi_day: float = 15.0
    bullish_flash_impact_floor: float = 15.0

    # ML
    ml_enabled: bool = True
    min_outcomes_for_ml: int = 100

    # Learning
    learning_enabled: bool = True
    min_samples_per_catalyst: int = 30
    min_total_samples: int = 100

    # ── Centralized gate thresholds (P0 refactor) ──────────────────────────
    # Previously these lived as inline constants in
    # news_momentum_orchestrator.py and news_momentum_winners.py. They are
    # collected here so the backtest harness (Priority 2) can grid-search
    # them without editing source. Defaults match the prior literal values
    # exactly — changing any default IS a behavior change.

    # ML hard floor / veto. See orchestrator._should_send_telegram.
    ml_min_win_probability: float = 0.25         # was MIN_WIN_PROB
    ml_veto_win_probability: float = 0.20        # ML "confident loser" cut
    ml_veto_min_confidence: float = 0.6          # confidence required to veto
    ml_amplify_win_probability: float = 0.75     # ML "confident winner" cut
    # Raised from 50 → 75 (V23.4): with the prior floor, median impact (~58)
    # was clearing the bypass, so the ML hard floor was almost never
    # enforced on high-conviction catalysts. 75 reserves the bypass for
    # genuinely strong signals only.
    ml_bypass_impact_threshold: float = 75.0     # high-conviction bypass floor

    # Sub-$10 lenient adjustments.
    under_1_lenient_step_down: float = 15.0
    under_1_min_floor: float = 35.0
    under_1_max_price: float = 10.0

    # High-conviction catalyst step-down (orchestrator gate).
    high_conviction_step_down: float = 10.0
    high_conviction_min_floor: float = 30.0

    # First-mover speed tier (orchestrator gate).
    # Raised from 90 → 180s (V23.4): the scan loop typically detects news
    # 30-60s after publication, leaving < 30s for the rest of the candidate
    # pipeline to finish scoring before first_mover would otherwise expire.
    # The result was first_mover essentially never firing; today's median
    # alert went out with the stock already +22.7% because we'd waited for
    # price confirmation instead. 180s preserves the "ahead of the move"
    # premise while giving detection a realistic budget.
    # MAX-SPEED tuning: wider window + lower floors so fresh strong-positive
    # catalysts alert before the spike, accepting more false positives. The
    # cost of a missed +500% mover outweighs a few duds (user preference).
    first_mover_max_age_seconds: int = 300
    first_mover_min_impact: float = 20.0
    first_mover_min_return: float = 20.0
    first_mover_min_continuation: float = 15.0
    first_mover_min_multi_day: float = 15.0
    first_mover_impact_floor: float = 20.0

    # Price-action breakout override.
    breakout_mega_move_pct: float = 35.0
    breakout_mega_rvol: float = 5.0
    breakout_strong_move_pct: float = 20.0
    breakout_strong_rvol: float = 3.0
    breakout_mega_impact_floor: float = 25.0
    breakout_strong_impact_floor: float = 35.0
    breakout_relax_min_impact: float = 35.0      # min/return cap when breakout fires
    breakout_relax_min_continuation: float = 30.0

    # Impact floor base (always-on).
    impact_floor_default: float = 50.0
    impact_floor_under_1: float = 45.0

    # Risk gates.
    high_dilution_block_threshold: float = 70.0
    high_trap_block_threshold: float = 70.0

    # ── Quality gates (V23.4) ────────────────────────────────────────────
    # Added after observing that 41/41 alerts on 2026-05-28 went through
    # with median ml_win_prob=14.8% and 39% catalyst_category=UNKNOWN.
    # Each gate targets a specific failure mode confirmed in that batch.

    # UNKNOWN-catalyst gate: the classifier couldn't identify what the news
    # IS. Without category we can't apply catalyst-specific calibration —
    # the alert is essentially noise. Allow only if impact AND sources
    # confirm the signal independently.
    block_unknown_catalyst: bool = True
    unknown_catalyst_min_impact: float = 75.0
    unknown_catalyst_min_sources: int = 2

    # Chase-the-spike gate: stocks that have ALREADY moved past this much
    # are unlikely to give a clean entry. Confirmed rockets (breakout /
    # first-mover) bypass — those signals carry their own confirmation.
    chase_spike_max_move_pct: float = 75.0
    late_chase_block_move_pct: float = 75.0
    high_conviction_late_chase_max_age_seconds: int = 900
    daily_standard_alert_cap_per_ticker: int = 1

    # Multi-source confirmation for cheap stocks: sub-$2 names are heavily
    # manipulation-prone. Require corroboration unless the catalyst type
    # is in the HIGH_CONVICTION set (those are vetted independently).
    cheap_stock_max_price: float = 2.0
    cheap_stock_min_sources: int = 2

    # Winner-targeting ML tier bands (news_momentum_winners._ML_PERCENTILE_BANDS).
    # Mutable globals stay in winners.py for hot-recalibration; these defaults
    # mirror the seed values and are used for snapshot equivalence.
    ml_band_p85: float = 0.20
    ml_band_p95: float = 0.30
    ml_band_p99: float = 0.40
    ml_tier_high_conviction_adjust: float = 15.0
    ml_tier_watch_adjust: float = -10.0


class NewsMomentumScanResult(BaseModel):
    """Result from a news momentum scan."""
    scan_time: datetime
    session: SessionType
    candidates: List[NewsMomentumCandidate] = Field(default_factory=list)
    top_expected_return: List[NewsMomentumCandidate] = Field(default_factory=list)
    top_continuation: List[NewsMomentumCandidate] = Field(default_factory=list)
    top_multiday: List[NewsMomentumCandidate] = Field(default_factory=list)
    trap_warnings: List[NewsMomentumCandidate] = Field(default_factory=list)
    telegram_alerts_sent: int = 0
