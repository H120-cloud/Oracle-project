"""Historical Catalyst Training Engine — Data Models"""
from __future__ import annotations
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field
from src.core.agentic.models import CatalystType, FloatCategory

class HistoricalOutcomeClass(str, Enum):
    CLEAN_EXPANSION = "clean_expansion"
    SECOND_LEG_CONTINUATION = "second_leg_continuation"
    PARTIAL_MOVE = "partial_move"
    FADED_MOVE = "faded_move"
    FAILED_CATALYST = "failed_catalyst"
    SELL_THE_NEWS = "sell_the_news"
    TRAP_MOVE = "trap_move"
    NO_REACTION = "no_reaction"

class TrainingMode(str, Enum):
    ANALYSE_ONLY = "analyse_only"
    RECOMMEND_ONLY = "recommend_only"
    APPROVED_APPLY = "approved_apply"

class ConfidenceLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"

class DataQuality(str, Enum):
    FULL = "full"
    PARTIAL = "partial"
    DEGRADED = "degraded"
    STALE = "stale"

class HistoricalCatalystEvent(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    ticker: str
    catalyst_type: CatalystType
    catalyst_headline: str = ""
    catalyst_source: str = ""
    catalyst_timestamp: Optional[datetime] = None
    price_at_news: float = 0.0
    price_before_30m: Optional[float] = None
    price_before_1h: Optional[float] = None
    price_before_2h: Optional[float] = None
    price_before_1d: Optional[float] = None
    volume_before_30m: Optional[float] = None
    volume_before_1h: Optional[float] = None
    volume_before_2h: Optional[float] = None
    rvol_before_news: Optional[float] = None
    volume_acceleration_before_news: Optional[float] = None
    spread_before_news: Optional[float] = None
    vwap_position_before_news: Optional[float] = None
    float_shares: Optional[float] = None
    market_cap: Optional[float] = None
    float_category: Optional[FloatCategory] = None
    is_premarket: bool = False
    time_of_day_bucket: Optional[str] = None
    data_quality: DataQuality = DataQuality.FULL
    feature_snapshot: Optional[dict] = None
    outcome: Optional[dict] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    resolved_at: Optional[datetime] = None
    event_date: str = ""

class HistoricalOutcome(BaseModel):
    event_id: str = ""
    outcome_class: HistoricalOutcomeClass = HistoricalOutcomeClass.NO_REACTION
    price_after_5m: Optional[float] = None
    price_after_15m: Optional[float] = None
    price_after_30m: Optional[float] = None
    price_after_1h: Optional[float] = None
    price_after_eod: Optional[float] = None
    price_next_day: Optional[float] = None
    move_after_news_pct: float = 0.0
    max_favorable_excursion_pct: Optional[float] = None
    max_adverse_excursion_pct: Optional[float] = None
    time_to_high_minutes: Optional[float] = None
    time_to_failure_minutes: Optional[float] = None
    target_1_hit: bool = False
    target_2_hit: bool = False
    target_1_pct: Optional[float] = None
    target_2_pct: Optional[float] = None
    vwap_lost_after_news: bool = False
    new_high_of_day_made: bool = False
    made_second_leg: bool = False
    initial_spike_only: bool = False
    labeled_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    label_confidence: str = "medium"
    data_quality: DataQuality = DataQuality.FULL

class PatternBucket(BaseModel):
    bucket_name: str = ""
    filter_description: str = ""
    count: int = 0
    clean_expansion_pct: float = 0.0
    second_leg_pct: float = 0.0
    partial_pct: float = 0.0
    failed_pct: float = 0.0
    trap_pct: float = 0.0
    avg_mfe: float = 0.0
    avg_mae: float = 0.0
    avg_move_pct: float = 0.0
    confidence: str = "low"
    sample_size: int = 0

class PatternInsight(BaseModel):
    insight_type: str = ""
    description: str = ""
    pattern_filter: dict = Field(default_factory=dict)
    evidence: str = ""
    sample_size: int = 0
    confidence: str = "low"
    expected_impact: str = ""

class CalibrationRecommendation(BaseModel):
    feature: str = ""
    current_threshold: str = ""
    proposed_threshold: str = ""
    evidence: str = ""
    confidence: str = "low"
    expected_impact: str = ""
    sample_count: int = 0
    rationale: str = ""

class CalibrationWeights(BaseModel):
    version: int = 1
    pre_news_suspicion_w: float = 1.0
    second_leg_probability_w: float = 1.0
    trap_risk_w: float = 1.0
    catalyst_strength_w: float = 1.0
    time_of_day_w: float = 1.0
    float_bucket_w: float = 1.0
    vwap_hold_w: float = 1.0
    volume_acceleration_w: float = 1.0
    quiet_accumulation_w: float = 1.0
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    is_approved: bool = False
    approved_by: str = ""
    notes: str = ""
