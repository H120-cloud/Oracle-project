from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# ── Enums ────────────────────────────────────────────────────────────────────

class SignalAction(str, Enum):
    BUY = "BUY"
    WATCH = "WATCH"
    AVOID = "AVOID"
    NO_VALID_SETUP = "NO_VALID_SETUP"


class StockClassification(str, Enum):
    DIP_FORMING = "dip_forming"
    BOUNCE_FORMING = "bounce_forming"
    DIP_BOUNCE_FORMING = "dip_bounce_forming"  # Both dip and bounce patterns present
    BREAKOUT_CONTINUATION = "breakout_continuation"
    SIDEWAYS = "sideways"
    BREAKDOWN_RISK = "breakdown_risk"
    OVEREXTENDED = "overextended"
    NO_VALID_SETUP = "no_valid_setup"


class DipPhase(str, Enum):
    EARLY = "early"
    MID = "mid"
    LATE = "late"


class OutcomeType(str, Enum):
    WIN = "win"
    LOSS = "loss"
    EXPIRED = "expired"
    UNKNOWN = "unknown"


class MarketRegime(str, Enum):
    TRENDING = "trending"
    CHOPPY = "choppy"
    HIGH_VOLATILITY = "high_volatility"
    LOW_VOLATILITY = "low_volatility"


class MarketTrendRegime(str, Enum):
    """V6: Three-regime trend classification for dip signal filtering."""
    STRONG_TREND = "strong_trend"
    CHOPPY = "choppy"
    BEARISH = "bearish"


class BearishState(str, Enum):
    """Bearish transition states for exit warning system."""
    BULLISH = "bullish"
    NEUTRAL = "neutral"
    WEAKENING = "weakening"
    BEARISH_TRANSITION = "bearish_transition"
    CONFIRMED_BEARISH = "confirmed_bearish"


class ExitWarningLevel(str, Enum):
    """Exit warning severity levels."""
    NONE = "none"
    EARLY_WARNING = "early_warning"
    STRONG_WARNING = "strong_warning"
    EXIT_SIGNAL = "exit_signal"


class StockType(str, Enum):
    LOW_FLOAT_MOMENTUM = "low_float_momentum"
    MID_CAP_LIQUID = "mid_cap_liquid"
    BIOTECH_NEWS = "biotech_news"
    EARNINGS_MOVER = "earnings_mover"
    UNKNOWN = "unknown"


class MoveStage(int, Enum):
    BREAKOUT = 1
    STRONG_TREND = 2
    EXTENDED = 3
    DISTRIBUTION = 4
    BREAKDOWN = 5


class ExpiryReason(str, Enum):
    TIME_EXPIRED = "time_expired"
    NO_BOUNCE = "no_bounce"
    RECLAIM_FAILED = "reclaim_failed"
    MOMENTUM_FADED = "momentum_faded"


# ── Scanner ──────────────────────────────────────────────────────────────────

class ScanFilter(BaseModel):
    min_price: float = 1.0
    max_price: float = 500.0
    min_volume: int = 500_000
    min_rvol: Optional[float] = None
    max_results: int = 20


class ScannedStock(BaseModel):
    # Base data
    ticker: str
    price: float
    volume: float
    rvol: Optional[float] = None
    change_percent: Optional[float] = None
    market_cap: Optional[float] = None
    float_shares: Optional[float] = None
    scan_type: str
    
    # V6 Professional Scanner Fields
    # Layer 2: Pre-market
    premarket_gap_percent: Optional[float] = None
    premarket_volume_vs_avg: Optional[float] = None
    premarket_status: Optional[str] = None  # strong, weak, none
    
    # Layer 3: Volume Analysis
    volume_as_pct_of_float: Optional[float] = None
    volume_trend: Optional[str] = None  # increasing, stable, decreasing, single_spike
    sustained_participation: bool = False
    
    # Layer 4: Catalyst
    has_catalyst: bool = False
    catalyst_tier: Optional[str] = None  # tier_1, tier_2, tier_3, none
    catalyst_headline: Optional[str] = None
    catalyst_sentiment: Optional[str] = None  # positive, neutral, negative
    
    # Layer 5: Structure
    structure_quality: Optional[str] = None  # clean_trend, choppy, weakening, broken
    higher_highs: bool = False
    lower_highs: bool = False
    gap_behavior: Optional[str] = None  # gap_and_go, gap_and_fade, reclaim_attempt, no_gap
    
    # Layer 6: Extension
    distance_from_vwap: Optional[float] = None
    distance_from_high: Optional[float] = None
    extension_pct: Optional[float] = None
    extension_state: Optional[str] = None  # early, mid, extended
    
    # Layer 7: Liquidity
    liquidity_quality: Optional[str] = None  # high, acceptable, poor
    spread_pct: Optional[float] = None
    
    # Layer 8: Stock Type
    stock_type: Optional[str] = None  # penny, micro, small, large
    float_category: Optional[str] = None  # low, medium, high
    
    # Layer 9: Risk
    risk_level: Optional[str] = None  # normal, moderate, high
    halt_risk: bool = False
    
    # Layer 10: Multi-timeframe
    timeframe_alignment: Optional[str] = None  # bullish, mixed, conflicting
    
    # Layer 11: Rejection Risk
    rejection_risk_score: float = 0.0  # 0-100
    failed_highs_count: int = 0
    upper_wick_pressure: bool = False
    
    # Layer 12: Relative Strength
    relative_strength: Optional[str] = None  # outperforming, inline, lagging
    outperformance_pct: Optional[float] = None
    
    # Layer 13: Sector/Theme
    sector: Optional[str] = None
    theme: Optional[str] = None
    
    # Layer 14: In-Play
    in_play_status: Optional[str] = None  # active, fading, dead
    
    # Layer 15: Setup Readiness
    setup_readiness: Optional[str] = None  # ready_for_dip, breakout_candidate, extended, avoid
    analyze_for_dip: bool = False
    breakout_candidate: bool = False
    monitor_bearish_shift: bool = False
    
    # Layer 16: Scoring
    final_score: float = 0.0  # 0-100
    scan_rank: int = 0
    
    # Layer 17: Reason Log
    positive_reasons: Optional[list[str]] = None
    negative_reasons: Optional[list[str]] = None
    key_risks: Optional[list[str]] = None
    
    # Layer 18: Exclusion
    excluded: bool = False
    exclusion_reason: Optional[str] = None
    
    # Layer 19: Integration Tags
    tags: Optional[list[str]] = None  # analyze_for_dip, breakout_candidate, ignore, etc.
    
    # V9: HTF-Aware Scanner Fields
    htf_bias: Optional[str] = None  # BULLISH/NEUTRAL/BEARISH
    htf_strength_score: Optional[float] = None  # 0-100 composite
    htf_structure_score: Optional[float] = None  # 0-100
    htf_ema_score: Optional[float] = None  # 0-100
    htf_momentum_score: Optional[float] = None  # 0-100
    htf_adx_score: Optional[float] = None  # 0-100
    scanner_htf_status: Optional[str] = None  # ALIGNED/NEUTRAL/BLOCKED/REVERSAL_ONLY
    scanner_htf_reason: Optional[str] = None  # Why scanner made this decision
    htf_rank_boost: Optional[float] = None  # Score adjustment from HTF (+/-)
    htf_alignment_readiness: Optional[str] = None  # ready/blocked/needs_confirmation
    
    passed_to_main: bool = False


class ScanResponse(BaseModel):
    stocks: list[ScannedStock]
    scanned_at: datetime
    scan_type: str


# ── Dip Detection ───────────────────────────────────────────────────────────

class DipFeatures(BaseModel):
    vwap_distance_pct: float = Field(description="% distance from VWAP")
    ema9_distance_pct: float = Field(description="% distance from EMA-9")
    ema20_distance_pct: float = Field(description="% distance from EMA-20")
    drop_from_high_pct: float = Field(description="% drop from intraday high")
    consecutive_red_candles: int = 0
    red_candle_volume_ratio: float = Field(
        1.0, description="Avg red candle vol / avg green candle vol"
    )
    lower_highs_count: int = 0
    momentum_decay: float = Field(0.0, description="Rate of momentum change")
    # V7: Momentum intelligence fields
    price_velocity: float = Field(0.0, description="Price change velocity % per bar")
    price_acceleration: float = Field(0.0, description="Change in velocity (acceleration)")
    momentum_state: str = Field("neutral", description="accelerating_down/slowing_down/bullish/neutral")
    structure_intact: bool = Field(True, description="Higher low maintained or reclaimed")
    is_falling_knife: bool = Field(False, description="Strong negative velocity + acceleration")


class DipResult(BaseModel):
    ticker: str
    probability: float = Field(ge=0, le=100)
    phase: DipPhase
    features: DipFeatures
    is_valid_dip: bool


# ── Bounce Detection ────────────────────────────────────────────────────────

class BounceFeatures(BaseModel):
    support_distance_pct: float = Field(description="% from nearest support")
    selling_pressure_change: float = Field(
        description="Change in selling pressure (negative = less selling)"
    )
    buying_pressure_ratio: float = Field(description="Buy vol / sell vol ratio")
    higher_low_formed: bool = False
    key_level_reclaimed: bool = False
    rsi: Optional[float] = None
    macd_histogram_slope: Optional[float] = None
    # V7: Momentum intelligence fields
    price_velocity: float = Field(0.0, description="Price change velocity % per bar")
    price_acceleration: float = Field(0.0, description="Change in velocity")
    momentum_state: str = Field("neutral", description="slowing_down/accelerating_up/bullish/neutral")


class BounceResult(BaseModel):
    ticker: str
    probability: float = Field(ge=0, le=100)
    entry_ready: bool
    trigger_price: Optional[float] = None
    features: BounceFeatures
    is_valid_bounce: bool


# ── ICT / Smart Money Concepts (V3) ──────────────────────────────────────────

class ICTFeatures(BaseModel):
    """ICT-style smart money features."""
    bos_detected: bool = False
    bos_direction: str = "none"  # "bullish" or "bearish"
    liquidity_sweep: bool = False
    sweep_direction: str = "none"  # "up" or "down"
    sweep_level: float = 0.0
    impulse_origin_price: float = 0.0
    impulse_strength_pct: float = 0.0
    order_block_price: float = 0.0
    order_block_type: str = "none"  # "bullish" or "bearish"
    extension_pct: float = 0.0
    is_overextended: bool = False
    recent_swing_low: float = 0.0
    recent_swing_high: float = 0.0

    # V3 fields (from previous implementation)
    ict_score: int = 0
    micro_high_level: float = 0.0
    micro_low_level: float = 0.0
    structure_break_confirmed: bool = False
    distance_to_order_block_pct: float = 0.0
    near_order_block: bool = False
    trap_detected: bool = False
    trap_reason: str = ""
    structure_reclaimed: bool = False
    reclaim_level: float = 0.0

    # V4: Execution quality fields
    atr_value: float = 0.0
    atr_pct: float = 0.0
    volatility_class: str = "medium"  # "low", "medium", "high"
    atr_stop_multiplier: float = 1.5
    order_block_freshness: float = 1.0  # 0.0-1.0, 1.0 = fresh

    # V7: Follow-through confirmation fields
    breakout_quality: str = Field("none", description="confirmed/weak/fake/none")
    follow_through_confirmed: bool = Field(False, description="2-3 candles closed above breakout")
    follow_through_candles: int = Field(0, description="Number of confirming candles")
    upper_wick_pressure: bool = Field(False, description="Strong upper wicks detected")
    volume_stable_or_increasing: bool = Field(True, description="Volume sustained after breakout")


# ── Volume Profile (V3) ─────────────────────────────────────────────────────

class VolumeProfileData(BaseModel):
    poc_price: float = Field(description="Point of Control — highest volume price")
    value_area_high: float = Field(description="Upper bound of 70% volume range")
    value_area_low: float = Field(description="Lower bound of 70% volume range")
    high_volume_nodes: list[float] = Field(default_factory=list)
    support_levels: list[float] = Field(default_factory=list)
    resistance_levels: list[float] = Field(default_factory=list)


# ── Regime / Segmentation / Stage (V3) ──────────────────────────────────────

class RegimeData(BaseModel):
    regime: MarketRegime
    adx: Optional[float] = None
    bb_width: Optional[float] = None
    atr_pct: Optional[float] = None
    sensitivity_multiplier: float = 1.0


class RegimeFilterResult(BaseModel):
    """V6: Market trend regime classification for dip signal filtering."""
    regime: MarketTrendRegime = Field(description="STRONG_TREND, CHOPPY, or BEARISH")
    confidence_score: float = Field(description="Regime classification confidence 0-100")
    reason: str = Field(description="Why this regime was classified")
    
    # Component scores for analysis
    ema_score: float = Field(description="EMA structure score 0-100")
    price_vs_ema50: float = Field(description="Price distance from EMA50 in %")
    trend_structure_score: float = Field(description="HH/HL trend score 0-100")
    vwap_score: float = Field(description="Price vs VWAP score 0-100")
    
    # Technical values
    ema9: float = Field(description="9-period EMA value")
    ema20: float = Field(description="20-period EMA value")
    ema50: float = Field(description="50-period EMA value")
    vwap: float = Field(description="Volume Weighted Average Price")
    current_price: float = Field(description="Current price")


class StockSegment(BaseModel):
    stock_type: StockType
    reason: str


class StageResult(BaseModel):
    ticker: str
    stage: MoveStage
    entry_allowed: bool = Field(description="True if stage 1-2")
    reason: str


class BearishTransitionData(BaseModel):
    """Bearish transition / exit warning detection results."""
    ticker: str
    bearish_state: BearishState = Field(description="Current bearish state classification")
    bearish_probability: float = Field(ge=0, le=100, description="Bearish probability score 0-100%")
    exit_warning: ExitWarningLevel = Field(description="Exit warning level")
    key_support_level: Optional[float] = Field(description="Key support level to watch")
    invalidation_level: Optional[float] = Field(description="Level that confirms bearish transition")
    top_reasons: list[str] = Field(default_factory=list, description="Top reasons for bearish shift")
    
    # Technical details for debugging
    lower_highs_detected: bool = False
    failed_breakout_detected: bool = False
    structure_break_detected: bool = False
    support_lost: bool = False
    resistance_rejection: bool = False
    vwap_lost: bool = False
    ema9_lost: bool = False
    ema20_lost: bool = False
    rising_selling_pressure: bool = False
    negative_order_flow: bool = False
    distribution_behavior: bool = False
    # V7: Early topping detection fields
    early_bearish_warning: bool = Field(False, description="Pre-reversal topping signals detected")
    early_bearish_confidence: float = Field(0.0, ge=0, le=100, description="Confidence in early warning")
    multiple_resistance_rejections: int = Field(0, description="Count of rejections at resistance")
    decreasing_volume_on_rises: bool = Field(False, description="Volume dropping on upward moves")
    increasing_upper_wicks: bool = Field(False, description="Upper wicks growing near highs")
    momentum_slowed_near_highs: bool = Field(False, description="Momentum decay at resistance")


# ── Signal ───────────────────────────────────────────────────────────────────

class TradingSignal(BaseModel):
    id: Optional[uuid.UUID] = None
    ticker: str
    action: SignalAction
    classification: StockClassification
    dip_probability: Optional[float] = None
    bounce_probability: Optional[float] = None
    entry_price: Optional[float] = None
    stop_price: Optional[float] = None
    target_prices: Optional[list[float]] = None
    # V2 — risk scoring
    risk_score: Optional[int] = Field(None, ge=1, le=10)
    setup_grade: Optional[str] = Field(None, pattern=r"^[A-F]$")
    confidence: Optional[float] = Field(None, ge=0, le=100)
    # V3 — advanced analysis
    stage: Optional[int] = Field(None, ge=1, le=5)
    regime: Optional[str] = None
    stock_type: Optional[str] = None
    volume_profile: Optional[VolumeProfileData] = None
    expiry_reason: Optional[str] = None
    # V4 — order flow
    order_flow: Optional["OrderFlowData"] = None
    signal_expiry: Optional[datetime] = None
    reason: Optional[list[str]] = None
    created_at: Optional[datetime] = None

    # V5 — Position Sizing & Risk Management
    account_equity: Optional[float] = None           # Account value at signal time
    max_risk_per_trade_pct: Optional[float] = None  # Configurable (e.g., 1.0%)
    position_size_shares: Optional[int] = None      # Calculated shares
    dollar_risk_per_share: Optional[float] = None   # Entry - Stop
    total_dollar_risk: Optional[float] = None        # Total $ at risk
    total_capital_used: Optional[float] = None      # Position value
    r_multiples: Optional[list[float]] = None       # R for T1/T2/T3
    expected_reward_t1: Optional[float] = None      # $ reward at target 1
    expected_reward_t2: Optional[float] = None
    expected_reward_t3: Optional[float] = None
    position_sizing_rejected: bool = False          # True if sizing failed safeguards
    rejection_reason: Optional[str] = None           # Why sizing rejected

    # V6 — Liquidity-Aware Execution (Penny Stock / Microcap Support)
    bid_ask_spread_pct: Optional[float] = None       # Spread as % of price
    estimated_slippage_pct: Optional[float] = None   # Expected slippage on entry/exit
    liquidity_score: Optional[float] = None            # 0-100 quality score
    order_size_pct_of_adv: Optional[float] = None    # Position vs Average Daily Volume
    order_size_pct_of_intraday: Optional[float] = None  # Position vs today's volume
    tick_size: Optional[float] = None                # Minimum price increment
    execution_quality_acceptable: bool = True        # False if liquidity/spread issues
    slippage_adjusted_stop: Optional[float] = None   # Stop including slippage estimate
    slippage_adjusted_targets: Optional[list[float]] = None  # Targets net of slippage

    # V6 — Market Regime Filter (Trend Classification)
    market_regime: Optional[str] = None              # STRONG_TREND, CHOPPY, or BEARISH
    regime_confidence_score: Optional[float] = None  # 0-100 confidence in regime
    regime_reason: Optional[str] = None              # Why this regime was classified
    regime_blocked: bool = False                       # True if BEARISH blocked the trade
    regime_downgrade_applied: bool = False           # True if CHOPPY downgraded confidence

    # V6 — Bearish Transition / Exit Warning Module
    bearish_state: Optional[str] = None              # bullish, neutral, weakening, bearish_transition, confirmed_bearish
    bearish_probability: Optional[float] = None      # 0-100 probability score
    exit_warning: bool = False                       # True if exit warning triggered
    key_support_level: Optional[float] = None        # Key support to watch
    invalidation_level: Optional[float] = None       # Level confirming bearish transition
    top_bearish_reasons: Optional[list[str]] = None  # Top reasons for bearish shift

    # V7 — Momentum & Structure Intelligence (Enhanced Audit Compliance)
    momentum_state: Optional[str] = None             # accelerating_down/slowing_down/bullish/neutral
    structure_status: Optional[str] = None           # intact/broken/reclaimed
    breakout_quality: Optional[str] = None         # confirmed/weak/fake/none
    target_type: Optional[str] = None                # liquidity/volume_profile/momentum_extended/fixed_r
    early_bearish_warning: bool = False            # Pre-reversal early warning active
    early_bearish_confidence: Optional[float] = None # 0-100 confidence in early warning
    dip_quality_score: Optional[float] = None        # Enhanced dip quality 0-100
    is_falling_knife: bool = False                 # Rejected as falling knife
    structure_reject_reason: Optional[str] = None  # Why structure validation failed
    follow_through_confirmed: bool = False          # Breakout follow-through verified

    # V8 — Higher Timeframe Confirmation (Multi-Timeframe Alignment)
    htf_bias: Optional[str] = None                   # BULLISH/NEUTRAL/BEARISH
    htf_strength_score: Optional[float] = None     # 0-100 composite score
    htf_structure_score: Optional[float] = None      # 0-100 structure component
    htf_ema_score: Optional[float] = None            # 0-100 EMA alignment component
    htf_momentum_score: Optional[float] = None       # 0-100 momentum component
    htf_adx_score: Optional[float] = None            # 0-100 trend strength component
    htf_rsi: Optional[float] = None                    # HTF RSI value
    htf_adx: Optional[float] = None                    # HTF ADX value
    alignment_status: Optional[str] = None           # ALIGNED/NEUTRAL/COUNTER_TREND
    trade_type: Optional[str] = None                 # TREND_FOLLOWING/COUNTER_TREND_REVERSAL
    htf_alignment_reason: Optional[str] = None      # Why this alignment was decided
    htf_blocked: bool = False                          # True if HTF filter blocked the trade
    alignment_confidence_adj: Optional[int] = None   # Confidence adjustment from alignment

    model_config = {"from_attributes": True}


class SignalResponse(BaseModel):
    signals: list[TradingSignal]
    generated_at: datetime
    count: int


# ── Watchlist ────────────────────────────────────────────────────────────────

class WatchlistAlertItem(BaseModel):
    id: Optional[str] = None
    alert_type: str
    severity: str = "info"
    message: str
    data: Optional[dict] = None
    read: bool = False
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class WatchlistTimelineItem(BaseModel):
    id: Optional[str] = None
    event_type: str
    description: str
    data: Optional[dict] = None
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class WatchlistItem(BaseModel):
    id: Optional[str] = None
    ticker: str
    company_name: Optional[str] = None
    added_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    active: bool = True

    # Source & context
    source: str = "manual"
    tags: list[str] = []
    notes: Optional[str] = None
    watch_reason: Optional[str] = None

    # Priority
    priority: str = "medium"
    priority_score: float = 50.0

    # Key levels
    support_level: Optional[float] = None
    resistance_level: Optional[float] = None
    invalidation_level: Optional[float] = None

    # Latest metrics
    latest_price: Optional[float] = None
    latest_change_pct: Optional[float] = None
    latest_volume: Optional[float] = None
    latest_rvol: Optional[float] = None
    latest_dip_prob: Optional[float] = None
    latest_bounce_prob: Optional[float] = None
    latest_bearish_prob: Optional[float] = None
    latest_regime: Optional[str] = None
    latest_stage: Optional[int] = None
    latest_in_play: Optional[str] = None
    latest_extension: Optional[str] = None
    latest_liquidity_score: Optional[float] = None
    latest_rejection_risk: Optional[float] = None
    latest_final_score: Optional[float] = None
    metrics_updated_at: Optional[datetime] = None
    
    # V8: Higher Timeframe (HTF) Analysis
    latest_htf_bias: Optional[str] = None  # BULLISH/NEUTRAL/BEARISH
    latest_htf_strength_score: Optional[float] = None  # 0-100
    latest_alignment_status: Optional[str] = None  # ALIGNED/NEUTRAL/COUNTER_TREND
    latest_trade_type: Optional[str] = None  # TREND_FOLLOWING/COUNTER_TREND_REVERSAL
    latest_htf_blocked: bool = False  # True if HTF filter blocked
    latest_htf_alignment_reason: Optional[str] = None  # Block/allow reason
    latest_htf_rsi: Optional[float] = None  # HTF RSI value
    latest_htf_adx: Optional[float] = None  # HTF ADX value
    latest_htf_updated_at: Optional[datetime] = None  # When HTF was last calculated

    # Alerts
    latest_alert: Optional[str] = None
    latest_alert_at: Optional[datetime] = None
    alert_count: int = 0

    # Status
    status: str = "active"
    archived_at: Optional[datetime] = None
    archive_reason: Optional[str] = None

    # Analysis snapshot
    analysis_snapshot: Optional[dict] = None

    # Earnings calendar
    next_earnings_date: Optional[datetime] = None
    earnings_warning_shown: bool = False
    days_until_earnings: Optional[int] = None  # Computed field

    model_config = {"from_attributes": True}


class WatchlistAddRequest(BaseModel):
    ticker: str
    source: str = "manual"
    tags: list[str] = []
    notes: Optional[str] = None
    watch_reason: Optional[str] = None
    priority: str = "medium"
    support_level: Optional[float] = None
    resistance_level: Optional[float] = None
    invalidation_level: Optional[float] = None
    analysis_snapshot: Optional[dict] = None


class WatchlistUpdateRequest(BaseModel):
    tags: Optional[list[str]] = None
    notes: Optional[str] = None
    watch_reason: Optional[str] = None
    priority: Optional[str] = None
    support_level: Optional[float] = None
    resistance_level: Optional[float] = None
    invalidation_level: Optional[float] = None


class WatchlistResponse(BaseModel):
    items: list[WatchlistItem]
    count: int


class WatchlistDetailResponse(BaseModel):
    item: WatchlistItem
    alerts: list[WatchlistAlertItem] = []
    timeline: list[WatchlistTimelineItem] = []


# ── Custom Price Alerts ───────────────────────────────────────────────────

class CustomAlertType(str, Enum):
    PRICE_ABOVE = "price_above"
    PRICE_BELOW = "price_below"
    PERCENT_CHANGE_UP = "percent_change_up"
    PERCENT_CHANGE_DOWN = "percent_change_down"
    RVOL_ABOVE = "rvol_above"


class CustomAlertItem(BaseModel):
    id: Optional[str] = None
    ticker: str
    alert_type: str
    target_value: float
    reference_price: Optional[float] = None
    is_active: bool = True
    triggered_at: Optional[datetime] = None
    triggered_price: Optional[float] = None
    message: Optional[str] = None
    notification_sent: bool = False
    created_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class CustomAlertCreate(BaseModel):
    ticker: str
    alert_type: str  # price_above, price_below, percent_change_up, percent_change_down, rvol_above
    target_value: float
    reference_price: Optional[float] = None
    message: Optional[str] = None
    expires_days: Optional[int] = 30  # Auto-expire after N days


class CustomAlertListResponse(BaseModel):
    alerts: list[CustomAlertItem]
    active_count: int
    triggered_count: int


# ── Outcome Logging ─────────────────────────────────────────────────────────

class OutcomeRecord(BaseModel):
    signal_id: uuid.UUID
    price_after_5m: Optional[float] = None
    price_after_15m: Optional[float] = None
    price_after_30m: Optional[float] = None
    price_after_60m: Optional[float] = None
    outcome: OutcomeType = OutcomeType.UNKNOWN
    pnl_percent: Optional[float] = None

    # V4: Post-trade execution analytics
    max_favorable_excursion: Optional[float] = None  # Max profit % reached
    max_adverse_excursion: Optional[float] = None    # Max drawdown % during trade
    reached_target_1: bool = False                 # Did it hit first target?
    reached_target_2: bool = False
    reached_target_3: bool = False
    hit_stop_first: bool = False                     # Stop before any target
    false_stop: bool = False                        # Hit stop, then hit target later
    hold_time_minutes: Optional[int] = None          # How long position was held
    exit_price: Optional[float] = None              # Actual exit price
    exit_reason: Optional[str] = None                # "target", "stop", "manual", "expired"

    # V5: R-multiple and risk-adjusted performance
    r_multiple: Optional[float] = None             # P&L in R units
    target_r_multiple: Optional[float] = None      # Expected R at entry
    risk_adjusted_return: Optional[float] = None   # Return per unit risk
    actual_shares: Optional[int] = None             # Actually traded size
    actual_dollar_risk: Optional[float] = None       # Actual $ at risk
    account_equity_at_exit: Optional[float] = None # For context


# ── OHLCV Bar ────────────────────────────────────────────────────────────────

class OHLCVBar(BaseModel):
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


# ── Order Flow (V4) ─────────────────────────────────────────────────────────

class OrderFlowData(BaseModel):
    bid_ask_imbalance: float = Field(description="Ratio of bid vs ask volume, >1 = buying pressure")
    aggressive_buy_ratio: float = Field(description="Fraction of volume at ask (aggressive buys)")
    aggressive_sell_ratio: float = Field(description="Fraction of volume at bid (aggressive sells)")
    large_order_buy_volume: float = 0.0
    large_order_sell_volume: float = 0.0
    tape_speed: float = Field(0.0, description="Trades per second — higher = more activity")
    net_flow: float = Field(0.0, description="Net buy volume minus sell volume")
    signal: str = Field("neutral", description="bullish / bearish / neutral")


# ── Self-Learning (V4) ──────────────────────────────────────────────────────

class PerformanceSnapshot(BaseModel):
    total_signals: int = 0
    total_wins: int = 0
    total_losses: int = 0
    win_rate: float = 0.0
    avg_pnl_pct: float = 0.0
    profit_factor: float = 0.0
    best_setup_grade: Optional[str] = None
    worst_setup_grade: Optional[str] = None
    avg_confidence: float = 0.0


class ThresholdAdjustment(BaseModel):
    parameter: str
    old_value: float
    new_value: float
    reason: str


# ── V4: Signal Monitoring & Execution Quality ───────────────────────────────

class SignalMonitoringMetrics(BaseModel):
    """Real-time signal flow monitoring to prevent over-filtering."""
    signals_today: int = 0
    buy_signals_today: int = 0
    watch_signals_today: int = 0
    rejected_signals_today: int = 0
    avg_signals_per_day_7d: float = 0.0
    rejection_reasons_breakdown: dict[str, int] = Field(default_factory=dict)
    warning_flags: list[str] = Field(default_factory=list)  # e.g., "too_restrictive", "flow_low"


class TradePerformanceMetrics(BaseModel):
    """Comprehensive trade execution performance."""
    # Basic metrics
    total_trades: int = 0
    win_rate: float = 0.0
    avg_winner_pct: float = 0.0
    avg_loser_pct: float = 0.0
    profit_factor: float = 0.0

    # V4: Execution quality metrics
    avg_r_multiple: float = 0.0  # Average R return (reward/risk)
    false_stop_rate: float = 0.0  # % of stops that hit before target was later reached
    avg_mfe_pct: float = 0.0  # Average max favorable excursion
    avg_mae_pct: float = 0.0  # Average max adverse excursion
    avg_hold_time_minutes: float = 0.0

    # Stop quality analysis
    stops_too_tight_count: int = 0  # Stopped out, then target hit within 30 min
    stops_appropriate_count: int = 0  # Stopped out, target never hit
    target_hits_before_stop_count: int = 0  # Normal wins

    # Volatility performance
    low_vol_win_rate: float = 0.0
    medium_vol_win_rate: float = 0.0
    high_vol_win_rate: float = 0.0


# ── Backtesting (V4) ────────────────────────────────────────────────────────

class BacktestConfig(BaseModel):
    ticker: str
    start_date: str
    end_date: str
    interval: str = "1d"
    initial_capital: float = 10000.0


# ── V6: Liquidity Profile (Microstructure) ────────────────────────────────────

class LiquidityProfile(BaseModel):
    """Microstructure data for execution quality assessment."""
    average_daily_volume: int = 0           # 20-day ADV
    today_volume: int = 0                 # Current day volume
    intraday_volume_15min: int = 0          # Last 15 min volume (for pacing)
    bid_price: float = 0.0
    ask_price: float = 0.0
    spread_amount: float = 0.0              # Ask - Bid
    spread_pct: float = 0.0                 # Spread / Mid
    tick_size: float = 0.01                 # Minimum price increment
    price: float = 0.0                      # Current price


class LiquidityExecutionConfig(BaseModel):
    """Configuration for liquidity-aware execution."""
    # Order size vs volume caps
    max_order_size_pct_of_adv: float = 5.0      # Max 5% of daily volume
    max_order_size_pct_of_intraday: float = 15.0  # Max 15% of current day's volume
    # Spread thresholds (by price tier)
    penny_spread_max_pct: float = 3.0            # Max 3% spread for <$1 stocks
    micro_spread_max_pct: float = 2.0            # Max 2% for $1-5 stocks
    small_spread_max_pct: float = 1.0            # Max 1% for $5-20 stocks
    standard_spread_max_pct: float = 0.5         # Max 0.5% for >$20 stocks
    # Liquidity quality thresholds
    min_liquidity_score: float = 30.0            # Reject if score < 30
    # Slippage estimates by tier
    penny_slippage_base_pct: float = 1.5         # Base 1.5% for pennies
    micro_slippage_base_pct: float = 0.8
    small_slippage_base_pct: float = 0.4
    standard_slippage_base_pct: float = 0.2


# ── V5: Position Sizing Configuration ───────────────────────────────────────────

class PositionSizingConfig(BaseModel):
    """Configuration for risk-based position sizing."""
    max_risk_per_trade_pct: float = 1.0  # Default 1% of equity per trade
    max_position_size_pct: float = 10.0  # Max 10% of equity in one position
    min_position_size_shares: int = 10   # Minimum practical trade size
    max_position_size_shares: int = 10000  # Absolute max
    max_stop_distance_pct: float = 8.0   # Reject if stop > 8% from entry
    # Volatility-based caps
    low_vol_max_position_multiplier: float = 1.5   # 150% of base in low vol
    high_vol_max_position_multiplier: float = 0.6  # 60% of base in high vol
    # Stock type caps
    low_float_max_position_pct: float = 5.0   # Max 5% for low float
    large_cap_max_position_pct: float = 15.0  # Max 15% for large cap
    # V6: Liquidity execution config
    liquidity_config: Optional[LiquidityExecutionConfig] = None


class PositionSizingResult(BaseModel):
    """Result of position sizing calculation."""
    shares: int = 0
    dollar_risk_per_share: float = 0.0
    total_dollar_risk: float = 0.0
    total_capital_used: float = 0.0
    r_multiples: list[float] = Field(default_factory=list)
    expected_rewards: list[float] = Field(default_factory=list)
    accepted: bool = False
    rejection_reason: Optional[str] = None
    # Sizing constraints applied
    max_risk_pct_applied: float = 0.0
    vol_cap_applied: bool = False
    stock_type_cap_applied: bool = False
    # V6: Liquidity execution fields
    liquidity_score: float = 0.0
    spread_pct: float = 0.0
    slippage_pct: float = 0.0
    order_pct_of_adv: float = 0.0
    order_pct_of_intraday: float = 0.0
    slippage_adjusted_stop: float = 0.0
    slippage_adjusted_targets: list[float] = Field(default_factory=list)
    liquidity_cap_applied: bool = False


class BacktestTrade(BaseModel):
    entry_date: str
    exit_date: str
    entry_price: float
    exit_price: float
    action: str
    pnl_pct: float
    setup_grade: Optional[str] = None


class BacktestResult(BaseModel):
    config: BacktestConfig
    trades: list[BacktestTrade]
    total_trades: int = 0
    win_rate: float = 0.0
    total_return_pct: float = 0.0
    max_drawdown_pct: float = 0.0
    sharpe_ratio: Optional[float] = None
    profit_factor: float = 0.0
    avg_win_pct: float = 0.0
    avg_loss_pct: float = 0.0
